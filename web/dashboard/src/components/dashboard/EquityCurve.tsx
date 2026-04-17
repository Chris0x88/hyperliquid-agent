"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { theme as t } from "@/lib/theme";

interface Snapshot {
  timestamp_ms: number;
  equity_total: number;
  drawdown_pct: number;
  high_water_mark: number;
  spot_usdc: number;
}

interface Stats {
  current: number;
  hwm: number;
  dd: number;
  change24h: number;
  change24hAbs: number;
}

export function EquityCurve() {
  const containerRef = useRef<HTMLDivElement>(null);
  // Store chart API reference — typed as unknown to avoid importing heavyweight
  // lightweight-charts types at module level (they're loaded dynamically).
  const chartRef = useRef<{ remove: () => void; timeScale: () => { fitContent: () => void }; applyOptions: (o: unknown) => void } | null>(null);
  const seriesRef = useRef<{ setData: (d: unknown[]) => void } | null>(null);
  const observerRef = useRef<ResizeObserver | null>(null);
  const [snapshots, setSnapshots] = useState<Snapshot[]>([]);
  const [stats, setStats] = useState<Stats>({ current: 0, hwm: 0, dd: 0, change24h: 0, change24hAbs: 0 });
  const [loading, setLoading] = useState(true);
  const [chartReady, setChartReady] = useState(false);

  // ── Fetch equity snapshots ──────────────────────────────────────────────────
  const loadSnapshots = useCallback(async () => {
    try {
      const res = await fetch("/api/account/equity-curve?limit=1000");
      if (!res.ok) return;
      const data = await res.json();
      setSnapshots(data.snapshots || []);
    } catch {
      // silently ignore network errors — stale data is fine
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadSnapshots();
    const id = setInterval(loadSnapshots, 60_000);
    return () => clearInterval(id);
  }, [loadSnapshots]);

  // ── Calculate stats whenever snapshots change ───────────────────────────────
  useEffect(() => {
    if (snapshots.length === 0) return;

    const latest = snapshots[snapshots.length - 1];

    // HWM: prefer the stored high_water_mark if available, fall back to max
    const storedHwm = Math.max(...snapshots.map((s) => s.high_water_mark || 0));
    const computedHwm = Math.max(...snapshots.map((s) => s.equity_total));
    const hwm = storedHwm > 0 ? storedHwm : computedHwm;

    // Drawdown: use stored value (backend now computes it from HWM if missing)
    const dd = latest.drawdown_pct || 0;

    // 24h change — find the snapshot CLOSEST to 24h ago.
    // snapshots are oldest-first; we want the snapshot whose timestamp is
    // nearest to (now - 24h). Using findLast(ts < cutoff) gives us the last
    // snapshot BEFORE the 24h mark, which is the most accurate baseline.
    const oneDayAgo = Date.now() - 86_400_000;
    let dayAgoSnap: Snapshot | undefined;

    // Walk backwards to find the last snapshot before the cutoff
    for (let i = snapshots.length - 1; i >= 0; i--) {
      if (snapshots[i].timestamp_ms <= oneDayAgo) {
        dayAgoSnap = snapshots[i];
        break;
      }
    }

    // Fallback to the oldest snapshot if all are within 24h (account < 1 day old)
    if (!dayAgoSnap && snapshots.length > 0) {
      dayAgoSnap = snapshots[0];
    }

    const change24h =
      dayAgoSnap && dayAgoSnap.equity_total > 0
        ? ((latest.equity_total - dayAgoSnap.equity_total) / dayAgoSnap.equity_total) * 100
        : 0;
    const change24hAbs =
      dayAgoSnap ? latest.equity_total - dayAgoSnap.equity_total : 0;

    setStats({ current: latest.equity_total, hwm, dd, change24h, change24hAbs });
  }, [snapshots]);

  // ── Initialise chart on mount ───────────────────────────────────────────────
  // Chart is created once; data is updated via seriesRef when snapshots change.
  // This avoids re-creating the chart (which is expensive and causes flicker)
  // every time data refreshes.
  useEffect(() => {
    if (!containerRef.current) return;

    let cancelled = false;

    (async () => {
      const { createChart, ColorType, LineStyle, AreaSeries } = await import("lightweight-charts");
      if (cancelled || !containerRef.current) return;

      // Clean up any previous chart instance
      if (chartRef.current) {
        chartRef.current.remove();
        chartRef.current = null;
        seriesRef.current = null;
      }

      const chart = createChart(containerRef.current, {
        width: containerRef.current.clientWidth,
        height: 220,
        layout: {
          background: { type: ColorType.Solid, color: "transparent" },
          textColor: t.colors.textDim,
          fontFamily: t.fonts.body,
          fontSize: 11,
        },
        grid: {
          vertLines: { color: t.colors.borderLight, style: LineStyle.Dotted },
          horzLines: { color: t.colors.borderLight, style: LineStyle.Dotted },
        },
        rightPriceScale: {
          borderColor: t.colors.border,
          scaleMargins: { top: 0.1, bottom: 0.05 },
        },
        timeScale: {
          borderColor: t.colors.border,
          timeVisible: true,
        },
        crosshair: {
          horzLine: { color: t.colors.secondary, labelBackgroundColor: t.colors.surface },
          vertLine: { color: t.colors.secondary, labelBackgroundColor: t.colors.surface },
        },
        handleScale: false,
        handleScroll: false,
      });

      const areaSeries = chart.addSeries(AreaSeries, {
        lineColor: t.colors.primary,
        topColor: `${t.colors.primary}40`,
        bottomColor: `${t.colors.primary}05`,
        lineWidth: 2,
        priceFormat: { type: "price", precision: 2, minMove: 0.01 },
      });

      chartRef.current = chart as unknown as typeof chartRef.current;
      seriesRef.current = areaSeries as unknown as typeof seriesRef.current;

      // Resize observer — keeps chart width in sync with container
      if (observerRef.current) observerRef.current.disconnect();
      const ro = new ResizeObserver(() => {
        if (containerRef.current && chartRef.current) {
          chartRef.current.applyOptions({ width: containerRef.current.clientWidth });
        }
      });
      ro.observe(containerRef.current);
      observerRef.current = ro;

      setChartReady(true);
    })();

    return () => {
      cancelled = true;
      observerRef.current?.disconnect();
      if (chartRef.current) {
        chartRef.current.remove();
        chartRef.current = null;
        seriesRef.current = null;
      }
      setChartReady(false);
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Push data to chart whenever snapshots or chart readiness changes ─────────
  useEffect(() => {
    if (!chartReady || !seriesRef.current || snapshots.length === 0) return;

    type UTCTimestamp = number & { readonly __brand: unique symbol };

    const chartData = snapshots.map((s) => ({
      time: Math.floor(s.timestamp_ms / 1000) as UTCTimestamp,
      value: s.equity_total,
    }));

    seriesRef.current.setData(chartData);
    chartRef.current?.timeScale().fitContent();
  }, [snapshots, chartReady]);

  return (
    <div className="rounded-lg p-5" style={{ background: t.colors.surface, border: `1px solid ${t.colors.border}` }}>
      <div className="flex items-center justify-between mb-4">
        <h3
          className="text-[13px] font-medium"
          style={{ color: t.colors.textMuted, textTransform: "uppercase", letterSpacing: "0.05em", fontFamily: t.fonts.heading }}
        >
          Equity Curve
        </h3>
        <div className="flex gap-4">
          <div className="text-right">
            <p className="text-[11px]" style={{ color: t.colors.textMuted }}>HWM</p>
            <p className="text-[13px] font-mono" style={{ color: t.colors.text }}>
              {stats.hwm > 0 ? `$${stats.hwm.toFixed(2)}` : "—"}
            </p>
          </div>
          <div className="text-right">
            <p className="text-[11px]" style={{ color: t.colors.textMuted }}>Drawdown</p>
            <p className="text-[13px] font-mono" style={{ color: stats.dd > 5 ? t.colors.danger : t.colors.textSecondary }}>
              {stats.dd > 0 ? `${stats.dd.toFixed(1)}%` : "0.0%"}
            </p>
          </div>
          <div className="text-right">
            <p className="text-[11px]" style={{ color: t.colors.textMuted }}>24h</p>
            {snapshots.length > 1 ? (
              <p className="text-[13px] font-mono" style={{ color: stats.change24h >= 0 ? t.colors.success : t.colors.danger }}>
                {stats.change24h >= 0 ? "+" : ""}
                {stats.change24h.toFixed(2)}%
                <span className="text-[10px] ml-1" style={{ color: stats.change24hAbs >= 0 ? t.colors.success : t.colors.danger }}>
                  ({stats.change24hAbs >= 0 ? "+" : ""}${stats.change24hAbs.toFixed(0)})
                </span>
              </p>
            ) : (
              <p className="text-[13px] font-mono" style={{ color: t.colors.textDim }}>—</p>
            )}
          </div>
        </div>
      </div>

      {/* Chart container — always rendered so the ResizeObserver target exists */}
      <div ref={containerRef} className="w-full" style={{ minHeight: 220 }}>
        {(loading || snapshots.length === 0) && (
          <div
            className="flex items-center justify-center"
            style={{ height: 220, color: t.colors.textDim, fontSize: 13 }}
          >
            {loading ? "Loading equity data..." : "No equity history yet — starts accumulating on first daemon tick"}
          </div>
        )}
      </div>
    </div>
  );
}
