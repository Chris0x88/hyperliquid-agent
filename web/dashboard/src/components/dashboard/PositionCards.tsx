"use client";

import { usePolling } from "@/lib/hooks";
import { getAccountStatus, type Position } from "@/lib/api";
import { theme as t } from "@/lib/theme";

function PositionCard({ pos }: { pos: Position }) {
  const pnl = parseFloat(pos.unrealizedPnl);
  const value = parseFloat(pos.positionValue);
  const entry = parseFloat(pos.entryPx);
  const size = parseFloat(pos.szi);
  const side = size > 0 ? "LONG" : "SHORT";
  const roe = parseFloat(pos.returnOnEquity) * 100;
  const sideColor = side === "LONG" ? t.colors.success : t.colors.danger;

  return (
    <div className="rounded-lg p-4" style={{ background: t.colors.surface, border: `1px solid ${t.colors.border}` }}>
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <span className="text-[14px] font-semibold" style={{ color: t.colors.text, fontFamily: t.fonts.heading }}>{pos.coin}</span>
          <span className="px-2 py-0.5 rounded text-[10px] font-semibold uppercase"
            style={{ background: `${sideColor}18`, color: sideColor, border: `1px solid ${sideColor}35` }}>
            {side}
          </span>
        </div>
        <span className="text-[12px]" style={{ color: t.colors.textMuted }}>{pos.leverage.value}x</span>
      </div>
      <div className="grid grid-cols-2 gap-x-6 gap-y-3">
        <div>
          <p className="text-[11px]" style={{ color: t.colors.textMuted }}>Entry</p>
          <p className="text-[14px]" style={{ color: t.colors.text, fontFamily: t.fonts.mono }}>${entry.toFixed(2)}</p>
        </div>
        <div>
          <p className="text-[11px]" style={{ color: t.colors.textMuted }}>Value</p>
          <p className="text-[14px]" style={{ color: t.colors.text, fontFamily: t.fonts.mono }}>${value.toFixed(2)}</p>
        </div>
        <div>
          <p className="text-[11px]" style={{ color: t.colors.textMuted }}>uPnL</p>
          <p className="text-[14px]" style={{ color: pnl >= 0 ? t.colors.success : t.colors.danger, fontFamily: t.fonts.mono }}>
            ${pnl.toFixed(2)} ({roe >= 0 ? "+" : ""}{roe.toFixed(1)}%)
          </p>
        </div>
        <div>
          <p className="text-[11px]" style={{ color: t.colors.textMuted }}>Liq. Price</p>
          <p className="text-[14px]" style={{ color: t.colors.text, fontFamily: t.fonts.mono }}>
            {pos.liquidationPx ? `$${parseFloat(pos.liquidationPx).toFixed(2)}` : "N/A"}
          </p>
        </div>
      </div>
    </div>
  );
}

export function PositionCards() {
  const { data, loading } = usePolling(getAccountStatus, 10000);
  if (loading || !data) return null;
  if (data.positions.length === 0) {
    return (
      <div className="rounded-lg p-8 text-center" style={{ background: t.colors.surface, border: `1px solid ${t.colors.border}` }}>
        <p className="text-[13px]" style={{ color: t.colors.textMuted }}>No open positions</p>
        <p className="text-[11px] mt-1" style={{ color: t.colors.textDim }}>Positions will appear here when trades are open</p>
      </div>
    );
  }
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
      {data.positions.map((pos) => <PositionCard key={pos.coin} pos={pos} />)}
    </div>
  );
}
