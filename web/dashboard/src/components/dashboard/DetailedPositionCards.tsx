"use client";

import { useState } from "react";
import { usePolling } from "@/lib/hooks";
import { getPositionsDetailed, type DetailedPosition } from "@/lib/api";
import { theme as t } from "@/lib/theme";

// ─── Helpers ─────────────────────────────────────────────────────────────────

function fmt(v: number | null | undefined, digits = 2, prefix = "$"): string {
  if (v === null || v === undefined) return "—";
  return `${prefix}${Math.abs(v).toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })}`;
}

function fmtPct(v: number | null | undefined, digits = 1): string {
  if (v === null || v === undefined) return "—";
  const sign = v >= 0 ? "+" : "";
  return `${sign}${v.toFixed(digits)}%`;
}

function fmtDuration(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return "—";
  const totalSec = Math.floor(ms / 1000);
  const h = Math.floor(totalSec / 3600);
  const m = Math.floor((totalSec % 3600) / 60);
  if (h > 24) {
    const d = Math.floor(h / 24);
    return `${d}d ${h % 24}h`;
  }
  return `${h}h ${m.toString().padStart(2, "0")}m`;
}

// ─── Sweep risk badge ─────────────────────────────────────────────────────────

function SweepBadge({ risk }: { risk: { score: number; label: string } | null }) {
  if (!risk) {
    return (
      <span className="text-[10px] px-1.5 py-0.5 rounded" style={{ background: t.colors.borderLight, color: t.colors.textDim }}>
        sweep —
      </span>
    );
  }
  const isHigh = risk.score >= 0.6;
  const isMed = risk.score >= 0.3;
  const bg = isHigh ? t.colors.dangerLight : isMed ? t.colors.warningLight : t.colors.successLight;
  const color = isHigh ? t.colors.danger : isMed ? t.colors.warning : t.colors.success;
  const border = isHigh ? t.colors.dangerBorder : isMed ? t.colors.warningBorder : t.colors.successBorder;
  return (
    <span
      className="text-[10px] px-1.5 py-0.5 rounded font-medium"
      style={{ background: bg, color, border: `1px solid ${border}` }}
      title={`Sweep risk: ${(risk.score * 100).toFixed(0)}% — ${risk.label}`}
    >
      sweep {(risk.score * 100).toFixed(0)}%
    </span>
  );
}

// ─── Single position card ─────────────────────────────────────────────────────

function DetailedPositionCard({ pos }: { pos: DetailedPosition }) {
  const [expanded, setExpanded] = useState(false);

  const size = parseFloat(pos.szi);
  const entry = parseFloat(pos.entryPx);
  const upnl = parseFloat(pos.unrealizedPnl);
  const roe = parseFloat(pos.returnOnEquity) * 100;
  const margin = parseFloat(pos.marginUsed);
  const notional = parseFloat(pos.positionValue);
  const side = size > 0 ? "LONG" : "SHORT";
  const sideColor = side === "LONG" ? t.colors.success : t.colors.danger;
  const pnlColor = upnl >= 0 ? t.colors.success : t.colors.danger;

  // Price arrow: current vs entry
  const current = pos.currentPx;
  const priceUp = current !== null && current > entry;
  const priceDelta = current !== null ? current - entry : null;
  const priceArrow = priceDelta === null ? "" : priceDelta >= 0 ? "↑" : "↓";
  const priceArrowColor = priceUp ? t.colors.success : t.colors.danger;

  // Coin display: strip xyz: prefix for readability, keep badge
  const coinDisplay = pos.coin.replace("xyz:", "");
  const isXyz = pos.coin.startsWith("xyz:");

  return (
    <div
      className="rounded-lg transition-all duration-150"
      style={{
        background: t.colors.surface,
        border: `1px solid ${expanded ? t.colors.primary : t.colors.border}`,
      }}
    >
      {/* ── Header ── */}
      <button
        className="w-full text-left"
        onClick={() => setExpanded((v) => !v)}
      >
        <div className="flex items-start justify-between p-3.5 pb-2">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-[15px] font-bold" style={{ color: t.colors.text, fontFamily: t.fonts.heading }}>
              {coinDisplay}
            </span>
            {isXyz && (
              <span className="text-[9px] px-1 py-0.5 rounded" style={{ background: t.colors.tertiaryLight, color: t.colors.tertiary, border: `1px solid ${t.colors.tertiaryBorder}` }}>
                xyz
              </span>
            )}
            <span
              className="px-2 py-0.5 rounded text-[10px] font-bold uppercase"
              style={{ background: `${sideColor}18`, color: sideColor, border: `1px solid ${sideColor}35` }}
            >
              {side}
            </span>
            <span className="text-[11px] font-medium" style={{ color: t.colors.textMuted }}>{pos.leverage.value}x</span>
            <SweepBadge risk={pos.sweep_risk} />
          </div>
          <div className="text-right">
            <div
              className="text-[15px] font-semibold"
              style={{ color: pnlColor, fontFamily: t.fonts.mono }}
            >
              {upnl >= 0 ? "+" : ""}{fmt(upnl)} <span className="text-[12px]">({fmtPct(roe)})</span>
            </div>
            <div className="text-[10px] mt-0.5" style={{ color: t.colors.textMuted }}>
              {pos.wallet} &nbsp;·&nbsp; held {fmtDuration(pos.time_held_ms)}
            </div>
          </div>
        </div>

        {/* ── Price row ── */}
        <div className="px-3.5 pb-3 flex items-center gap-3 text-[12px]">
          <span style={{ color: t.colors.textMuted }}>Entry</span>
          <span style={{ color: t.colors.text, fontFamily: t.fonts.mono }}>{fmt(entry, 4, "$")}</span>
          {current !== null && (
            <>
              <span style={{ color: t.colors.textDim }}>→</span>
              <span style={{ color: priceArrowColor, fontFamily: t.fonts.mono }}>
                {priceArrow} {fmt(current, 4, "$")}
              </span>
              {priceDelta !== null && (
                <span style={{ color: priceDelta >= 0 ? t.colors.success : t.colors.danger, fontFamily: t.fonts.mono }}>
                  ({priceDelta >= 0 ? "+" : ""}{fmt(priceDelta, 4, "$")})
                </span>
              )}
            </>
          )}
        </div>
      </button>

      {/* ── Data grid (always visible) ── */}
      <div
        className="grid grid-cols-2 gap-x-4 gap-y-2 px-3.5 pb-3.5"
        style={{ borderTop: `1px solid ${t.colors.borderLight}`, paddingTop: "0.625rem" }}
      >
        {/* Notional + margin */}
        <div>
          <p className="text-[10px]" style={{ color: t.colors.textMuted }}>Notional</p>
          <p className="text-[13px]" style={{ color: t.colors.text, fontFamily: t.fonts.mono }}>{fmt(notional)}</p>
        </div>
        <div>
          <p className="text-[10px]" style={{ color: t.colors.textMuted }}>Margin</p>
          <p className="text-[13px]" style={{ color: t.colors.text, fontFamily: t.fonts.mono }}>{fmt(margin)}</p>
        </div>

        {/* SL */}
        <div>
          <p className="text-[10px]" style={{ color: t.colors.textMuted }}>Stop Loss</p>
          {pos.sl_px ? (
            <p className="text-[13px]" style={{ color: t.colors.danger, fontFamily: t.fonts.mono }}>
              {fmt(pos.sl_px, 4, "$")}
              {pos.sl_distance && (
                <span className="text-[10px] ml-1" style={{ color: t.colors.textMuted }}>
                  {fmtPct(pos.sl_distance.pct)}{pos.sl_distance.atrs !== null ? ` · ${pos.sl_distance.atrs.toFixed(1)} ATR` : ""}
                </span>
              )}
            </p>
          ) : (
            <p className="text-[13px]" style={{ color: t.colors.textDim }}>—</p>
          )}
        </div>

        {/* TP */}
        <div>
          <p className="text-[10px]" style={{ color: t.colors.textMuted }}>Take Profit</p>
          {pos.tp_px ? (
            <p className="text-[13px]" style={{ color: t.colors.success, fontFamily: t.fonts.mono }}>
              {fmt(pos.tp_px, 4, "$")}
              {pos.tp_distance && (
                <span className="text-[10px] ml-1" style={{ color: t.colors.textMuted }}>
                  {fmtPct(pos.tp_distance.pct)}{pos.tp_distance.atrs !== null ? ` · ${pos.tp_distance.atrs.toFixed(1)} ATR` : ""}
                </span>
              )}
            </p>
          ) : (
            <p className="text-[13px]" style={{ color: t.colors.textDim }}>—</p>
          )}
        </div>

        {/* Liq */}
        <div>
          <p className="text-[10px]" style={{ color: t.colors.textMuted }}>Liquidation</p>
          {pos.liquidationPx ? (
            <p className="text-[13px]" style={{ color: t.colors.danger, fontFamily: t.fonts.mono }}>
              {fmt(parseFloat(pos.liquidationPx), 4, "$")}
              {pos.liq_cushion_pct !== null && (
                <span className="text-[10px] ml-1" style={{ color: t.colors.textMuted }}>
                  {pos.liq_cushion_pct.toFixed(1)}% away
                </span>
              )}
            </p>
          ) : (
            <p className="text-[13px]" style={{ color: t.colors.textDim }}>—</p>
          )}
        </div>

        {/* ATR + time-to-liq */}
        <div>
          <p className="text-[10px]" style={{ color: t.colors.textMuted }}>ATR (1d) / Liq in</p>
          <p className="text-[13px]" style={{ color: t.colors.text, fontFamily: t.fonts.mono }}>
            {pos.atr ? fmt(pos.atr, 4, "$") : "—"}
            {pos.time_to_liq_atrs !== null && (
              <span className="text-[10px] ml-1.5" style={{ color: t.colors.warning }}>
                liq {pos.time_to_liq_atrs.toFixed(1)} ATR
              </span>
            )}
          </p>
        </div>
      </div>

      {/* ── Expanded detail ── */}
      {expanded && (
        <div
          className="px-3.5 pb-3.5 text-[12px] space-y-1.5"
          style={{ borderTop: `1px solid ${t.colors.border}`, paddingTop: "0.625rem" }}
        >
          <div className="flex justify-between">
            <span style={{ color: t.colors.textMuted }}>ROE (return on equity)</span>
            <span style={{ color: pnlColor, fontFamily: t.fonts.mono }}>{fmtPct(roe, 2)}</span>
          </div>
          <div className="flex justify-between">
            <span style={{ color: t.colors.textMuted }}>Max leverage (instrument cap)</span>
            <span style={{ color: t.colors.text, fontFamily: t.fonts.mono }}>{pos.maxLeverage}x</span>
          </div>
          {pos.liq_atrs !== null && (
            <div className="flex justify-between">
              <span style={{ color: t.colors.textMuted }}>Liq distance (ATR multiples)</span>
              <span style={{ color: t.colors.warning, fontFamily: t.fonts.mono }}>{pos.liq_atrs.toFixed(2)} ATR</span>
            </div>
          )}
          <div className="flex justify-between">
            <span style={{ color: t.colors.textMuted }}>DEX</span>
            <span style={{ color: t.colors.text }}>{pos.dex}</span>
          </div>
          {pos.entry_ts && (
            <div className="flex justify-between">
              <span style={{ color: t.colors.textMuted }}>Opened at</span>
              <span style={{ color: t.colors.text, fontFamily: t.fonts.mono }}>
                {new Date(pos.entry_ts).toLocaleString()}
              </span>
            </div>
          )}
          <p className="text-[10px] pt-1" style={{ color: t.colors.textDim }}>
            Click card to collapse · Entry critique via /critique command in Telegram
          </p>
        </div>
      )}
    </div>
  );
}

// ─── Main component ───────────────────────────────────────────────────────────

export function DetailedPositionCards() {
  const { data, loading } = usePolling(getPositionsDetailed, 10000);

  if (loading && !data) return null;

  if (!data || data.positions.length === 0) {
    return (
      <div
        className="rounded-lg p-8 text-center"
        style={{ background: t.colors.surface, border: `1px solid ${t.colors.border}` }}
      >
        <p className="text-[13px]" style={{ color: t.colors.textMuted }}>No open positions</p>
        <p className="text-[11px] mt-1" style={{ color: t.colors.textDim }}>
          Positions will appear here when trades are open
        </p>
      </div>
    );
  }

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
      {data.positions.map((pos) => (
        <DetailedPositionCard key={`${pos.wallet}-${pos.coin}`} pos={pos} />
      ))}
    </div>
  );
}
