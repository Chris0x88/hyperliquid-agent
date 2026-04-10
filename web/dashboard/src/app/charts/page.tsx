"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import {
  createChart,
  CandlestickSeries,
  LineSeries,
  HistogramSeries,
  type IChartApi,
  type ISeriesApi,
  type CandlestickData,
  type LineData,
  type HistogramData,
  type Time,
} from "lightweight-charts";
import { theme as t } from "@/lib/theme";
import { sma, ema, bollingerBands } from "@/lib/indicators";

// ─── Types ───────────────────────────────────────────────────────────────────

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

// ─── Constants ───────────────────────────────────────────────────────────────

const MARKETS = ["BTC", "BRENTOIL", "GOLD", "SILVER", "CL", "SP500"] as const;
type Market = (typeof MARKETS)[number];

const INTERVALS = [
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

// Indicator colors
const IND_COLORS = {
  bbUpper: t.colors.tertiary,        // #87CAE6
  bbMiddle: "rgba(135,202,230,0.55)",
  bbLower: t.colors.tertiary,
  sma50: t.colors.primary,           // #A26B32
  sma200: t.colors.secondary,        // #8F7156
  ema12: "#c084fc",                  // purple-400
  ema26: "#f472b6",                  // pink-400
};

// ─── Helper: build lightweight-charts series data ─────────────────────────────

function toLineData(
  candles: Candle[],
  values: (number | null)[]
): LineData[] {
  const out: LineData[] = [];
  for (let i = 0; i < candles.length; i++) {
    if (values[i] !== null) {
      out.push({ time: candles[i].time as Time, value: values[i] as number });
    }
  }
  return out;
}

// ─── Tiny UI components ───────────────────────────────────────────────────────

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
      className="flex items-center gap-1.5 px-2.5 py-1 rounded text-[11px] font-medium transition-all duration-100"
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

// ─── Main Chart Component ─────────────────────────────────────────────────────

function CandleChart({
  candles,
  indicators,
}: {
  candles: Candle[];
  indicators: IndicatorState;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);

  // Series refs
  const candleSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volumeSeriesRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  const bbUpperRef = useRef<ISeriesApi<"Line"> | null>(null);
  const bbMiddleRef = useRef<ISeriesApi<"Line"> | null>(null);
  const bbLowerRef = useRef<ISeriesApi<"Line"> | null>(null);
  const sma50Ref = useRef<ISeriesApi<"Line"> | null>(null);
  const sma200Ref = useRef<ISeriesApi<"Line"> | null>(null);
  const ema12Ref = useRef<ISeriesApi<"Line"> | null>(null);
  const ema26Ref = useRef<ISeriesApi<"Line"> | null>(null);

  // ── Create chart on mount ─────────────────────────────────────────────────
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
      rightPriceScale: {
        borderColor: t.colors.border,
      },
      width: containerRef.current.clientWidth,
      height: 480,
    });

    chartRef.current = chart;

    // ── Candlestick series ──────────────────────────────────────────────────
    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: t.colors.success,
      downColor: t.colors.danger,
      borderUpColor: t.colors.success,
      borderDownColor: t.colors.danger,
      wickUpColor: t.colors.success,
      wickDownColor: t.colors.danger,
    });
    candleSeriesRef.current = candleSeries;

    // ── Volume histogram on separate price scale ────────────────────────────
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

    // ── Bollinger Bands ─────────────────────────────────────────────────────
    const bbLineOpts = {
      color: IND_COLORS.bbUpper,
      lineWidth: 1 as const,
      lineStyle: 2 as const, // dashed
      lastValueVisible: false,
      priceLineVisible: false,
    };
    bbUpperRef.current = chart.addSeries(LineSeries, bbLineOpts);
    bbLowerRef.current = chart.addSeries(LineSeries, bbLineOpts);
    bbMiddleRef.current = chart.addSeries(LineSeries, {
      color: IND_COLORS.bbMiddle,
      lineWidth: 1 as const,
      lineStyle: 2 as const,
      lastValueVisible: false,
      priceLineVisible: false,
    });

    // ── SMA / EMA lines ─────────────────────────────────────────────────────
    sma50Ref.current = chart.addSeries(LineSeries, {
      color: IND_COLORS.sma50,
      lineWidth: 1 as const,
      lastValueVisible: true,
      priceLineVisible: false,
    });
    sma200Ref.current = chart.addSeries(LineSeries, {
      color: IND_COLORS.sma200,
      lineWidth: 1 as const,
      lastValueVisible: true,
      priceLineVisible: false,
    });
    ema12Ref.current = chart.addSeries(LineSeries, {
      color: IND_COLORS.ema12,
      lineWidth: 1 as const,
      lastValueVisible: true,
      priceLineVisible: false,
    });
    ema26Ref.current = chart.addSeries(LineSeries, {
      color: IND_COLORS.ema26,
      lineWidth: 1 as const,
      lastValueVisible: true,
      priceLineVisible: false,
    });

    // ── Resize observer ─────────────────────────────────────────────────────
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
    };
  }, []);

  // ── Update data when candles change ────────────────────────────────────────
  useEffect(() => {
    if (!candles.length) return;

    const closes = candles.map((c) => c.close);

    // Candlestick data
    const candleData: CandlestickData[] = candles.map((c) => ({
      time: c.time as Time,
      open: c.open,
      high: c.high,
      low: c.low,
      close: c.close,
    }));
    candleSeriesRef.current?.setData(candleData);

    // Volume data — color by bar direction
    const volumeData: HistogramData[] = candles.map((c) => ({
      time: c.time as Time,
      value: c.volume,
      color:
        c.close >= c.open
          ? "rgba(34, 197, 94, 0.35)"
          : "rgba(239, 68, 68, 0.35)",
    }));
    volumeSeriesRef.current?.setData(volumeData);

    // ── Indicators ──────────────────────────────────────────────────────────
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

  // ── Show/hide indicator series based on toggle state ──────────────────────
  useEffect(() => {
    const applyVisibility = (
      ref: React.MutableRefObject<ISeriesApi<"Line"> | null>,
      visible: boolean
    ) => {
      if (ref.current) {
        ref.current.applyOptions({ visible });
      }
    };

    applyVisibility(bbUpperRef, indicators.bb);
    applyVisibility(bbMiddleRef, indicators.bb);
    applyVisibility(bbLowerRef, indicators.bb);
    applyVisibility(sma50Ref, indicators.sma50);
    applyVisibility(sma200Ref, indicators.sma200);
    applyVisibility(ema12Ref, indicators.ema12);
    applyVisibility(ema26Ref, indicators.ema26);
  }, [indicators]);

  return (
    <div
      ref={containerRef}
      className="w-full rounded-lg overflow-hidden"
      style={{ height: 480, background: t.colors.surface }}
    />
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

  const fetchCandles = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(
        `/api/charts/candles/${market}?interval=${interval}&limit=500`
      );
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail ?? `HTTP ${res.status}`);
      }
      const data: CandleResponse = await res.json();
      setCandles(data.candles);
      setLastUpdated(new Date());
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [market, interval]);

  // Fetch on mount + whenever market/interval changes
  useEffect(() => {
    fetchCandles();
  }, [fetchCandles]);

  // Auto-refresh every 60s
  useEffect(() => {
    const id = window.setInterval(() => { fetchCandles(); }, 60_000);
    return () => window.clearInterval(id);
  }, [fetchCandles]);

  const toggleIndicator = (key: keyof IndicatorState) => {
    setIndicators((prev) => ({ ...prev, [key]: !prev[key] }));
  };

  const marketOptions = MARKETS.map((m) => ({ value: m, label: m }));
  const intervalOptions = INTERVALS.map((i) => ({ value: i.value, label: i.label }));

  return (
    <div className="p-8 space-y-6 max-w-[1400px]">
      {/* ── Header ────────────────────────────────────────────────────────── */}
      <div className="flex items-center justify-between flex-wrap gap-4">
        <div>
          <h2
            className="text-2xl font-semibold"
            style={{ color: t.colors.text, fontFamily: t.fonts.heading }}
          >
            Charts
          </h2>
          <p className="text-[13px] mt-1" style={{ color: t.colors.textMuted }}>
            OHLCV candlestick charts with technical overlays
          </p>
        </div>

        <div className="flex items-center gap-2 flex-wrap">
          {/* Market selector */}
          <SegmentedControl
            options={marketOptions}
            value={market}
            onChange={(v) => setMarket(v as Market)}
          />

          {/* Interval selector */}
          <SegmentedControl
            options={intervalOptions}
            value={interval}
            onChange={(v) => setInterval(v as Interval)}
          />

          {/* Refresh button */}
          <button
            onClick={fetchCandles}
            disabled={loading}
            className="px-3 py-1.5 rounded-lg text-[12px] font-medium transition-all"
            style={{
              background: loading ? t.colors.primaryLight : t.colors.primaryLight,
              color: t.colors.primary,
              border: `1px solid ${t.colors.primaryBorder}`,
              cursor: loading ? "wait" : "pointer",
              opacity: loading ? 0.7 : 1,
            }}
          >
            {loading ? "Loading…" : "Refresh"}
          </button>
        </div>
      </div>

      {/* ── Chart card ────────────────────────────────────────────────────── */}
      <div
        className="rounded-xl overflow-hidden"
        style={{
          border: `1px solid ${t.colors.border}`,
          background: t.colors.surface,
        }}
      >
        {/* Card header: market name + indicator toggles */}
        <div
          className="flex items-center justify-between px-5 py-3 flex-wrap gap-3"
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
                Candle data may not be available for this market/interval yet.
              </p>
            </div>
          )}

          {!error && candles.length === 0 && !loading && (
            <div
              className="absolute inset-0 flex flex-col items-center justify-center z-10"
              style={{ background: t.colors.surface, height: 480 }}
            >
              <div className="text-[13px]" style={{ color: t.colors.textMuted }}>
                No candle data for {market} {interval}
              </div>
              <p className="text-[11px] mt-1" style={{ color: t.colors.textDim }}>
                The candle cache may not have populated this market yet.
              </p>
            </div>
          )}

          <CandleChart candles={candles} indicators={indicators} />
        </div>

        {/* Card footer */}
        {lastUpdated && (
          <div
            className="px-5 py-2 flex items-center justify-between"
            style={{ borderTop: `1px solid ${t.colors.border}` }}
          >
            <div className="flex items-center gap-4 text-[11px]" style={{ color: t.colors.textDim }}>
              {/* Last price stat */}
              {candles.length > 0 && (() => {
                const last = candles[candles.length - 1];
                const prev = candles.length > 1 ? candles[candles.length - 2] : null;
                const change = prev ? ((last.close - prev.close) / prev.close) * 100 : null;
                return (
                  <>
                    <span>
                      Last:{" "}
                      <span style={{ color: t.colors.text, fontFamily: t.fonts.mono }}>
                        {last.close.toLocaleString(undefined, {
                          minimumFractionDigits: 2,
                          maximumFractionDigits: 4,
                        })}
                      </span>
                    </span>
                    {change !== null && (
                      <span
                        style={{
                          color: change >= 0 ? t.colors.success : t.colors.danger,
                          fontFamily: t.fonts.mono,
                        }}
                      >
                        {change >= 0 ? "+" : ""}
                        {change.toFixed(2)}%
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

      {/* ── Indicator legend ──────────────────────────────────────────────── */}
      <div
        className="rounded-xl px-5 py-4"
        style={{
          border: `1px solid ${t.colors.border}`,
          background: t.colors.surface,
        }}
      >
        <h3
          className="text-[11px] font-medium uppercase tracking-wider mb-3"
          style={{ color: t.colors.textMuted, fontFamily: t.fonts.heading }}
        >
          Indicator Reference
        </h3>
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-3">
          {[
            {
              key: "bb" as const,
              color: IND_COLORS.bbUpper,
              desc: "Bollinger Bands · 20-period SMA ± 2σ — measures volatility envelope",
            },
            {
              key: "sma50" as const,
              color: IND_COLORS.sma50,
              desc: "SMA 50 · 50-bar simple moving average — medium-term trend",
            },
            {
              key: "sma200" as const,
              color: IND_COLORS.sma200,
              desc: "SMA 200 · 200-bar simple moving average — long-term trend",
            },
            {
              key: "ema12" as const,
              color: IND_COLORS.ema12,
              desc: "EMA 12 · Fast exponential moving average — short-term momentum",
            },
            {
              key: "ema26" as const,
              color: IND_COLORS.ema26,
              desc: "EMA 26 · Slow exponential moving average — MACD baseline",
            },
          ].map(({ key, color, desc }) => (
            <div key={key} className="flex gap-2">
              <div
                className="w-0.5 flex-shrink-0 rounded-full mt-0.5"
                style={{ background: color, minHeight: 16 }}
              />
              <div>
                <span
                  className="text-[11px] font-medium block"
                  style={{ color: indicators[key] ? t.colors.text : t.colors.textDim }}
                >
                  {INDICATOR_LABELS[key]}
                </span>
                <span className="text-[10px]" style={{ color: t.colors.textDim }}>
                  {desc.split(" · ")[1]}
                </span>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
