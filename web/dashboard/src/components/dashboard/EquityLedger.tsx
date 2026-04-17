"use client";

import { useState, useCallback } from "react";
import { usePolling } from "@/lib/hooks";
import {
  getAccountLedger,
  getRiskBudget,
  resetHWM,
  type AccountLedger,
  type WalletRow,
  type RiskBudget,
} from "@/lib/api";
import { theme as t } from "@/lib/theme";

// ─── Helpers ─────────────────────────────────────────────────────────────────

function fmt(v: number | null, digits = 2, prefix = "$"): string {
  if (v === null || v === undefined) return "—";
  return `${prefix}${v.toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })}`;
}

function fmtPct(v: number | null, digits = 2): string {
  if (v === null || v === undefined) return "—";
  return `${v.toFixed(digits)}%`;
}

// ─── Risk Gauge ───────────────────────────────────────────────────────────────

function RiskGauge({ data }: { data: RiskBudget | null }) {
  if (!data || data.risk_pct === null) {
    return (
      <div className="mt-3 pt-3" style={{ borderTop: `1px solid ${t.colors.border}` }}>
        <div className="flex items-center justify-between mb-1">
          <span className="text-[11px] font-medium" style={{ color: t.colors.textMuted, textTransform: "uppercase", letterSpacing: "0.05em" }}>
            Risk Budget
          </span>
          <span className="text-[11px]" style={{ color: t.colors.textDim }}>—</span>
        </div>
      </div>
    );
  }

  const pct = data.risk_pct * 100;
  const warnPct = data.warn_pct * 100;
  const capPct = data.cap_pct * 100;
  const fillPct = Math.min(pct / capPct * 100, 100);

  // Colour: green < warn, amber >= warn, red >= cap
  const fillColor =
    data.status === "critical"
      ? t.colors.danger
      : data.status === "warning"
      ? t.colors.warning
      : t.colors.success;

  // Marker positions as % of bar width
  const warnPos = (warnPct / capPct) * 100;

  return (
    <div className="mt-3 pt-3" style={{ borderTop: `1px solid ${t.colors.border}` }}>
      <div className="flex items-center justify-between mb-1.5">
        <span className="text-[11px] font-medium" style={{ color: t.colors.textMuted, textTransform: "uppercase", letterSpacing: "0.05em" }}>
          Risk Budget
        </span>
        <span
          className="text-[12px] font-semibold"
          style={{ color: fillColor, fontFamily: t.fonts.mono }}
        >
          {fmt(data.risk_usd)} &nbsp;·&nbsp; {fmtPct(pct, 1)} of equity
        </span>
      </div>

      {/* Bar */}
      <div className="relative h-2 rounded-full overflow-hidden" style={{ background: t.colors.borderLight }}>
        <div
          className="absolute left-0 top-0 h-full rounded-full transition-all duration-500"
          style={{ width: `${fillPct}%`, background: fillColor }}
        />
        {/* Warn marker at 8% */}
        <div
          className="absolute top-0 h-full w-px"
          style={{ left: `${warnPos}%`, background: t.colors.warning, opacity: 0.7 }}
        />
      </div>

      <div className="flex justify-between mt-0.5">
        <span className="text-[10px]" style={{ color: t.colors.textDim }}>0%</span>
        <span className="text-[10px]" style={{ color: t.colors.warning }}>
          {warnPct.toFixed(0)}% warn
        </span>
        <span className="text-[10px]" style={{ color: t.colors.danger }}>
          {capPct.toFixed(0)}% cap
        </span>
      </div>
    </div>
  );
}

// ─── HWM Reset Modal ──────────────────────────────────────────────────────────

function ResetHWMModal({
  currentEquity,
  currentHWM,
  onClose,
  onSuccess,
}: {
  currentEquity: number;
  currentHWM: number | null;
  onClose: () => void;
  onSuccess: () => void;
}) {
  const [reason, setReason] = useState("manual reset after equity formula correction");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleReset = async () => {
    if (!reason.trim()) {
      setError("Reason is required");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      await resetHWM(reason.trim());
      onSuccess();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Reset failed — check bearer auth");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center"
      style={{ background: "rgba(0,0,0,0.7)" }}
      onClick={onClose}
    >
      <div
        className="rounded-xl p-6 w-full max-w-sm"
        style={{ background: t.colors.surface, border: `1px solid ${t.colors.border}` }}
        onClick={(e) => e.stopPropagation()}
      >
        <h3 className="text-[15px] font-semibold mb-1" style={{ color: t.colors.text, fontFamily: t.fonts.heading }}>
          Reset High-Water Mark
        </h3>
        <p className="text-[12px] mb-4" style={{ color: t.colors.textMuted }}>
          Sets HWM to current equity. Drawdown resets to 0%. The old HWM is backed up.
        </p>

        <div className="grid grid-cols-2 gap-3 mb-4">
          <div className="p-3 rounded-lg" style={{ background: t.colors.borderLight }}>
            <p className="text-[10px] mb-0.5" style={{ color: t.colors.textMuted }}>Current Equity</p>
            <p className="text-[14px] font-semibold" style={{ color: t.colors.success, fontFamily: t.fonts.mono }}>
              {fmt(currentEquity)}
            </p>
          </div>
          <div className="p-3 rounded-lg" style={{ background: t.colors.borderLight }}>
            <p className="text-[10px] mb-0.5" style={{ color: t.colors.textMuted }}>Current HWM</p>
            <p className="text-[14px] font-semibold" style={{ color: t.colors.text, fontFamily: t.fonts.mono }}>
              {fmt(currentHWM)}
            </p>
          </div>
        </div>

        <div className="mb-4">
          <label className="text-[11px] block mb-1.5" style={{ color: t.colors.textMuted }}>
            Reason (required)
          </label>
          <input
            type="text"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            className="w-full px-3 py-2 rounded-lg text-[13px] outline-none"
            style={{
              background: t.colors.borderLight,
              border: `1px solid ${t.colors.border}`,
              color: t.colors.text,
            }}
            placeholder="Why are you resetting the HWM?"
          />
        </div>

        {error && (
          <p className="text-[12px] mb-3" style={{ color: t.colors.danger }}>{error}</p>
        )}

        <div className="flex gap-3">
          <button
            onClick={onClose}
            className="flex-1 py-2 rounded-lg text-[13px]"
            style={{ background: t.colors.borderLight, color: t.colors.textSecondary }}
          >
            Cancel
          </button>
          <button
            onClick={handleReset}
            disabled={loading}
            className="flex-1 py-2 rounded-lg text-[13px] font-medium"
            style={{
              background: loading ? t.colors.borderLight : t.colors.primary,
              color: loading ? t.colors.textMuted : "#fff",
              cursor: loading ? "not-allowed" : "pointer",
            }}
          >
            {loading ? "Resetting…" : "Confirm Reset"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ─── Wallet Row ───────────────────────────────────────────────────────────────

function WalletSection({ row }: { row: WalletRow }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div>
      {/* Wallet header — clickable to expand */}
      <button
        className="w-full text-left"
        onClick={() => setExpanded((v) => !v)}
      >
        <div className="flex items-center justify-between py-1.5">
          <div className="flex items-center gap-2">
            <span
              className="text-[11px] font-medium"
              style={{ color: t.colors.textSecondary }}
            >
              {expanded ? "▾" : "▸"}
            </span>
            <span className="text-[13px] font-medium" style={{ color: t.colors.text }}>
              {row.label}
            </span>
            {row.is_vault && (
              <span
                className="text-[10px] px-1.5 py-0.5 rounded"
                style={{ background: t.colors.primaryLight, color: t.colors.primary, border: `1px solid ${t.colors.primaryBorder}` }}
              >
                vault
              </span>
            )}
          </div>
          <span className="text-[14px] font-semibold" style={{ color: t.colors.text, fontFamily: t.fonts.mono }}>
            {fmt(row.total_equity)}
          </span>
        </div>
      </button>

      {/* Wallet detail — two-column grid */}
      <div
        className="grid grid-cols-2 gap-x-6 gap-y-0.5 pl-5 pb-1.5"
        style={{ fontSize: "12px" }}
      >
        <div className="flex justify-between">
          <span style={{ color: t.colors.textMuted }}>Spot USDC</span>
          <span style={{ color: t.colors.text, fontFamily: t.fonts.mono }}>{fmt(row.spot_usdc)}</span>
        </div>
        <div className="flex justify-between">
          <span style={{ color: t.colors.textMuted }}>Spot assets</span>
          <span style={{ color: t.colors.text, fontFamily: t.fonts.mono }}>
            {row.spot_assets > 0 ? fmt(row.spot_assets) : "—"}
          </span>
        </div>
        <div className="flex justify-between">
          <span style={{ color: t.colors.textMuted }}>Native perps</span>
          <span style={{ color: t.colors.text, fontFamily: t.fonts.mono }}>{fmt(row.native_equity)}</span>
        </div>
        <div className="flex justify-between">
          <span style={{ color: t.colors.textMuted }}>xyz perps</span>
          <span style={{ color: t.colors.text, fontFamily: t.fonts.mono }}>{fmt(row.xyz_equity)}</span>
        </div>
        <div className="flex justify-between col-span-2">
          <span style={{ color: t.colors.textMuted }}>Free margin</span>
          <span style={{ color: t.colors.text, fontFamily: t.fonts.mono }}>{fmt(row.free_margin)}</span>
        </div>
        {row.is_vault && (
          <>
            {/* Vault participant breakdown — sourced from HL vaultDetails API */}
            {row.vault_your_equity !== null ? (
              <>
                <div className="flex justify-between col-span-2 mt-0.5 pt-0.5" style={{ borderTop: `1px solid ${t.colors.borderLight}` }}>
                  <span style={{ color: t.colors.textMuted }}>Your share</span>
                  <span style={{ color: t.colors.success, fontFamily: t.fonts.mono }}>{fmt(row.vault_your_equity)}</span>
                </div>
                <div className="flex justify-between">
                  <span style={{ color: t.colors.textMuted }}>3rd-party equity</span>
                  <span style={{ color: t.colors.textSecondary, fontFamily: t.fonts.mono }}>{fmt(row.vault_third_party_equity)}</span>
                </div>
                <div className="flex justify-between">
                  <span style={{ color: t.colors.textMuted }}>Participants</span>
                  <span style={{ color: t.colors.textSecondary, fontFamily: t.fonts.mono }}>{row.vault_participant_count ?? "—"}</span>
                </div>
              </>
            ) : (
              <p className="col-span-2 text-[10px] mt-0.5" style={{ color: t.colors.textDim }}>
                Vault detail unavailable — HL API participant breakdown not reachable
              </p>
            )}
          </>
        )}
      </div>

      {/* Expanded: spot asset list */}
      {expanded && row.spot_balances.filter((b) => b.coin !== "USDC" && b.total > 0).length > 0 && (
        <div className="pl-5 pb-2">
          {row.spot_balances
            .filter((b) => b.coin !== "USDC" && b.total > 0)
            .map((b) => (
              <div key={b.coin} className="flex justify-between text-[12px]">
                <span style={{ color: t.colors.textSecondary }}>{b.coin}</span>
                <span style={{ color: t.colors.text, fontFamily: t.fonts.mono }}>{b.total}</span>
              </div>
            ))}
        </div>
      )}
    </div>
  );
}

// ─── Main Component ───────────────────────────────────────────────────────────

export function EquityLedger() {
  const [showResetModal, setShowResetModal] = useState(false);

  const { data, loading, error, refresh } = usePolling(getAccountLedger, 15000);
  const { data: riskData } = usePolling(getRiskBudget, 30000);

  const handleResetSuccess = useCallback(() => {
    setShowResetModal(false);
    // Refresh after a brief delay so the new HWM is picked up
    setTimeout(refresh, 500);
  }, [refresh]);

  if (loading && !data) {
    return (
      <div className="rounded-lg p-4" style={{ background: t.colors.surface, border: `1px solid ${t.colors.border}` }}>
        <p className="text-[13px]" style={{ color: t.colors.textMuted }}>{error || "Connecting…"}</p>
      </div>
    );
  }

  if (!data) return null;

  const { total_equity, accounts, unrealized_pnl, leverage_summary, hwm, realized_pnl, funding_today, trade_count_24h } = data as AccountLedger;

  // Unrealized: flatten to sorted list of (coin, upnl)
  const upnlEntries = Object.entries(unrealized_pnl || {}).sort((a, b) => a[0].localeCompare(b[0]));

  // HWM date display
  const hwmDate = hwm.set_at
    ? new Date(hwm.set_at).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" })
    : null;

  const drawdownColor =
    hwm.drawdown_pct !== null && hwm.drawdown_pct > 5
      ? t.colors.danger
      : hwm.drawdown_pct !== null && hwm.drawdown_pct > 2
      ? t.colors.warning
      : t.colors.textSecondary;

  return (
    <>
      {showResetModal && (
        <ResetHWMModal
          currentEquity={total_equity}
          currentHWM={hwm.value}
          onClose={() => setShowResetModal(false)}
          onSuccess={handleResetSuccess}
        />
      )}

      <div
        className="rounded-lg"
        style={{ background: t.colors.surface, border: `1px solid ${t.colors.border}` }}
      >
        {/* ─── Total header ─── */}
        <div
          className="flex items-baseline justify-between px-5 py-3"
          style={{ borderBottom: `1px solid ${t.colors.border}` }}
        >
          <span
            className="text-[11px] font-semibold tracking-widest"
            style={{ color: t.colors.textMuted, textTransform: "uppercase", fontFamily: t.fonts.heading }}
          >
            Total Equity
          </span>
          <span
            className="text-[26px] font-bold tracking-tight"
            style={{ color: t.colors.text, fontFamily: t.fonts.mono }}
          >
            {fmt(total_equity)}
          </span>
        </div>

        <div className="px-5 py-3 space-y-0">
          {/* ─── Per-wallet rows ─── */}
          <div style={{ borderBottom: `1px solid ${t.colors.border}`, paddingBottom: "0.75rem", marginBottom: "0.75rem" }}>
            {accounts.map((row) => (
              <WalletSection key={row.role} row={row} />
            ))}
          </div>

          {/* ─── Realized PnL row ─── */}
          <div className="flex items-center gap-4 py-1 text-[12px]" style={{ borderBottom: `1px solid ${t.colors.border}` }}>
            <span className="font-medium" style={{ color: t.colors.textMuted, minWidth: 100 }}>REALIZED P&L</span>
            <span style={{ color: t.colors.textSecondary }}>
              today&nbsp;
              <span style={{ color: t.colors.text, fontFamily: t.fonts.mono }}>
                {realized_pnl.today !== null ? fmt(realized_pnl.today) : "—"}
              </span>
            </span>
            <span style={{ color: t.colors.textSecondary }}>
              week&nbsp;
              <span style={{ color: t.colors.text, fontFamily: t.fonts.mono }}>
                {realized_pnl.week !== null ? fmt(realized_pnl.week) : "—"}
              </span>
            </span>
            <span style={{ color: t.colors.textSecondary }}>
              inception&nbsp;
              <span style={{ color: t.colors.text, fontFamily: t.fonts.mono }}>
                {realized_pnl.inception !== null ? fmt(realized_pnl.inception) : "—"}
              </span>
            </span>
          </div>

          {/* ─── Unrealized PnL + Leverage ─── */}
          <div className="py-1 text-[12px]" style={{ borderBottom: `1px solid ${t.colors.border}` }}>
            <div className="flex items-baseline gap-4 mb-0.5">
              <span className="font-medium" style={{ color: t.colors.textMuted, minWidth: 100 }}>UNREALIZED</span>
              {upnlEntries.length === 0 ? (
                <span style={{ color: t.colors.textDim }}>—</span>
              ) : (
                upnlEntries.map(([coin, upnl]) => (
                  <span key={coin} style={{ color: t.colors.textSecondary }}>
                    {coin.replace("xyz:", "")}&nbsp;
                    <span
                      style={{
                        color: upnl >= 0 ? t.colors.success : t.colors.danger,
                        fontFamily: t.fonts.mono,
                      }}
                    >
                      {upnl >= 0 ? "+" : ""}{fmt(upnl)}
                    </span>
                  </span>
                ))
              )}
            </div>
            <div className="flex items-baseline gap-4">
              <span className="font-medium" style={{ color: t.colors.textMuted, minWidth: 100 }}>LEVERAGE</span>
              <span style={{ color: t.colors.textSecondary }}>
                notional&nbsp;
                <span style={{ color: t.colors.text, fontFamily: t.fonts.mono }}>{fmt(leverage_summary.total_notional)}</span>
                &nbsp;/&nbsp;margin&nbsp;
                <span style={{ color: t.colors.text, fontFamily: t.fonts.mono }}>{fmt(leverage_summary.total_margin)}</span>
                &nbsp;=&nbsp;
                <span style={{ color: t.colors.text, fontFamily: t.fonts.mono }}>
                  {leverage_summary.effective_leverage > 0
                    ? `${leverage_summary.effective_leverage.toFixed(1)}x`
                    : "—"}
                </span>
                &nbsp;eff
              </span>
            </div>
          </div>

          {/* ─── HWM + Drawdown ─── */}
          <div className="flex items-center gap-4 py-1 text-[12px]" style={{ borderBottom: `1px solid ${t.colors.border}` }}>
            <span className="font-medium" style={{ color: t.colors.textMuted, minWidth: 100 }}>HWM</span>
            <span style={{ color: t.colors.textSecondary }}>
              {/* Flag stale HWM: if HWM is much lower than current equity it was
                  set before the equity formula was corrected (pre-2026-04-17).
                  Threshold: HWM < 20% of total equity → clearly stale. */}
              {hwm.value !== null && total_equity > 0 && hwm.value < total_equity * 0.2 ? (
                <span
                  className="px-1.5 py-0.5 rounded text-[10px] font-semibold mr-1"
                  style={{ background: t.colors.warningLight, color: t.colors.warning, border: `1px solid ${t.colors.warningBorder}` }}
                  title="HWM was set before the equity formula was corrected. Reset it to today's equity."
                >
                  STALE — reset recommended
                </span>
              ) : (
                <>
                  <span style={{ color: t.colors.text, fontFamily: t.fonts.mono }}>{fmt(hwm.value)}</span>
                  {hwmDate && (
                    <span style={{ color: t.colors.textDim }}> (set {hwmDate})</span>
                  )}
                  {hwm.drawdown_pct !== null && (
                    <span style={{ color: t.colors.textSecondary }}>
                      &nbsp;·&nbsp;Drawdown&nbsp;
                      <span style={{ color: drawdownColor, fontFamily: t.fonts.mono }}>
                        {fmtPct(hwm.drawdown_pct, 2)}
                      </span>
                    </span>
                  )}
                </>
              )}
            </span>
            <button
              onClick={() => setShowResetModal(true)}
              className="ml-auto px-2.5 py-1 rounded text-[11px] font-medium transition-colors"
              style={{
                background: t.colors.borderLight,
                color: t.colors.textSecondary,
                border: `1px solid ${t.colors.border}`,
              }}
            >
              Reset HWM
            </button>
          </div>

          {/* ─── 24h summary ─── */}
          <div className="flex items-center gap-4 py-1 text-[12px]">
            <span className="font-medium" style={{ color: t.colors.textMuted, minWidth: 100 }}>24H</span>
            <span style={{ color: t.colors.textSecondary }}>
              Trades&nbsp;
              <span style={{ color: t.colors.text, fontFamily: t.fonts.mono }}>
                {trade_count_24h !== null ? trade_count_24h : "—"}
              </span>
            </span>
            <span style={{ color: t.colors.textSecondary }}>
              Funding&nbsp;
              <span style={{ color: t.colors.text, fontFamily: t.fonts.mono }}>
                {funding_today !== null ? fmt(funding_today) : "—"}
              </span>
            </span>
          </div>

          {/* ─── Risk budget gauge ─── */}
          <RiskGauge data={riskData ?? null} />
        </div>
      </div>
    </>
  );
}
