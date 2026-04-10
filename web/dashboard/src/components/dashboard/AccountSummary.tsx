"use client";

import { usePolling } from "@/lib/hooks";
import { getAccountStatus } from "@/lib/api";
import { theme as t } from "@/lib/theme";

export function AccountSummary() {
  const { data, loading, error } = usePolling(getAccountStatus, 10000);

  if (loading || !data) {
    return (
      <div className="rounded-lg p-6" style={{ background: t.colors.surface, border: `1px solid ${t.colors.border}` }}>
        <p className="text-[13px]" style={{ color: t.colors.textMuted }}>{error || "Connecting..."}</p>
      </div>
    );
  }

  const totalSpot = data.spot.reduce((sum, s) => s.coin === "USDC" ? sum + s.total : sum, 0);

  return (
    <div className="rounded-lg p-6" style={{ background: t.colors.surface, border: `1px solid ${t.colors.border}` }}>
      <div className="mb-6">
        <p className="text-[13px] font-medium mb-1" style={{ color: t.colors.textMuted, fontFamily: t.fonts.heading }}>
          Total Equity
        </p>
        <p className="text-4xl font-bold tracking-tight" style={{ color: t.colors.text, fontFamily: t.fonts.mono }}>
          ${data.equity.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
        </p>
      </div>

      <div className="grid grid-cols-3 gap-6" style={{ borderTop: `1px solid ${t.colors.border}`, paddingTop: "1rem" }}>
        <div>
          <p className="text-2xl font-semibold" style={{ color: t.colors.text, fontFamily: t.fonts.mono }}>{data.positions.length}</p>
          <p className="text-[12px] mt-0.5" style={{ color: t.colors.textMuted }}>Open Positions</p>
        </div>
        <div>
          <p className="text-2xl font-semibold" style={{ color: t.colors.text, fontFamily: t.fonts.mono }}>${totalSpot.toFixed(2)}</p>
          <p className="text-[12px] mt-0.5" style={{ color: t.colors.textMuted }}>USDC Balance</p>
        </div>
        <div>
          <p className="text-2xl font-semibold" style={{ color: t.colors.text, fontFamily: t.fonts.mono }}>{data.spot.filter(s => s.coin !== "USDC" && s.total > 0).length}</p>
          <p className="text-[12px] mt-0.5" style={{ color: t.colors.textMuted }}>Spot Assets</p>
        </div>
      </div>

      {data.spot.filter(s => s.coin !== "USDC" && s.total > 0).length > 0 && (
        <div className="mt-4 pt-4" style={{ borderTop: `1px solid ${t.colors.border}` }}>
          {data.spot.filter(s => s.coin !== "USDC" && s.total > 0).map(s => (
            <div key={s.coin} className="flex justify-between py-1">
              <span className="text-[13px]" style={{ color: t.colors.textSecondary }}>{s.coin}</span>
              <span className="text-[13px]" style={{ color: t.colors.text, fontFamily: t.fonts.mono }}>{s.total}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
