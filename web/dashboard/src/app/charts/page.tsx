"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import {
  createChart,
  createSeriesMarkers,
  CandlestickSeries,
  LineSeries,
  HistogramSeries,
  AreaSeries,
  type IChartApi,
  type ISeriesApi,
  type ISeriesMarkersPluginApi,
  type CandlestickData,
  type LineData,
  type HistogramData,
  type Time,
  type SeriesMarker,
  type SeriesType,
} from "lightweight-charts";
import { theme as t } from "@/lib/theme";
import { sma, ema, bollingerBands } from "@/lib/indicators";
import { usePolling } from "@/lib/hooks";
import {
  getAccountStatus,
  getChartMarkers,
  getChartOverlay,
  computeChartSignal,
  type Position,
  type NewsMarker,
  type TradeMarker,
  type LessonMarker,
  type ChartMarkersResponse,
  type ChartOverlayResponse,
  type SignalResult,
  type SignalMarker,
} from "@/lib/api";
import SignalTogglePanel, {
  loadActiveSlugs,
  saveActiveSlugs,
  resolveSignalColor,
  type SignalToggleState,
} from "@/components/charts/SignalTogglePanel";

// ─── Types ────────────────────────────────────────────────────────────────────

interface Candle {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

interface CandleResponse {
  coin: string;
  interval: string;
  candles: Candle[];
}

// ─── Constants ────────────────────────────────────────────────────────────────

const MARKETS = ["BTC", "BRENTOIL", "GOLD", "SILVER", "CL", "SP500"] as const;
type Market = (typeof MARKETS)[number];

const INTERVALS = [
  { value: "1m", label: "1m" },
  { value: "5m", label: "5m" },
  { value: "15m", label: "15m" },
  { value: "1h", label: "1H" },
  { value: "4h", label: "4H" },
  { value: "1d", label: "1D" },
] as const;
type Interval = (typeof INTERVALS)[number]["value"];

interface IndicatorState {
  bb: boolean;
  sma50: boolean;
  sma200: boolean;
  ema12: boolean;
  ema26: boolean;
}

const DEFAULT_INDICATORS: IndicatorState = {
  bb: true,
  sma50: true,
  sma200: false,
  ema12: false,
  ema26: false,
};

const INDICATOR_LABELS: Record<keyof IndicatorState, string> = {
  bb: "BB (20)",
  sma50: "SMA 50",
  sma200: "SMA 200",
  ema12: "EMA 12",
  ema26: "EMA 26",
};

const IND_COLORS = {
  bbUpper: t.colors.tertiary,
  bbMiddle: "rgba(135,202,230,0.55)",
  bbLower: t.colors.tertiary,
  sma50: t.colors.primary,
  sma200: t.colors.secondary,
  ema12: "#c084fc",
  ema26: "#f472b6",
};

// Severity → color for news markers
const SEVERITY_COLORS: Record<number, string> = {
  5: t.colors.danger,
  4: t.colors.warning,
  3: t.colors.tertiary,
  2: t.colors.textMuted,
  1: t.colors.textDim,
};

function severityColor(n: number): string {
  return SEVERITY_COLORS[Math.min(5, Math.max(1, n))] ?? t.colors.textDim;
}

// ─── Tiny helpers ─────────────────────────────────────────────────────────────

function toLineData(candles: Candle[], values: (number | null)[]): LineData[] {
  const out: LineData[] = [];
  for (let i = 0; i < candles.length; i++) {
    if (values[i] !== null) {
      out.push({ time: candles[i].time as Time, value: values[i] as number });
    }
  }
  return out;
}

function fmtTs(unix: number): string {
  return new Date(unix * 1000).toLocaleString("en-AU", {
    timeZone: "Australia/Brisbane",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function fmtPnl(v: number) {
  const color = v >= 0 ? t.colors.success : t.colors.danger;
  const sign = v >= 0 ? "+" : "";
  return { text: `${sign}$${v.toFixed(2)}`, color };
}

// ─── Segmented control ────────────────────────────────────────────────────────

function SegmentedControl<T extends string>({
  options,
  value,
  onChange,
}: {
  options: { value: T; label: string }[];
  value: T;
  onChange: (v: T) => void;
}) {
  return (
    <div
      className="flex rounded-lg overflow-hidden"
      style={{ border: `1px solid ${t.colors.border}`, background: t.colors.bg }}
    >
      {options.map((opt) => {
        const active = opt.value === value;
        return (
          <button
            key={opt.value}
            onClick={() => onChange(opt.value)}
            className="px-3 py-1.5 text-[12px] font-medium transition-all duration-100"
            style={{
              background: active ? t.colors.primaryLight : "transparent",
              color: active ? t.colors.primary : t.colors.textMuted,
              borderRight: `1px solid ${t.colors.border}`,
              cursor: "pointer",
            }}
          >
            {opt.label}
          </button>
        );
      })}
    </div>
  );
}

function IndicatorToggle({
  label,
  active,
  color,
  onToggle,
}: {
  label: string;
  active: boolean;
  color: string;
  onToggle: () => void;
}) {
  return (
    <button
      onClick={onToggle}
      className="flex items-center gap-1.5 px-2.5 py-1 rounded text-[11px] font-medium"
      style={{
        background: active ? "rgba(255,255,255,0.06)" : "transparent",
        color: active ? t.colors.text : t.colors.textDim,
        border: `1px solid ${active ? color + "55" : t.colors.borderLight}`,
        cursor: "pointer",
      }}
      aria-pressed={active}
    >
      <span
        className="w-2.5 h-2.5 rounded-sm flex-shrink-0"
        style={{ background: active ? color : t.colors.textDim }}
      />
      {label}
    </button>
  );
}

// ─── Marker toggles (P0 fix 2026-04-17 — replaces sprint-1 agent A's
// hallucinated MarkerToggleBar that never landed in the file).
// Persists to localStorage so toggle state survives reload + nav.
// ─────────────────────────────────────────────────────────────────────────────

type MarkerKey = "news" | "trades" | "lessons" | "critiques";

const MARKER_DEFAULTS: Record<MarkerKey, boolean> = {
  news: true,
  trades: false,    // Default OFF — these were the "DEL" stack the operator
                    // explicitly complained about. Easy to turn on, off by default.
  lessons: false,
  critiques: true,  // Default ON — entry critiques are highest signal/noise
                    // ratio (one per new entry, with grade) and surface
                    // bot's read on the operator's trade decision.
};

const MARKER_LABELS: Record<MarkerKey, string> = {
  news: "News",
  trades: "Trade actions",
  lessons: "Lessons",
  critiques: "Critiques",
};

const MARKER_COLORS: Record<MarkerKey, string> = {
  news: "#3b82f6",      // blue
  trades: "#a78bfa",    // violet — distinct from SL red and TP green
  lessons: "#facc15",   // amber
  critiques: "#14b8a6", // teal — distinct from everything else
};

const MARKER_LS_KEY = "charts.markerToggles.v1";

function loadMarkerToggles(): Record<MarkerKey, boolean> {
  if (typeof window === "undefined") return MARKER_DEFAULTS;
  try {
    const raw = localStorage.getItem(MARKER_LS_KEY);
    if (!raw) return MARKER_DEFAULTS;
    const parsed = JSON.parse(raw) as Partial<Record<MarkerKey, boolean>>;
    return { ...MARKER_DEFAULTS, ...parsed };
  } catch {
    return MARKER_DEFAULTS;
  }
}

function MarkerToggle({
  active, label, color, onToggle, count,
}: { active: boolean; label: string; color: string; onToggle: () => void; count?: number }) {
  return (
    <button
      onClick={onToggle}
      className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[11px] font-medium transition-all"
      style={{
        background: active ? `${color}22` : t.colors.surfaceHover,
        border: `1px solid ${active ? color : t.colors.border}`,
        color: active ? color : t.colors.textMuted,
        cursor: "pointer",
      }}
    >
      <span
        className="w-1.5 h-1.5 rounded-full"
        style={{ background: active ? color : t.colors.textDim }}
      />
      {label}{typeof count === "number" ? ` (${count})` : ""}
    </button>
  );
}

// ─── Chart handle ─────────────────────────────────────────────────────────────

interface ChartHandle {
  updateTick: (candles: Candle[]) => void;
  setMarkers: (markers: SeriesMarker<Time>[]) => void;
  drawPositionLines: (positions: Position[]) => void;
  /** Add or update a signal series. Idempotent — calling twice with the
   *  same slug replaces the existing data. */
  upsertSignal: (result: SignalResult) => void;
  /** Remove a signal series + any marker plugin it owns. */
  removeSignal: (slug: string) => void;
  /** Remove all signal series (used on coin/interval change before refetch). */
  clearSignals: () => void;
}

// ─── Popover ──────────────────────────────────────────────────────────────────

interface PopoverData {
  title: string;
  lines: { label: string; value: string; color?: string }[];
}

function Popover({ data, onClose }: { data: PopoverData; onClose: () => void }) {
  return (
    <div
      className="absolute top-4 right-4 z-30 rounded-xl p-4 shadow-2xl w-72"
      style={{ background: t.colors.surface, border: `1px solid ${t.colors.border}` }}
    >
      <div className="flex items-start justify-between mb-3">
        <span className="text-[13px] font-semibold" style={{ color: t.colors.text, fontFamily: t.fonts.heading }}>
          {data.title}
        </span>
        <button
          onClick={onClose}
          className="text-[12px] px-2 py-0.5 rounded"
          style={{ color: t.colors.textMuted, cursor: "pointer" }}
        >
          x
        </button>
      </div>
      <div className="space-y-2">
        {data.lines.map((l, i) => (
          <div key={i} className="flex justify-between gap-4">
            <span className="text-[11px]" style={{ color: t.colors.textMuted }}>{l.label}</span>
            <span
              className="text-[11px] text-right"
              style={{ color: l.color ?? t.colors.text, fontFamily: t.fonts.mono, maxWidth: "60%", overflow: "hidden", textOverflow: "ellipsis" }}
            >
              {l.value}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ─── Main CandleChart component ───────────────────────────────────────────────

function CandleChart({
  candles,
  indicators,
  markers,
  handleRef,
  onMarkerClick,
}: {
  candles: Candle[];
  indicators: IndicatorState;
  markers: SeriesMarker<Time>[];
  handleRef: React.MutableRefObject<ChartHandle | null>;
  onMarkerClick?: (markerTime: number) => void;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volumeSeriesRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  const bbUpperRef = useRef<ISeriesApi<"Line"> | null>(null);
  const bbMiddleRef = useRef<ISeriesApi<"Line"> | null>(null);
  const bbLowerRef = useRef<ISeriesApi<"Line"> | null>(null);
  const sma50Ref = useRef<ISeriesApi<"Line"> | null>(null);
  const sma200Ref = useRef<ISeriesApi<"Line"> | null>(null);
  const ema12Ref = useRef<ISeriesApi<"Line"> | null>(null);
  const ema26Ref = useRef<ISeriesApi<"Line"> | null>(null);
  // v5 markers plugin (replaces deprecated series.setMarkers)
  const markersPluginRef = useRef<ISeriesMarkersPluginApi<Time> | null>(null);

  // Create chart on mount
  useEffect(() => {
    if (!containerRef.current) return;

    const chart = createChart(containerRef.current, {
      layout: {
        background: { color: t.colors.surface },
        textColor: t.colors.textSecondary,
        fontFamily: t.fonts.body,
        fontSize: 11,
      },
      grid: {
        vertLines: { color: t.colors.borderLight },
        horzLines: { color: t.colors.borderLight },
      },
      crosshair: {
        vertLine: { color: t.colors.border, labelBackgroundColor: t.colors.surface },
        horzLine: { color: t.colors.border, labelBackgroundColor: t.colors.surface },
      },
      timeScale: {
        borderColor: t.colors.border,
        timeVisible: true,
        secondsVisible: false,
      },
      rightPriceScale: { borderColor: t.colors.border },
      width: containerRef.current.clientWidth,
      height: 440,
    });
    chartRef.current = chart;

    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: t.colors.success,
      downColor: t.colors.danger,
      borderUpColor: t.colors.success,
      borderDownColor: t.colors.danger,
      wickUpColor: t.colors.success,
      wickDownColor: t.colors.danger,
    });
    candleSeriesRef.current = candleSeries;

    const volumeSeries = chart.addSeries(HistogramSeries, {
      color: "rgba(162, 107, 50, 0.4)",
      priceFormat: { type: "volume" },
      priceScaleId: "volume",
    });
    chart.priceScale("volume").applyOptions({
      scaleMargins: { top: 0.82, bottom: 0 },
      borderVisible: false,
    });
    volumeSeriesRef.current = volumeSeries;

    const bbLineOpts = {
      color: IND_COLORS.bbUpper,
      lineWidth: 1 as const,
      lineStyle: 2 as const,
      lastValueVisible: false,
      priceLineVisible: false,
    };
    bbUpperRef.current = chart.addSeries(LineSeries, bbLineOpts);
    bbLowerRef.current = chart.addSeries(LineSeries, bbLineOpts);
    bbMiddleRef.current = chart.addSeries(LineSeries, {
      color: IND_COLORS.bbMiddle, lineWidth: 1 as const, lineStyle: 2 as const,
      lastValueVisible: false, priceLineVisible: false,
    });

    sma50Ref.current = chart.addSeries(LineSeries, {
      color: IND_COLORS.sma50, lineWidth: 1 as const, lastValueVisible: true, priceLineVisible: false,
    });
    sma200Ref.current = chart.addSeries(LineSeries, {
      color: IND_COLORS.sma200, lineWidth: 1 as const, lastValueVisible: true, priceLineVisible: false,
    });
    ema12Ref.current = chart.addSeries(LineSeries, {
      color: IND_COLORS.ema12, lineWidth: 1 as const, lastValueVisible: true, priceLineVisible: false,
    });
    ema26Ref.current = chart.addSeries(LineSeries, {
      color: IND_COLORS.ema26, lineWidth: 1 as const, lastValueVisible: true, priceLineVisible: false,
    });

    // Create the v5 markers plugin (attached to candleSeries)
    markersPluginRef.current = createSeriesMarkers(candleSeries, []);

    // Expose handles
    // Position price-lines are stored so toggle off can remove them cleanly.
    // P0 fix 2026-04-17 — SL/TP/Liq/Entry rendered as horizontal price lines
    // (NOT markers) per Chris's spec. Lines persist across the visible range,
    // unlike markers which are point-in-time. createPriceLine returns a
    // handle we keep so we can removePriceLine() on update.
    const positionPriceLines: Array<ReturnType<typeof candleSeries.createPriceLine>> = [];

    // Phase 4 — signal registry: slug → series + optional markers plugin.
    // Sub-pane signals get their own pane (lightweight-charts v5 addPane).
    // Sub-pane index is allocated on first use and reused across re-fetches
    // for the same slug so the pane doesn't flicker.
    interface SignalEntry {
      series: ISeriesApi<SeriesType>;
      markersPlugin: ISeriesMarkersPluginApi<Time> | null;
      paneIndex: number; // 0 = main, >0 = sub-pane
    }
    const signalEntries = new Map<string, SignalEntry>();
    // Track next free pane index. Pane 0 is always the main price pane.
    let nextPaneIndex = 1;

    const mapMarkerShape = (shape: string): "circle" | "square" | "arrowUp" | "arrowDown" => {
      switch (shape) {
        case "arrowUp":
        case "arrowDown":
        case "circle":
        case "square":
          return shape;
        default:
          return "circle";
      }
    };
    const mapMarkerPosition = (p: string): "aboveBar" | "belowBar" | "inBar" => {
      switch (p) {
        case "aboveBar":
        case "belowBar":
        case "inBar":
          return p;
        default:
          return "aboveBar";
      }
    };

    handleRef.current = {
      updateTick: (tickCandles: Candle[]) => {
        for (const c of tickCandles) {
          candleSeriesRef.current?.update({ time: c.time as Time, open: c.open, high: c.high, low: c.low, close: c.close });
          volumeSeriesRef.current?.update({
            time: c.time as Time, value: c.volume,
            color: c.close >= c.open ? "rgba(34, 197, 94, 0.35)" : "rgba(239, 68, 68, 0.35)",
          });
        }
      },
      setMarkers: (m: SeriesMarker<Time>[]) => {
        markersPluginRef.current?.setMarkers(m);
      },
      drawPositionLines: (positions: Position[]) => {
        if (!candleSeriesRef.current) return;
        // Wipe existing lines first; createPriceLine has no replace-all API.
        for (const ln of positionPriceLines) {
          try { candleSeriesRef.current.removePriceLine(ln); } catch { /* already gone */ }
        }
        positionPriceLines.length = 0;
        for (const p of positions) {
          const entry = parseFloat(p.entryPx);
          const liq = p.liquidationPx ? parseFloat(p.liquidationPx) : null;
          const isLong = parseFloat(p.szi) > 0;
          // Entry line (white solid)
          if (entry > 0) {
            positionPriceLines.push(
              candleSeriesRef.current.createPriceLine({
                price: entry,
                color: "#f3f4f6",
                lineWidth: 1,
                lineStyle: 0, // Solid
                axisLabelVisible: true,
                title: `Entry ${isLong ? "L" : "S"} ${parseFloat(p.szi).toFixed(4)}`,
              })
            );
          }
          // Liquidation line (orange dashed)
          if (liq && liq > 0) {
            positionPriceLines.push(
              candleSeriesRef.current.createPriceLine({
                price: liq,
                color: "#fb923c",
                lineWidth: 1,
                lineStyle: 2, // Dashed
                axisLabelVisible: true,
                title: `LIQ ${liq.toFixed(2)}`,
              })
            );
          }
          // Note: SL/TP price lines require fetching open trigger orders per
          // position. That endpoint exists (/api/account/orders); a future
          // pass should pair them by coin and add red/green dashed lines.
          // Today we render entry + liq only — those are the highest-value
          // levels and don't need a second API call.
        }
      },

      // ── Signal series management (Phase 4) ────────────────────────────
      upsertSignal: (result: SignalResult) => {
        if (!chartRef.current || !result.chart_spec) return;
        const spec = result.chart_spec;
        const slug = result.slug;
        const color = resolveSignalColor(spec.color);

        // Convert [timestamp_ms, value] → {time, value} (seconds).
        const lineData: LineData[] = [];
        const histData: HistogramData[] = [];
        for (const [tsMs, v] of result.values) {
          if (v === null || v === undefined || Number.isNaN(v)) continue;
          const time = Math.floor(tsMs / 1000) as Time;
          if (spec.series_type === "histogram") {
            histData.push({ time, value: v, color });
          } else {
            lineData.push({ time, value: v });
          }
        }

        // Resolve an existing entry (refresh-in-place) or allocate a new one.
        let entry = signalEntries.get(slug);

        if (entry) {
          // Refresh data on the existing series.
          if (spec.series_type === "histogram") {
            (entry.series as ISeriesApi<"Histogram">).setData(histData);
          } else {
            (entry.series as ISeriesApi<"Line" | "Area">).setData(lineData);
          }
        } else {
          // Allocate a pane for sub-pane placements. v5 supports addPane().
          let paneIndex = 0;
          if (spec.placement === "subpane") {
            paneIndex = nextPaneIndex++;
            try {
              chartRef.current.addPane(true);
            } catch {
              // If addPane is unavailable for any reason we fall back to
              // drawing on pane 0 with a dedicated priceScaleId — still
              // gives a distinct axis, just not a split frame.
              paneIndex = 0;
            }
          }

          // Build series-type-specific options. priceScaleId isolates the
          // signal's scale from price so an oscillator doesn't squash candles.
          const priceScaleId =
            spec.placement === "subpane"
              ? `signal-${slug}`
              : spec.axis === "price"
                ? "right"
                : `signal-${slug}`;

          const commonOpts = {
            color,
            lineWidth: 2 as const,
            priceScaleId,
            lastValueVisible: true,
            priceLineVisible: false,
            title: spec.series_name || slug,
          };

          let series: ISeriesApi<SeriesType>;
          try {
            if (spec.series_type === "histogram") {
              series = chartRef.current.addSeries(
                HistogramSeries,
                { color, priceScaleId, priceFormat: { type: "volume" } },
                paneIndex,
              ) as ISeriesApi<SeriesType>;
              (series as ISeriesApi<"Histogram">).setData(histData);
            } else if (spec.series_type === "area") {
              series = chartRef.current.addSeries(
                AreaSeries,
                {
                  lineColor: color,
                  topColor: color,
                  bottomColor: `${color}10`,
                  priceScaleId,
                  lastValueVisible: true,
                  priceLineVisible: false,
                },
                paneIndex,
              ) as ISeriesApi<SeriesType>;
              (series as ISeriesApi<"Area">).setData(lineData);
            } else {
              // line, band, markers-only → line series (markers-only series
              // still needs a line to anchor the marker plugin; we draw it
              // with lineWidth 0 / transparent by using the color alpha
              // — but lightweight-charts doesn't render empty lines, so
              // we keep a faint visible line).
              series = chartRef.current.addSeries(
                LineSeries,
                commonOpts,
                paneIndex,
              ) as ISeriesApi<SeriesType>;
              (series as ISeriesApi<"Line">).setData(lineData);
            }
          } catch (e) {
            console.warn(`Signal ${slug} failed to render:`, e);
            return;
          }

          entry = { series, markersPlugin: null, paneIndex };
          signalEntries.set(slug, entry);
        }

        // Markers — use the markers plugin on the signal series so they
        // align with the signal's own scale/pane.
        if (result.markers && result.markers.length > 0) {
          const mapped: SeriesMarker<Time>[] = result.markers.map((m: SignalMarker) => ({
            time: Math.floor(m.time / 1000) as Time,
            position: mapMarkerPosition(m.position),
            color: resolveSignalColor(m.color || spec.color),
            shape: mapMarkerShape(m.shape),
            text: m.text,
            size: 1,
          }));
          mapped.sort((a, b) => (a.time as number) - (b.time as number));
          if (!entry.markersPlugin) {
            entry.markersPlugin = createSeriesMarkers(entry.series, mapped);
          } else {
            entry.markersPlugin.setMarkers(mapped);
          }
        } else if (entry.markersPlugin) {
          entry.markersPlugin.setMarkers([]);
        }
      },

      removeSignal: (slug: string) => {
        const entry = signalEntries.get(slug);
        if (!entry || !chartRef.current) return;
        try {
          entry.markersPlugin?.detach();
        } catch { /* plugin already detached */ }
        try {
          chartRef.current.removeSeries(entry.series);
        } catch { /* already removed */ }
        // Note: we deliberately don't remove the pane — v5 keeps an empty
        // pane around and re-toggling the same signal will reuse it via
        // nextPaneIndex. Panes are cheap; removing them mid-session causes
        // layout jumps.
        signalEntries.delete(slug);
      },

      clearSignals: () => {
        for (const slug of [...signalEntries.keys()]) {
          const entry = signalEntries.get(slug);
          if (!entry || !chartRef.current) continue;
          try { entry.markersPlugin?.detach(); } catch { /* */ }
          try { chartRef.current.removeSeries(entry.series); } catch { /* */ }
          signalEntries.delete(slug);
        }
        nextPaneIndex = 1;
      },
    };

    // Click handler — propagate marker time back up
    chart.subscribeClick((param) => {
      if (!param.time) return;
      onMarkerClick?.(param.time as number);
    });

    const ro = new ResizeObserver(() => {
      if (containerRef.current && chartRef.current) {
        chartRef.current.applyOptions({ width: containerRef.current.clientWidth });
      }
    });
    ro.observe(containerRef.current);

    return () => {
      ro.disconnect();
      chart.remove();
      chartRef.current = null;
      handleRef.current = null;
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Load candle data
  useEffect(() => {
    if (!candles.length) return;
    const closes = candles.map((c) => c.close);

    const candleData: CandlestickData[] = candles.map((c) => ({
      time: c.time as Time, open: c.open, high: c.high, low: c.low, close: c.close,
    }));
    candleSeriesRef.current?.setData(candleData);

    const volumeData: HistogramData[] = candles.map((c) => ({
      time: c.time as Time, value: c.volume,
      color: c.close >= c.open ? "rgba(34, 197, 94, 0.35)" : "rgba(239, 68, 68, 0.35)",
    }));
    volumeSeriesRef.current?.setData(volumeData);

    const bb = bollingerBands(closes, 20, 2);
    bbUpperRef.current?.setData(toLineData(candles, bb.upper));
    bbMiddleRef.current?.setData(toLineData(candles, bb.middle));
    bbLowerRef.current?.setData(toLineData(candles, bb.lower));
    sma50Ref.current?.setData(toLineData(candles, sma(closes, 50)));
    sma200Ref.current?.setData(toLineData(candles, sma(closes, 200)));
    ema12Ref.current?.setData(toLineData(candles, ema(closes, 12)));
    ema26Ref.current?.setData(toLineData(candles, ema(closes, 26)));

    chartRef.current?.timeScale().fitContent();
  }, [candles]);

  // Sync indicators visibility
  useEffect(() => {
    const applyVisibility = (ref: React.MutableRefObject<ISeriesApi<"Line"> | null>, visible: boolean) => {
      ref.current?.applyOptions({ visible });
    };
    applyVisibility(bbUpperRef, indicators.bb);
    applyVisibility(bbMiddleRef, indicators.bb);
    applyVisibility(bbLowerRef, indicators.bb);
    applyVisibility(sma50Ref, indicators.sma50);
    applyVisibility(sma200Ref, indicators.sma200);
    applyVisibility(ema12Ref, indicators.ema12);
    applyVisibility(ema26Ref, indicators.ema26);
  }, [indicators]);

  // Set markers via the v5 plugin
  useEffect(() => {
    markersPluginRef.current?.setMarkers(markers);
  }, [markers]);

  return (
    <div
      ref={containerRef}
      className="w-full rounded-lg overflow-hidden"
      style={{ height: 440, background: t.colors.surface }}
    />
  );
}

// ─── Position card (sidebar) ──────────────────────────────────────────────────

function PositionCard({ pos }: { pos: Position }) {
  const pnl = parseFloat(pos.unrealizedPnl);
  const value = parseFloat(pos.positionValue);
  const entry = parseFloat(pos.entryPx);
  const size = parseFloat(pos.szi);
  const side = size > 0 ? "LONG" : "SHORT";
  const roe = parseFloat(pos.returnOnEquity) * 100;
  const sideColor = side === "LONG" ? t.colors.success : t.colors.danger;

  return (
    <div className="rounded-lg p-3" style={{ background: t.colors.bg, border: `1px solid ${t.colors.border}` }}>
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <span className="text-[13px] font-semibold" style={{ color: t.colors.text, fontFamily: t.fonts.heading }}>{pos.coin}</span>
          <span className="px-1.5 py-0.5 rounded text-[10px] font-semibold uppercase"
            style={{ background: `${sideColor}18`, color: sideColor, border: `1px solid ${sideColor}35` }}>
            {side}
          </span>
        </div>
        <span className="text-[11px]" style={{ color: t.colors.textMuted }}>{pos.leverage.value}x</span>
      </div>
      <div className="grid grid-cols-2 gap-2">
        <div>
          <p className="text-[10px]" style={{ color: t.colors.textMuted }}>Entry</p>
          <p className="text-[12px]" style={{ color: t.colors.text, fontFamily: t.fonts.mono }}>${entry.toFixed(2)}</p>
        </div>
        <div>
          <p className="text-[10px]" style={{ color: t.colors.textMuted }}>uPnL</p>
          <p className="text-[12px]" style={{ color: pnl >= 0 ? t.colors.success : t.colors.danger, fontFamily: t.fonts.mono }}>
            ${pnl.toFixed(2)} ({roe >= 0 ? "+" : ""}{roe.toFixed(1)}%)
          </p>
        </div>
        <div>
          <p className="text-[10px]" style={{ color: t.colors.textMuted }}>Size</p>
          <p className="text-[12px]" style={{ color: t.colors.text, fontFamily: t.fonts.mono }}>{Math.abs(size).toFixed(4)}</p>
        </div>
        <div>
          <p className="text-[10px]" style={{ color: t.colors.textMuted }}>Liq.</p>
          <p className="text-[12px]" style={{ color: t.colors.danger, fontFamily: t.fonts.mono }}>
            {pos.liquidationPx ? `$${parseFloat(pos.liquidationPx).toFixed(2)}` : "N/A"}
          </p>
        </div>
      </div>
      <div className="mt-2 pt-2" style={{ borderTop: `1px solid ${t.colors.borderLight}` }}>
        <p className="text-[10px]" style={{ color: t.colors.textMuted }}>Value</p>
        <p className="text-[12px]" style={{ color: t.colors.text, fontFamily: t.fonts.mono }}>${value.toFixed(2)}</p>
      </div>
    </div>
  );
}

// ─── Right sidebar ────────────────────────────────────────────────────────────

function RightSidebar({
  market,
  markersData,
  overlayData,
  showManipOverlay,
  onToggleManip,
}: {
  market: string;
  markersData: ChartMarkersResponse | null;
  overlayData: ChartOverlayResponse | null;
  showManipOverlay: boolean;
  onToggleManip: () => void;
}) {
  const { data: accountData } = usePolling(getAccountStatus, 10_000);
  const matchingPositions = accountData?.positions.filter(
    (p) => p.coin.replace("xyz:", "").toUpperCase() === market.toUpperCase()
  ) ?? [];

  return (
    <div
      className="flex flex-col gap-4 overflow-y-auto"
      style={{ width: 264, flexShrink: 0 }}
    >
      {/* Position card */}
      <Panel title="Position">
        {matchingPositions.length === 0 ? (
          <p className="text-[12px] px-3 pb-3" style={{ color: t.colors.textMuted }}>
            No open position for {market}
          </p>
        ) : (
          <div className="px-3 pb-3 space-y-2">
            {matchingPositions.map((p) => <PositionCard key={p.coin} pos={p} />)}
          </div>
        )}
      </Panel>

      {/* Manipulation overlay toggle */}
      <Panel title="Manipulation Overlay">
        <div className="px-3 pb-3 space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-[12px]" style={{ color: t.colors.textMuted }}>Sweep-risk overlay</span>
            <button
              onClick={onToggleManip}
              className="px-2.5 py-1 rounded text-[11px] font-medium"
              style={{
                background: showManipOverlay ? t.colors.dangerLight : t.colors.neutralLight,
                color: showManipOverlay ? t.colors.danger : t.colors.textMuted,
                border: `1px solid ${showManipOverlay ? t.colors.dangerBorder : t.colors.border}`,
                cursor: "pointer",
              }}
            >
              {showManipOverlay ? "On" : "Off"}
            </button>
          </div>
          {overlayData?.sweep_risk && (
            <div>
              <div className="flex justify-between items-center mb-1">
                <span className="text-[10px]" style={{ color: t.colors.textDim }}>Sweep Risk Score</span>
                <span className="text-[11px]" style={{ color: t.colors.textMuted, fontFamily: t.fonts.mono }}>
                  {overlayData.sweep_risk.stub ? "—" : overlayData.sweep_risk.score}
                </span>
              </div>
              {overlayData.sweep_risk.stub && (
                <p className="text-[10px]" style={{ color: t.colors.textDim }}>
                  Awaiting Phase 2 sweep_detector
                </p>
              )}
            </div>
          )}
          {overlayData && overlayData.liq_zones.length > 0 && (
            <div>
              <p className="text-[10px] uppercase tracking-wide mb-1.5" style={{ color: t.colors.textDim }}>
                Liq. Zones ({overlayData.liq_zones.length})
              </p>
              <div className="space-y-1 max-h-40 overflow-y-auto">
                {overlayData.liq_zones.slice(-8).map((z, i) => (
                  <div key={i} className="flex justify-between text-[10px]">
                    <span style={{ color: z.side === "bid" ? t.colors.success : t.colors.danger }}>
                      {z.side.toUpperCase()} ${z.centroid?.toFixed(2)}
                    </span>
                    <span style={{ color: t.colors.textDim }}>
                      ${(z.notional_usd / 1000).toFixed(0)}k
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </Panel>

      {/* Recent news */}
      <Panel title="Recent News">
        <div className="px-3 pb-3 space-y-2 max-h-64 overflow-y-auto">
          {!markersData || markersData.news.length === 0 ? (
            <p className="text-[11px]" style={{ color: t.colors.textMuted }}>
              No news for {market} in the selected window
            </p>
          ) : (
            markersData.news.slice(-10).reverse().map((n, i) => (
              <div
                key={i}
                className="rounded p-2 space-y-0.5"
                style={{ background: t.colors.bg, border: `1px solid ${t.colors.borderLight}` }}
              >
                <div className="flex items-start gap-2">
                  <span
                    className="flex-shrink-0 w-1.5 h-1.5 rounded-full mt-1"
                    style={{ background: severityColor(n.severity) }}
                  />
                  <span className="text-[11px] leading-snug" style={{ color: t.colors.text }}>
                    {n.headline}
                  </span>
                </div>
                <p className="text-[10px] pl-3.5" style={{ color: t.colors.textDim }}>
                  {fmtTs(n.time)} · sev {n.severity}
                </p>
              </div>
            ))
          )}
        </div>
      </Panel>

      {/* Signals panel */}
      <Panel title="Signals">
        <div className="px-3 pb-3">
          <p className="text-[11px]" style={{ color: t.colors.textMuted }}>
            Signal feed from alerts pipeline shown here when entries fire.
          </p>
          <p className="text-[10px] mt-1" style={{ color: t.colors.textDim }}>
            Stub — see /alerts for live signals
          </p>
        </div>
      </Panel>
    </div>
  );
}

// Small panel wrapper
function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-xl overflow-hidden" style={{ border: `1px solid ${t.colors.border}`, background: t.colors.surface }}>
      <div
        className="px-3 py-2.5 text-[11px] font-semibold uppercase tracking-wider"
        style={{ color: t.colors.textMuted, borderBottom: `1px solid ${t.colors.border}`, fontFamily: t.fonts.heading }}
      >
        {title}
      </div>
      {children}
    </div>
  );
}

// ─── Bottom panel tabs ────────────────────────────────────────────────────────

type BottomTab = "trades" | "lessons" | "critiques";

function BottomPanel({
  market,
  markersData,
}: {
  market: string;
  markersData: ChartMarkersResponse | null;
}) {
  const [activeTab, setActiveTab] = useState<BottomTab>("trades");

  const tabs: { value: BottomTab; label: string }[] = [
    { value: "trades", label: "Trades" },
    { value: "lessons", label: "Lessons" },
    { value: "critiques", label: "Critiques" },
  ];

  return (
    <div className="rounded-xl overflow-hidden" style={{ border: `1px solid ${t.colors.border}`, background: t.colors.surface }}>
      {/* Tab bar */}
      <div className="flex" style={{ borderBottom: `1px solid ${t.colors.border}` }}>
        {tabs.map((tab) => {
          const active = tab.value === activeTab;
          return (
            <button
              key={tab.value}
              onClick={() => setActiveTab(tab.value)}
              className="px-4 py-2.5 text-[12px] font-medium"
              style={{
                color: active ? t.colors.primary : t.colors.textMuted,
                borderBottom: active ? `2px solid ${t.colors.primary}` : "2px solid transparent",
                background: "transparent",
                cursor: "pointer",
              }}
            >
              {tab.label}
            </button>
          );
        })}
        <div className="flex-1" />
        <span className="flex items-center px-4 text-[11px]" style={{ color: t.colors.textDim }}>
          {market}
        </span>
      </div>

      {/* Tab content */}
      <div className="p-4 overflow-x-auto" style={{ maxHeight: 220 }}>
        {activeTab === "trades" && <TradesTab markersData={markersData} />}
        {activeTab === "lessons" && <LessonsTab markersData={markersData} />}
        {activeTab === "critiques" && <CritiquesTab markersData={markersData} />}
      </div>
    </div>
  );
}

// ── TradesTab helpers ────────────────────────────────────────────────────────

/** Known action type categories for colour-coded badges. */
const _ACTION_BADGE: Record<string, { bg: string; text: string; border: string }> = {
  // Entries / adds
  place_order:         { bg: "#0e2e1a", text: "#4ade80", border: "#166534" },
  market_order:        { bg: "#0e2e1a", text: "#4ade80", border: "#166534" },
  limit_order:         { bg: "#0e2e1a", text: "#4ade80", border: "#166534" },
  position_opened:     { bg: "#0e2e1a", text: "#4ade80", border: "#166534" },
  manual_entry:        { bg: "#0e2e1a", text: "#4ade80", border: "#166534" },
  buy:                 { bg: "#0e2e1a", text: "#4ade80", border: "#166534" },
  scale_in:            { bg: "#0e2e1a", text: "#86efac", border: "#166534" },
  conviction_dip_add:  { bg: "#0e2e1a", text: "#86efac", border: "#166534" },
  // Exits / trims
  position_closed:     { bg: "#2e0e0e", text: "#f87171", border: "#7f1d1d" },
  manual_exit:         { bg: "#2e0e0e", text: "#f87171", border: "#7f1d1d" },
  sell:                { bg: "#2e0e0e", text: "#f87171", border: "#7f1d1d" },
  scale_out:           { bg: "#2e0e0e", text: "#fca5a5", border: "#7f1d1d" },
  conviction_profit_take: { bg: "#2e0e0e", text: "#fca5a5", border: "#7f1d1d" },
  spike_profit:        { bg: "#2e0e0e", text: "#fca5a5", border: "#7f1d1d" },
};

function ActionBadge({ action }: { action: string }) {
  const key = action.toLowerCase();
  const style = _ACTION_BADGE[key] ?? { bg: t.colors.surface, text: t.colors.textSecondary, border: t.colors.border };
  return (
    <span
      className="px-1.5 py-0.5 rounded text-[10px] font-semibold uppercase tracking-wide whitespace-nowrap"
      style={{ background: style.bg, color: style.text, border: `1px solid ${style.border}` }}
    >
      {action.replace(/_/g, " ")}
    </span>
  );
}

/** Extract the most interesting fields from a detail object into brief human text. */
function fmtDetailCells(detail: Record<string, unknown>): { summary: string; hasExtra: boolean } {
  const parts: string[] = [];
  const d = detail as Record<string, number | string | undefined>;

  // Price fields
  if (d.price !== undefined) parts.push(`@ $${Number(d.price).toFixed(2)}`);
  if (d.stop_price !== undefined) parts.push(`SL $${Number(d.stop_price).toFixed(2)}`);
  if (d.tp_price !== undefined) parts.push(`TP $${Number(d.tp_price).toFixed(2)}`);

  // Size fields
  if (d.size_added !== undefined) parts.push(`+${d.size_added}`);
  if (d.size_closed !== undefined) parts.push(`−${d.size_closed}`);

  // Leverage change
  if (d.prev_leverage !== undefined && d.new_leverage !== undefined) {
    parts.push(`${d.prev_leverage}x→${d.new_leverage}x`);
  }

  // Conviction / spike
  if (d.conviction !== undefined) parts.push(`conv ${Number(d.conviction).toFixed(2)}`);
  if (d.spike_pct !== undefined) parts.push(`spike +${Number(d.spike_pct).toFixed(1)}%`);

  const knownKeys = new Set(["price","stop_price","tp_price","size_added","size_closed","prev_leverage","new_leverage","conviction","spike_pct","market","action","reason","oid"]);
  const extraKeys = Object.keys(detail).filter(k => !knownKeys.has(k));

  return {
    summary: parts.length > 0 ? parts.join("  ") : "—",
    hasExtra: extraKeys.length > 0,
  };
}

function TradeDetailCell({ tr }: { tr: TradeMarker }) {
  const [showRaw, setShowRaw] = useState(false);
  const { summary, hasExtra } = fmtDetailCells(tr.detail);

  return (
    <td className="py-1.5 pr-4" style={{ maxWidth: 260 }}>
      <div className="flex flex-col gap-0.5">
        {/* Primary: reasoning if present, otherwise parsed summary */}
        {tr.reasoning ? (
          <span className="truncate text-[11px]" style={{ color: t.colors.textMuted }} title={tr.reasoning}>
            {tr.reasoning}
          </span>
        ) : (
          <span className="text-[11px]" style={{ color: t.colors.text, fontFamily: t.fonts.mono }}>
            {summary}
          </span>
        )}
        {/* Secondary: parsed summary when reasoning present */}
        {tr.reasoning && summary !== "—" && (
          <span className="text-[10px]" style={{ color: t.colors.textDim, fontFamily: t.fonts.mono }}>
            {summary}
          </span>
        )}
        {/* Show raw toggle when extra fields exist */}
        {(hasExtra || Object.keys(tr.detail).length > 0) && (
          <button
            onClick={() => setShowRaw(v => !v)}
            className="text-[10px] text-left w-fit"
            style={{ color: t.colors.primary, background: "none", border: "none", cursor: "pointer", padding: 0 }}
          >
            {showRaw ? "hide raw ▲" : "show raw ▾"}
          </button>
        )}
        {showRaw && (
          <pre
            className="text-[9px] mt-0.5 p-1.5 rounded overflow-x-auto"
            style={{ background: t.colors.bg, color: t.colors.textDim, border: `1px solid ${t.colors.borderLight}`, maxWidth: 300, whiteSpace: "pre-wrap", wordBreak: "break-all" }}
          >
            {JSON.stringify(tr.detail, null, 2)}
          </pre>
        )}
      </div>
    </td>
  );
}

function TradesTab({ markersData }: { markersData: ChartMarkersResponse | null }) {
  if (!markersData || markersData.trades.length === 0) {
    return (
      <EmptyState message="No trade actions recorded for this market in the selected window." />
    );
  }
  const trades = [...markersData.trades].reverse();
  return (
    <table className="w-full text-[11px]" style={{ borderCollapse: "collapse" }}>
      <thead>
        <tr style={{ color: t.colors.textDim }}>
          <th className="text-left pb-2 pr-4 font-medium whitespace-nowrap">Time (AEST)</th>
          <th className="text-left pb-2 pr-4 font-medium">Action</th>
          <th className="text-left pb-2 pr-4 font-medium">Detail / Reason</th>
          <th className="text-left pb-2 font-medium">Outcome</th>
        </tr>
      </thead>
      <tbody>
        {trades.map((tr: TradeMarker, i) => (
          <tr key={i} style={{ borderTop: `1px solid ${t.colors.borderLight}` }}>
            <td className="py-1.5 pr-4 whitespace-nowrap" style={{ color: t.colors.textMuted, fontFamily: t.fonts.mono }}>
              {fmtTs(tr.time)}
            </td>
            <td className="py-1.5 pr-4">
              <ActionBadge action={tr.action} />
            </td>
            <TradeDetailCell tr={tr} />
            <td className="py-1.5" style={{ color: t.colors.textDim }}>
              {tr.outcome || "—"}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function LessonsTab({ markersData }: { markersData: ChartMarkersResponse | null }) {
  if (!markersData || markersData.lessons.length === 0) {
    return <EmptyState message="No post-mortems for this market in the selected window." />;
  }
  const lessons = [...markersData.lessons].reverse();
  return (
    <div className="space-y-3">
      {lessons.map((l: LessonMarker) => {
        const pnl = fmtPnl(l.pnl_usd);
        return (
          <div
            key={l.lesson_id}
            className="rounded-lg p-3"
            style={{ background: t.colors.bg, border: `1px solid ${t.colors.borderLight}` }}
          >
            <div className="flex items-center justify-between mb-1.5">
              <div className="flex items-center gap-2">
                <span
                  className="px-1.5 py-0.5 rounded text-[10px] font-semibold uppercase"
                  style={{
                    background: l.direction === "long" ? t.colors.successLight : t.colors.dangerLight,
                    color: l.direction === "long" ? t.colors.success : t.colors.danger,
                    border: `1px solid ${l.direction === "long" ? t.colors.successBorder : t.colors.dangerBorder}`,
                  }}
                >
                  {l.direction}
                </span>
                <span className="text-[11px]" style={{ color: t.colors.text }}>{l.lesson_type}</span>
              </div>
              <span className="text-[11px]" style={{ color: pnl.color, fontFamily: t.fonts.mono }}>
                {pnl.text} ({l.roe_pct >= 0 ? "+" : ""}{l.roe_pct.toFixed(2)}%)
              </span>
            </div>
            <p className="text-[11px] leading-snug" style={{ color: t.colors.textMuted }}>
              {l.summary}
            </p>
            {l.tags.length > 0 && (
              <div className="flex flex-wrap gap-1 mt-1.5">
                {l.tags.map((tag) => (
                  <span
                    key={tag}
                    className="px-1.5 py-0.5 rounded text-[9px]"
                    style={{ background: t.colors.neutralLight, color: t.colors.textDim }}
                  >
                    {tag}
                  </span>
                ))}
              </div>
            )}
            <p className="text-[10px] mt-1.5" style={{ color: t.colors.textDim }}>
              Closed {fmtTs(l.time)}
            </p>
          </div>
        );
      })}
    </div>
  );
}

function CritiquesTab({ markersData }: { markersData: ChartMarkersResponse | null }) {
  const critiques = (markersData?.critiques ?? []).filter((c) => !c.stub);
  if (critiques.length === 0) {
    return (
      <EmptyState message="No entry critiques yet for this market in the selected window. Critiques are written automatically by the daemon when a new position appears, OR run scripts/critique_position.py --coin <COIN> to grade an existing position on demand." />
    );
  }
  // Newest-first
  const sorted = [...critiques].sort((a, b) => b.time - a.time);
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-3 px-3 py-3">
      {sorted.map((c) => {
        const passes = c.pass_count ?? 0;
        const warns = c.warn_count ?? 0;
        const fails = c.fail_count ?? 0;
        const label = c.overall_label || "?";
        const labelColor =
          label.toUpperCase().includes("RISK") || label.toUpperCase().includes("BAD") || fails >= 1 ? t.colors.danger
          : label.toUpperCase().includes("MIXED") || warns >= 2 ? t.colors.warning
          : label.toUpperCase().includes("GOOD") || label.toUpperCase().includes("GREAT") || passes >= 3 ? t.colors.success
          : t.colors.textMuted;
        return (
          <div
            key={`${c.instrument}-${c.time}`}
            className="rounded-lg p-3"
            style={{ background: t.colors.surfaceHover, border: `1px solid ${t.colors.border}` }}
          >
            <div className="flex items-center justify-between mb-2">
              <span className="text-[12px] font-semibold" style={{ color: t.colors.text }}>
                {c.instrument} {(c.direction || "").toUpperCase()}
                {c.leverage ? ` · ${c.leverage}x` : ""}
              </span>
              <span
                className="text-[10px] font-semibold px-2 py-0.5 rounded"
                style={{ background: `${labelColor}22`, color: labelColor, border: `1px solid ${labelColor}66` }}
              >
                {label}
              </span>
            </div>
            <p className="text-[11px] mb-1.5" style={{ color: t.colors.textMuted }}>
              Entry ${c.entry_price?.toFixed(2) ?? "?"} · qty {c.entry_qty?.toFixed(4) ?? "?"} · {fmtTs(c.time)}
            </p>
            <p className="text-[11px] font-mono" style={{ color: t.colors.textDim }}>
              {passes} pass · {warns} warn · {fails} fail
            </p>
            {c.suggestions && c.suggestions.length > 0 && (
              <ul className="mt-2 space-y-1">
                {c.suggestions.slice(0, 3).map((s, i) => (
                  <li key={i} className="text-[11px]" style={{ color: t.colors.textMuted }}>
                    • {s}
                  </li>
                ))}
              </ul>
            )}
          </div>
        );
      })}
    </div>
  );
}

function EmptyState({ message }: { message: string }) {
  return (
    <div className="flex items-center justify-center h-20">
      <p className="text-[12px] text-center max-w-md" style={{ color: t.colors.textMuted }}>
        {message}
      </p>
    </div>
  );
}

// ─── Onboarding help sidebar ──────────────────────────────────────────────────

function HelpSidebar({ onClose }: { onClose: () => void }) {
  const sections = [
    {
      title: "Chart",
      body: "Candlestick OHLCV chart with volume histogram. Use the market selector to switch assets, and the timeframe bar to change the interval. Indicators toggle on/off from the Overlays bar.",
    },
    {
      title: "Markers",
      body: "Coloured pins on the chart indicate events: news catalysts (triangle-up/down by severity), trade actions (circles), and post-mortem lessons (diamonds). Click a candle near a marker to open its popover.",
    },
    {
      title: "Right Sidebar",
      body: "Shows the open position for the selected market, liquidation heatmap zones, recent news catalysts, and a placeholder for the manipulation-overlay toggle.",
    },
    {
      title: "Bottom Panel",
      body: "Three tabs: Trades shows action_log entries; Lessons shows closed-trade post-mortems from memory.db; Critiques will show entry-critic analysis when Phase 2 ships.",
    },
    {
      title: "Manipulation Overlay",
      body: "Toggle on the sidebar shades candle regions where sweep_detector flagged elevated stop-hunt risk. Returns mock data today — gets real data when Phase 2 sweep_detector ships.",
    },
  ];
  return (
    <div
      className="fixed top-0 right-0 h-full z-50 flex flex-col shadow-2xl overflow-y-auto"
      style={{ width: 320, background: t.colors.surface, borderLeft: `1px solid ${t.colors.border}` }}
    >
      <div
        className="flex items-center justify-between px-5 py-4"
        style={{ borderBottom: `1px solid ${t.colors.border}` }}
      >
        <span className="text-[15px] font-semibold" style={{ color: t.colors.text, fontFamily: t.fonts.heading }}>
          Charts Guide
        </span>
        <button
          onClick={onClose}
          className="text-[12px] px-3 py-1 rounded"
          style={{ color: t.colors.textMuted, background: t.colors.bg, border: `1px solid ${t.colors.border}`, cursor: "pointer" }}
        >
          Close
        </button>
      </div>
      <div className="p-5 space-y-5">
        {sections.map((s) => (
          <div key={s.title}>
            <h4
              className="text-[12px] font-semibold mb-1.5"
              style={{ color: t.colors.primary, fontFamily: t.fonts.heading }}
            >
              {s.title}
            </h4>
            <p className="text-[12px] leading-relaxed" style={{ color: t.colors.textMuted }}>
              {s.body}
            </p>
          </div>
        ))}
        <div
          className="rounded-lg p-3 text-[11px]"
          style={{ background: t.colors.primaryLight, border: `1px solid ${t.colors.primaryBorder}`, color: t.colors.primary }}
        >
          Thesis-driven markets: BTC, BRENTOIL, GOLD, SILVER.
          <br />
          CL and SP500 are tracked but not thesis-driven.
        </div>
      </div>
    </div>
  );
}

// ─── Build lightweight-charts markers from API data ───────────────────────────

function buildChartMarkers(
  markersData: ChartMarkersResponse | null,
  toggles: Record<MarkerKey, boolean>,
): SeriesMarker<Time>[] {
  if (!markersData) return [];
  const out: SeriesMarker<Time>[] = [];

  if (toggles.news) {
    for (const n of markersData.news) {
      if (n.stub) continue;
      out.push({
        time: n.time as Time,
        position: n.expected_direction === "bear" ? "aboveBar" : "belowBar",
        color: severityColor(n.severity),
        shape: n.expected_direction === "bear" ? "arrowDown" : "arrowUp",
        text: `N${n.severity}`,
        size: 1,
      });
    }
  }

  if (toggles.trades) {
    for (const tr of markersData.trades) {
      if (tr.stub) continue;
      const isExit = tr.action.includes("exit") || tr.action.includes("close");
      out.push({
        time: tr.time as Time,
        position: isExit ? "aboveBar" : "belowBar",
        color: isExit ? t.colors.warning : MARKER_COLORS.trades,
        shape: "circle",
        text: tr.action.slice(0, 3).toUpperCase(),
        size: 1,
      });
    }
  }

  if (toggles.lessons) {
    for (const l of markersData.lessons) {
      if (l.stub) continue;
      out.push({
        time: l.time as Time,
        position: "aboveBar",
        color: l.pnl_usd >= 0 ? t.colors.success : t.colors.danger,
        shape: "square",
        text: "L",
        size: 1,
      });
    }
  }

  if (toggles.critiques) {
    for (const c of markersData.critiques) {
      if (c.stub) continue;
      // Colour the critique by overall_label severity:
      //   GREAT/GOOD = green, MIXED = amber, RISKY/BAD = red, else neutral
      const label = (c.overall_label || "").toUpperCase();
      const passes = c.pass_count ?? 0;
      const warns = c.warn_count ?? 0;
      const fails = c.fail_count ?? 0;
      let color = MARKER_COLORS.critiques; // teal default
      if (label.includes("GREAT") || label.includes("GOOD") || passes >= 3) color = t.colors.success;
      else if (label.includes("RISK") || label.includes("BAD") || fails >= 1) color = t.colors.danger;
      else if (label.includes("MIXED") || warns >= 2) color = t.colors.warning;
      out.push({
        time: c.time as Time,
        position: "belowBar",
        color,
        shape: "square",
        text: `EC${passes}/${warns}/${fails}`,
        size: 1,
      });
    }
  }

  // Sort by time — required by lightweight-charts
  out.sort((a, b) => (a.time as number) - (b.time as number));
  return out;
}

// ─── Signal meta strip (Phase 4) ──────────────────────────────────────────────
// One compact line per active signal, showing the current value / state
// pulled from SignalResult.meta. Format is intentionally terse — the idea
// is to fit an OBV, RSI, and CVD reading on one row without wrapping.

function formatMetaValue(v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "number") {
    if (!Number.isFinite(v)) return "—";
    const abs = Math.abs(v);
    if (abs >= 1_000_000) return `${(v / 1_000_000).toFixed(2)}M`;
    if (abs >= 1_000) return v.toLocaleString(undefined, { maximumFractionDigits: 1 });
    if (abs >= 1) return v.toFixed(2);
    return v.toFixed(4);
  }
  if (typeof v === "boolean") return v ? "yes" : "no";
  return String(v);
}

function summarizeMeta(result: SignalResult): string {
  const parts: string[] = [];
  const meta = result.meta ?? {};
  for (const [k, v] of Object.entries(meta)) {
    if (v === null || v === undefined) continue;
    if (typeof v === "object") continue; // skip nested
    parts.push(`${k}=${formatMetaValue(v)}`);
  }
  if (result.markers && result.markers.length > 0) {
    parts.push(`${result.markers.length} markers`);
  }
  return parts.length > 0 ? parts.join(" · ") : "(no meta)";
}

function SignalMetaStrip({
  results,
  activeSlugs,
}: {
  results: Record<string, SignalResult>;
  activeSlugs: Set<string>;
}) {
  const rows = [...activeSlugs]
    .map((slug) => results[slug])
    .filter((r): r is SignalResult => !!r);

  return (
    <div
      className="mt-2 rounded-xl overflow-hidden"
      style={{ border: `1px solid ${t.colors.border}`, background: t.colors.surface }}
    >
      <div
        className="px-3 py-1.5 text-[10px] font-semibold uppercase tracking-wider"
        style={{
          color: t.colors.textMuted,
          borderBottom: `1px solid ${t.colors.border}`,
          fontFamily: t.fonts.heading,
        }}
      >
        Signal readouts ({rows.length})
      </div>
      <div className="divide-y" style={{ borderColor: t.colors.borderLight }}>
        {rows.length === 0 && (
          <div className="px-3 py-2 text-[11px]" style={{ color: t.colors.textDim }}>
            Awaiting compute…
          </div>
        )}
        {rows.map((r) => {
          const name = r.card?.name ?? r.slug;
          const color = resolveSignalColor(r.chart_spec?.color ?? "textMuted");
          return (
            <div
              key={r.slug}
              className="px-3 py-1.5 flex items-center gap-2 text-[11px]"
              style={{ borderTop: `1px solid ${t.colors.borderLight}` }}
            >
              <span
                className="w-1.5 h-1.5 rounded-full flex-shrink-0"
                style={{ background: color }}
              />
              <span
                className="flex-shrink-0"
                style={{ color: t.colors.text, minWidth: 140 }}
                title={r.slug}
              >
                {name}
              </span>
              <span
                className="truncate"
                style={{ color: t.colors.textMuted, fontFamily: t.fonts.mono }}
                title={summarizeMeta(r)}
              >
                {summarizeMeta(r)}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function ChartsPage() {
  const [market, setMarket] = useState<Market>("BTC");
  const [interval, setInterval] = useState<Interval>("1h");
  const [indicators, setIndicators] = useState<IndicatorState>(DEFAULT_INDICATORS);
  const [candles, setCandles] = useState<Candle[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [livePrice, setLivePrice] = useState<Candle | null>(null);
  const [showManipOverlay, setShowManipOverlay] = useState(false);
  const [showHelp, setShowHelp] = useState(false);
  const [popover, setPopover] = useState<PopoverData | null>(null);
  const chartHandleRef = useRef<ChartHandle | null>(null);

  // P0 fix 2026-04-17 — marker toggle state, persisted to localStorage.
  // Defaults: News on, Trades off (the "DEL" stack), Lessons off.
  // Operator can flip any chip in the toggle bar above the chart.
  const [markerToggles, setMarkerToggles] = useState<Record<MarkerKey, boolean>>(MARKER_DEFAULTS);
  useEffect(() => {
    setMarkerToggles(loadMarkerToggles());
  }, []);

  // Phase 4 — signal toggles (per-market localStorage). `signalRegistry`
  // is populated by SignalTogglePanel after the initial registry fetch so
  // the parent can look up card/spec when rehydrating active slugs on mount.
  const [activeSignalSlugs, setActiveSignalSlugs] = useState<Set<string>>(new Set());
  const [signalResults, setSignalResults] = useState<Record<string, SignalResult>>({});
  const signalRegistryRef = useRef<Map<string, SignalToggleState>>(new Map());
  const handleSignalRegistryLoaded = useCallback((reg: Map<string, SignalToggleState>) => {
    signalRegistryRef.current = reg;
  }, []);
  const toggleMarker = useCallback((key: MarkerKey) => {
    setMarkerToggles((prev) => {
      const next = { ...prev, [key]: !prev[key] };
      try { localStorage.setItem(MARKER_LS_KEY, JSON.stringify(next)); } catch { /* private mode */ }
      return next;
    });
  }, []);

  // Position fetch — drives SL/TP/Liq/Entry horizontal price lines.
  const { data: accountStatus } = usePolling(
    useCallback(() => getAccountStatus(), []),
    30_000,
  );
  const positionsForMarket = (accountStatus?.positions ?? []).filter((p) => {
    const stripped = p.coin.replace("xyz:", "").toUpperCase();
    return stripped === market.toUpperCase();
  });

  // ── Markers + overlay polling ─────────────────────────────────────────────
  const { data: markersData } = usePolling(
    useCallback(() => getChartMarkers(market, 72), [market]),
    60_000
  );
  const { data: overlayData } = usePolling(
    useCallback(() => getChartOverlay(market, 24), [market]),
    120_000
  );

  // ── Chart markers (computed from API data, filtered by toggle state) ──────
  const chartMarkers = buildChartMarkers(markersData, markerToggles);

  // Push markers to chart whenever they change OR toggle state changes
  useEffect(() => {
    chartHandleRef.current?.setMarkers(chartMarkers);
  }, [chartMarkers]);

  // Push position price lines (SL/TP/Liq/Entry) whenever positions change.
  // P0 2026-04-17 — replaces marker stack on the right edge with persistent
  // horizontal lines per the spec.
  useEffect(() => {
    chartHandleRef.current?.drawPositionLines(positionsForMarket);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [accountStatus, market]);

  // ── Candle loading ────────────────────────────────────────────────────────
  const fetchCandles = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`/api/charts/candles/${market}?interval=${interval}&limit=500`);
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail ?? `HTTP ${res.status}`);
      }
      const data: CandleResponse = await res.json();
      setCandles(data.candles);
      setLastUpdated(new Date());
      if (data.candles.length > 0) setLivePrice(data.candles[data.candles.length - 1]);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [market, interval]);

  useEffect(() => { fetchCandles(); }, [fetchCandles]);
  useEffect(() => {
    const id = window.setInterval(fetchCandles, 60_000);
    return () => window.clearInterval(id);
  }, [fetchCandles]);

  // ── Live tick poll (3s) ───────────────────────────────────────────────────
  useEffect(() => {
    const id = window.setInterval(async () => {
      try {
        const res = await fetch(`/api/charts/candles/${market}/tick?interval=${interval}`);
        if (!res.ok) return;
        const data: CandleResponse = await res.json();
        if (data.candles.length > 0) {
          chartHandleRef.current?.updateTick(data.candles);
          setLivePrice(data.candles[data.candles.length - 1]);
          setLastUpdated(new Date());
        }
      } catch {
        // silent
      }
    }, 3_000);
    return () => window.clearInterval(id);
  }, [market, interval]);

  // ── Phase 4 — signal management ───────────────────────────────────────────
  // Hydrate active slugs from localStorage whenever the market changes.
  // The registry load is the other gate — but the panel owns that fetch,
  // so we tolerate it being empty on first render (re-fetch hook below).
  useEffect(() => {
    const loaded = loadActiveSlugs(market);
    setActiveSignalSlugs(loaded);
    // Clear old series on market change. The effect below will then
    // re-fetch compute() for the hydrated active set.
    chartHandleRef.current?.clearSignals();
    setSignalResults({});
  }, [market]);

  // Toggle handler — persist and let the compute effect pick up the change.
  const handleSignalToggle = useCallback(
    (slug: string, enabled: boolean) => {
      setActiveSignalSlugs((prev) => {
        const next = new Set(prev);
        if (enabled) next.add(slug);
        else next.delete(slug);
        saveActiveSlugs(market, next);
        return next;
      });
      if (!enabled) {
        chartHandleRef.current?.removeSignal(slug);
        setSignalResults((prev) => {
          if (!(slug in prev)) return prev;
          const { [slug]: _drop, ...rest } = prev;
          void _drop;
          return rest;
        });
      }
    },
    [market],
  );

  // Fetch + re-fetch compute() for the full active set whenever:
  //   • the active slug set changes
  //   • the coin or interval changes (via candle refetch tick below)
  // We also re-fetch on every 3s tick so sub-pane oscillators move with price.
  const fetchActiveSignals = useCallback(async () => {
    if (activeSignalSlugs.size === 0) return;
    const slugs = [...activeSignalSlugs];
    const results = await Promise.allSettled(
      slugs.map((slug) => computeChartSignal(slug, market, interval, 500)),
    );
    const patch: Record<string, SignalResult> = {};
    for (let i = 0; i < slugs.length; i++) {
      const r = results[i];
      if (r.status === "fulfilled") {
        patch[slugs[i]] = r.value;
        chartHandleRef.current?.upsertSignal(r.value);
      }
    }
    if (Object.keys(patch).length > 0) {
      setSignalResults((prev) => ({ ...prev, ...patch }));
    }
  }, [activeSignalSlugs, market, interval]);

  // Fire on active-set / coin / interval change.
  useEffect(() => {
    fetchActiveSignals();
  }, [fetchActiveSignals]);

  // Fire on 3s tick — piggyback on the existing tick cadence instead of
  // wiring a second timer. Keeps code footprint small; fetchActiveSignals
  // is a no-op when the set is empty.
  useEffect(() => {
    if (activeSignalSlugs.size === 0) return;
    const id = window.setInterval(() => {
      fetchActiveSignals();
    }, 3_000);
    return () => window.clearInterval(id);
  }, [fetchActiveSignals, activeSignalSlugs.size]);

  const toggleIndicator = (key: keyof IndicatorState) =>
    setIndicators((prev) => ({ ...prev, [key]: !prev[key] }));

  // Click on chart — find nearest marker and show popover
  const handleMarkerClick = useCallback(
    (clickTime: number) => {
      if (!markersData) return;
      // Find the closest marker within 3 candle-widths
      const WINDOW = 3 * 3600; // 3 hours in seconds, rough
      const allMarkers = [
        ...markersData.news.filter((n) => !n.stub),
        ...markersData.trades.filter((tr) => !tr.stub),
        ...markersData.lessons.filter((l) => !l.stub),
      ];
      const nearest = allMarkers
        .filter((m) => Math.abs(m.time - clickTime) <= WINDOW)
        .sort((a, b) => Math.abs(a.time - clickTime) - Math.abs(b.time - clickTime))[0];

      if (!nearest) {
        setPopover(null);
        return;
      }

      if (nearest.type === "news") {
        const n = nearest as NewsMarker;
        setPopover({
          title: `News · Sev ${n.severity}`,
          lines: [
            { label: "Headline", value: n.headline },
            { label: "Category", value: n.category },
            { label: "Source", value: n.source },
            { label: "Direction", value: n.expected_direction ?? "—" },
            { label: "Rationale", value: n.rationale },
            { label: "Time (AEST)", value: fmtTs(n.time) },
          ],
        });
      } else if (nearest.type === "trade") {
        const tr = nearest as TradeMarker;
        setPopover({
          title: `Trade · ${tr.action}`,
          lines: [
            { label: "Action", value: tr.action },
            { label: "Reasoning", value: tr.reasoning || "—" },
            { label: "Outcome", value: tr.outcome || "—" },
            { label: "Time (AEST)", value: fmtTs(tr.time) },
          ],
        });
      } else if (nearest.type === "lesson") {
        const l = nearest as LessonMarker;
        const pnl = fmtPnl(l.pnl_usd);
        setPopover({
          title: `Lesson · ${l.lesson_type}`,
          lines: [
            { label: "Direction", value: l.direction },
            { label: "Outcome", value: l.outcome },
            { label: "PnL", value: pnl.text, color: pnl.color },
            { label: "ROE", value: `${l.roe_pct >= 0 ? "+" : ""}${l.roe_pct.toFixed(2)}%`, color: pnl.color },
            { label: "Summary", value: l.summary.slice(0, 120) + (l.summary.length > 120 ? "…" : "") },
            { label: "Tags", value: l.tags.join(", ") || "—" },
            { label: "Closed", value: fmtTs(l.time) },
          ],
        });
      }
    },
    [markersData]
  );

  const marketOptions = MARKETS.map((m) => ({ value: m, label: m }));
  const intervalOptions = INTERVALS.map((i) => ({ value: i.value, label: i.label }));

  return (
    <div className="p-6 space-y-4 max-w-[1600px]">
      {/* Help sidebar overlay */}
      {showHelp && <HelpSidebar onClose={() => setShowHelp(false)} />}

      {/* ── Header ────────────────────────────────────────────────────────── */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h2
            className="text-2xl font-semibold"
            style={{ color: t.colors.text, fontFamily: t.fonts.heading }}
          >
            Charts
          </h2>
          <p className="text-[13px] mt-0.5" style={{ color: t.colors.textMuted }}>
            OHLCV with news, trade, and lesson markers
          </p>
        </div>

        <div className="flex items-center gap-2 flex-wrap">
          <SegmentedControl options={marketOptions} value={market} onChange={(v) => setMarket(v as Market)} />
          <SegmentedControl options={intervalOptions} value={interval} onChange={(v) => setInterval(v as Interval)} />
          <button
            onClick={fetchCandles}
            disabled={loading}
            className="px-3 py-1.5 rounded-lg text-[12px] font-medium"
            style={{
              background: t.colors.primaryLight,
              color: t.colors.primary,
              border: `1px solid ${t.colors.primaryBorder}`,
              cursor: loading ? "wait" : "pointer",
              opacity: loading ? 0.7 : 1,
            }}
          >
            {loading ? "Loading…" : "Refresh"}
          </button>
          <button
            onClick={() => setShowHelp((v) => !v)}
            className="w-7 h-7 rounded-full flex items-center justify-center text-[12px] font-semibold"
            title="Chart guide"
            style={{
              background: t.colors.neutralLight,
              color: t.colors.textMuted,
              border: `1px solid ${t.colors.border}`,
              cursor: "pointer",
            }}
          >
            ?
          </button>
        </div>
      </div>

      {/* ── Main layout: signal panel + chart + right sidebar ────────────── */}
      <div className="flex gap-4 items-start">
        {/* Left: signal toggle panel (Phase 4) */}
        <SignalTogglePanel
          coin={market}
          activeSlugs={activeSignalSlugs}
          onToggle={handleSignalToggle}
          onRegistryLoaded={handleSignalRegistryLoaded}
        />

        {/* Chart column */}
        <div className="flex-1 min-w-0 space-y-0">
          {/* Chart card */}
          <div
            className="rounded-xl overflow-hidden"
            style={{ border: `1px solid ${t.colors.border}`, background: t.colors.surface }}
          >
            {/* Card header */}
            <div
              className="flex items-center justify-between px-4 py-2.5 flex-wrap gap-3"
              style={{ borderBottom: `1px solid ${t.colors.border}` }}
            >
              <div className="flex items-center gap-3">
                <span
                  className="text-[15px] font-semibold"
                  style={{ color: t.colors.text, fontFamily: t.fonts.heading }}
                >
                  {market}
                </span>
                <span
                  className="text-[11px] px-2 py-0.5 rounded"
                  style={{
                    background: t.colors.primaryLight,
                    color: t.colors.primary,
                    border: `1px solid ${t.colors.primaryBorder}`,
                  }}
                >
                  {interval}
                </span>
                {candles.length > 0 && (
                  <span className="text-[11px]" style={{ color: t.colors.textMuted }}>
                    {candles.length} candles
                  </span>
                )}
                {markersData && (
                  <span className="text-[11px]" style={{ color: t.colors.textDim }}>
                    {markersData.news.length} news · {markersData.trades.length} actions · {markersData.lessons.length} lessons
                  </span>
                )}
              </div>

              {/* Indicator toggles */}
              <div className="flex items-center gap-1.5 flex-wrap">
                <span
                  className="text-[10px] font-medium uppercase tracking-wider mr-1"
                  style={{ color: t.colors.textDim }}
                >
                  Overlays
                </span>
                {(Object.keys(indicators) as (keyof IndicatorState)[]).map((key) => {
                  const colorMap: Record<keyof IndicatorState, string> = {
                    bb: IND_COLORS.bbUpper,
                    sma50: IND_COLORS.sma50,
                    sma200: IND_COLORS.sma200,
                    ema12: IND_COLORS.ema12,
                    ema26: IND_COLORS.ema26,
                  };
                  return (
                    <IndicatorToggle
                      key={key}
                      label={INDICATOR_LABELS[key]}
                      active={indicators[key]}
                      color={colorMap[key]}
                      onToggle={() => toggleIndicator(key)}
                    />
                  );
                })}
              </div>
            </div>

            {/* Marker toggle bar — P0 2026-04-17.  Lets the operator hide
                the trade-action stack ("DEL" markers) and other clutter.
                Persists to localStorage. SL/TP/Liq/Entry are NOT here —
                those are horizontal price lines, always shown for any
                position on the selected market. */}
            <div
              className="flex items-center gap-1.5 flex-wrap px-4 py-2"
              style={{ borderBottom: `1px solid ${t.colors.border}`, background: t.colors.bg }}
            >
              <span
                className="text-[10px] font-medium uppercase tracking-wider mr-1"
                style={{ color: t.colors.textDim }}
              >
                Markers
              </span>
              {(Object.keys(MARKER_DEFAULTS) as MarkerKey[]).map((key) => {
                const counts: Record<MarkerKey, number> = {
                  news: markersData?.news.length ?? 0,
                  trades: markersData?.trades.length ?? 0,
                  lessons: markersData?.lessons.length ?? 0,
                  critiques: (markersData?.critiques ?? []).filter((c) => !c.stub).length,
                };
                return (
                  <MarkerToggle
                    key={key}
                    label={MARKER_LABELS[key]}
                    color={MARKER_COLORS[key]}
                    active={markerToggles[key]}
                    onToggle={() => toggleMarker(key)}
                    count={counts[key]}
                  />
                );
              })}
              {positionsForMarket.length > 0 && (
                <span
                  className="ml-2 text-[10px] px-2 py-0.5 rounded"
                  style={{
                    color: t.colors.textMuted,
                    background: t.colors.surfaceHover,
                    border: `1px solid ${t.colors.border}`,
                  }}
                >
                  Lines: Entry + Liq for {positionsForMarket.length} open position{positionsForMarket.length === 1 ? "" : "s"}
                </span>
              )}
            </div>

            {/* Chart area */}
            <div className="relative">
              {error && (
                <div
                  className="absolute inset-0 flex flex-col items-center justify-center z-10 rounded-b-xl"
                  style={{ background: t.colors.surface }}
                >
                  <div
                    className="text-[13px] px-4 py-3 rounded-lg"
                    style={{
                      background: t.colors.dangerLight,
                      color: t.colors.danger,
                      border: `1px solid ${t.colors.dangerBorder}`,
                    }}
                  >
                    {error}
                  </div>
                  <p className="text-[11px] mt-2" style={{ color: t.colors.textMuted }}>
                    Candle data may not be available for {market} {interval} yet.
                  </p>
                </div>
              )}
              {!error && candles.length === 0 && !loading && (
                <div
                  className="absolute inset-0 flex flex-col items-center justify-center z-10"
                  style={{ background: t.colors.surface, height: 440 }}
                >
                  <div className="text-[13px]" style={{ color: t.colors.textMuted }}>
                    No candle data for {market} {interval}
                  </div>
                  <p className="text-[11px] mt-1" style={{ color: t.colors.textDim }}>
                    The candle cache may not have populated this market yet.
                  </p>
                </div>
              )}

              <CandleChart
                candles={candles}
                indicators={indicators}
                markers={chartMarkers}
                handleRef={chartHandleRef}
                onMarkerClick={handleMarkerClick}
              />

              {/* Popover */}
              {popover && (
                <Popover data={popover} onClose={() => setPopover(null)} />
              )}
            </div>

            {/* Footer */}
            {lastUpdated && (
              <div
                className="px-4 py-2 flex items-center justify-between"
                style={{ borderTop: `1px solid ${t.colors.border}` }}
              >
                <div className="flex items-center gap-4 text-[11px]" style={{ color: t.colors.textDim }}>
                  {livePrice && (() => {
                    const prev = candles.length > 1 ? candles[candles.length - 2] : null;
                    const change = prev ? ((livePrice.close - prev.close) / prev.close) * 100 : null;
                    return (
                      <>
                        <span>
                          Last:{" "}
                          <span style={{ color: t.colors.text, fontFamily: t.fonts.mono }}>
                            {livePrice.close.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 4 })}
                          </span>
                        </span>
                        {change !== null && (
                          <span style={{ color: change >= 0 ? t.colors.success : t.colors.danger, fontFamily: t.fonts.mono }}>
                            {change >= 0 ? "+" : ""}{change.toFixed(2)}%
                          </span>
                        )}
                      </>
                    );
                  })()}
                </div>
                <span className="text-[11px]" style={{ color: t.colors.textDim }}>
                  Updated {lastUpdated.toLocaleTimeString()}
                </span>
              </div>
            )}
          </div>

          {/* Phase 4 — Signal meta strip (one line per active signal) */}
          {activeSignalSlugs.size > 0 && (
            <SignalMetaStrip results={signalResults} activeSlugs={activeSignalSlugs} />
          )}
        </div>

        {/* Right sidebar */}
        <RightSidebar
          market={market}
          markersData={markersData ?? null}
          overlayData={overlayData ?? null}
          showManipOverlay={showManipOverlay}
          onToggleManip={() => setShowManipOverlay((v) => !v)}
        />
      </div>

      {/* ── Bottom panel ──────────────────────────────────────────────────── */}
      <BottomPanel market={market} markersData={markersData ?? null} />
    </div>
  );
}
