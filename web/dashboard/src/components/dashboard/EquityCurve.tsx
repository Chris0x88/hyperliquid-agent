"use client";

import { useEffect, useRef, useState } from "react";
import { theme as t } from "@/lib/theme";

interface Snapshot {
  timestamp_ms: number;
  equity_total: number;
  drawdown_pct: number;
  high_water_mark: number;
}

export function EquityCurve() {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<unknown>(null);
  const [snapshots, setSnapshots] = useState<Snapshot[]>([]);
  const [stats, setStats] = useState({ current: 0, hwm: 0, dd: 0, change24h: 0 });

  // Fetch data
  useEffect(() => {
    async function load() {
      try {
        const res = await fetch("/api/account/equity-curve?limit=1000");
        const data = await res.json();
        setSnapshots(data.snapshots || []);
      } catch { /* ignore */ }
    }
    load();
    const id = setInterval(load, 60000);
    return () => clearInterval(id);
  }, []);

  // Calculate stats
  useEffect(() => {
    if (snapshots.length === 0) return;
    const latest = snapshots[snapshots.length - 1];
    const hwm = Math.max(...snapshots.map((s) => s.equity_total));

    // 24h change
    const oneDayAgo = Date.now() - 86400000;
    const dayAgoSnap = snapshots.find((s) => s.timestamp_ms >= oneDayAgo);
    const change24h = dayAgoSnap
      ? ((latest.equity_total - dayAgoSnap.equity_total) / dayAgoSnap.equity_total) * 100
      : 0;

    setStats({
      current: latest.equity_total,
      hwm,
      dd: latest.drawdown_pct || 0,
      change24h,
    });
  }, [snapshots]);

  // Render chart
  useEffect(() => {
    if (!containerRef.current || snapshots.length === 0) return;

    let cleanup: (() => void) | undefined;

    (async () => {
      const { createChart, ColorType, LineStyle } = await import("lightweight-charts");

      // Clean up previous chart
      if (chartRef.current) {
        (chartRef.current as { remove: () => void }).remove();
      }

      const chart = createChart(containerRef.current!, {
        width: containerRef.current!.clientWidth,
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

      // Equity area series (v5 API: addSeries with AreaSeries type)
      const { AreaSeries } = await import("lightweight-charts");
      const areaSeries = chart.addSeries(AreaSeries, {
        lineColor: t.colors.primary,
        topColor: `${t.colors.primary}40`,
        bottomColor: `${t.colors.primary}05`,
        lineWidth: 2,
        priceFormat: { type: "price", precision: 2, minMove: 0.01 },
      });

      const chartData = snapshots.map((s) => ({
        time: (s.timestamp_ms / 1000) as import("lightweight-charts").UTCTimestamp,
        value: s.equity_total,
      }));

      areaSeries.setData(chartData);
      chart.timeScale().fitContent();
      chartRef.current = chart;

      // Resize observer
      const observer = new ResizeObserver(() => {
        if (containerRef.current) {
          chart.applyOptions({ width: containerRef.current.clientWidth });
        }
      });
      observer.observe(containerRef.current!);

      cleanup = () => {
        observer.disconnect();
        chart.remove();
        chartRef.current = null;
      };
    })();

    return () => cleanup?.();
  }, [snapshots]);

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
            <p className="text-[13px] font-mono" style={{ color: t.colors.text }}>${stats.hwm.toFixed(2)}</p>
          </div>
          <div className="text-right">
            <p className="text-[11px]" style={{ color: t.colors.textMuted }}>Drawdown</p>
            <p className="text-[13px] font-mono" style={{ color: stats.dd > 5 ? t.colors.danger : t.colors.textSecondary }}>
              {stats.dd.toFixed(1)}%
            </p>
          </div>
          <div className="text-right">
            <p className="text-[11px]" style={{ color: t.colors.textMuted }}>24h</p>
            <p className="text-[13px] font-mono" style={{ color: stats.change24h >= 0 ? t.colors.success : t.colors.danger }}>
              {stats.change24h >= 0 ? "+" : ""}{stats.change24h.toFixed(2)}%
            </p>
          </div>
        </div>
      </div>
      <div ref={containerRef} className="w-full" />
      {snapshots.length === 0 && (
        <div className="h-[220px] flex items-center justify-center">
          <p className="text-[13px]" style={{ color: t.colors.textDim }}>Loading equity data...</p>
        </div>
      )}
    </div>
  );
}
