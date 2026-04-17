"use client";

import { usePolling } from "@/lib/hooks";
import { getHealth, type ProcessStatus } from "@/lib/api";
import { theme as t } from "@/lib/theme";

// ── Small dot + PID pill used in the banner ───────────────────────────────────

function ProcessDot({ label, status }: { label: string; status: ProcessStatus }) {
  const running = status.running;
  return (
    <span className="inline-flex items-center gap-1 text-[11px]" style={{ color: t.colors.textSecondary }}>
      <span
        className="w-1.5 h-1.5 rounded-full flex-shrink-0"
        style={{
          background: running ? t.colors.success : t.colors.danger,
          boxShadow: running ? `0 0 4px ${t.colors.success}` : "none",
        }}
      />
      <span style={{ color: t.colors.textDim }}>{label}</span>
      {running && status.pid && (
        <span style={{ color: t.colors.textDim, fontFamily: t.fonts.mono }}>{status.pid}</span>
      )}
    </span>
  );
}

function TierChip({ tier }: { tier: string }) {
  const styles: Record<string, { bg: string; text: string; border: string }> = {
    watch: { bg: t.colors.tertiaryLight, text: t.colors.tertiary, border: t.colors.tertiaryBorder },
    rebalance: { bg: t.colors.warningLight, text: t.colors.warning, border: t.colors.warningBorder },
    opportunistic: { bg: t.colors.primaryLight, text: t.colors.primary, border: t.colors.primaryBorder },
  };
  const s = styles[tier.toLowerCase()] || styles.watch;
  return (
    <span
      className="px-2 py-0.5 rounded text-[10px] font-semibold uppercase tracking-wider"
      style={{ background: s.bg, color: s.text, border: `1px solid ${s.border}` }}
    >
      {tier}
    </span>
  );
}

// ── Horizontal status strip — used in the Dashboard page header row ───────────

export function HealthBanner() {
  const { data, loading } = usePolling(getHealth, 15000);

  if (loading || !data) {
    return (
      <div
        className="flex items-center gap-2 px-3 py-1.5 rounded-lg text-[11px]"
        style={{ background: t.colors.surface, border: `1px solid ${t.colors.border}`, color: t.colors.textDim }}
      >
        <span className="w-1.5 h-1.5 rounded-full" style={{ background: t.colors.textDim }} />
        Connecting…
      </div>
    );
  }

  const anyDown =
    !data.processes.daemon.running || !data.processes.telegram_bot.running;

  return (
    <div
      className="flex items-center gap-3 px-3 py-1.5 rounded-lg flex-wrap"
      style={{
        background: t.colors.surface,
        border: `1px solid ${anyDown ? t.colors.dangerBorder : t.colors.border}`,
        gap: "12px",
      }}
    >
      {/* Process dots */}
      <ProcessDot label="Daemon" status={data.processes.daemon} />
      <ProcessDot label="Bot" status={data.processes.telegram_bot} />
      <ProcessDot label="Rebalancer" status={data.processes.vault_rebalancer} />

      {/* Divider */}
      <span style={{ color: t.colors.borderLight, userSelect: "none" }}>|</span>

      {/* Tier */}
      <TierChip tier={data.daemon.tier} />

      {/* Ticks */}
      <span className="text-[11px]" style={{ color: t.colors.textDim }}>
        <span style={{ color: t.colors.textSecondary }}>Ticks</span>
        {" "}
        <span style={{ fontFamily: t.fonts.mono, color: t.colors.text }}>{data.daemon.tick_count.toLocaleString()}</span>
      </span>

      {/* Daily P&L */}
      <span className="text-[11px]" style={{ color: t.colors.textDim }}>
        <span style={{ color: t.colors.textSecondary }}>P&L</span>
        {" "}
        {data.daemon.daily_pnl === null ? (
          <span style={{ fontFamily: t.fonts.mono }}>—</span>
        ) : (
          <span style={{ fontFamily: t.fonts.mono, color: data.daemon.daily_pnl >= 0 ? t.colors.success : t.colors.danger }}>
            ${data.daemon.daily_pnl.toFixed(2)}
          </span>
        )}
      </span>

      {/* Heartbeat */}
      {data.heartbeat.escalation_level > 0 && (
        <span
          className="text-[10px] px-1.5 py-0.5 rounded font-medium"
          style={{ background: t.colors.dangerLight, color: t.colors.danger, border: `1px solid ${t.colors.dangerBorder}` }}
        >
          HB L{data.heartbeat.escalation_level}
        </span>
      )}
    </div>
  );
}

// ── Legacy full-card kept for backward compat (no longer rendered on dashboard)

function StatusRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between py-2.5" style={{ borderBottom: `1px solid ${t.colors.borderLight}` }}>
      <span className="text-[13px]" style={{ color: t.colors.textSecondary }}>{label}</span>
      {children}
    </div>
  );
}

function ProcessBadge({ status }: { status: ProcessStatus }) {
  if (status.running) {
    return (
      <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-md text-[11px] font-medium"
        style={{ background: t.colors.successLight, color: t.colors.success, border: `1px solid ${t.colors.successBorder}` }}>
        <span className="w-1.5 h-1.5 rounded-full" style={{ background: t.colors.success }} />
        PID {status.pid}
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-md text-[11px] font-medium"
      style={{ background: t.colors.dangerLight, color: t.colors.danger, border: `1px solid ${t.colors.dangerBorder}` }}>
      OFF
    </span>
  );
}

/** @deprecated Use HealthBanner instead — kept for non-dashboard contexts */
export function HealthPanel() {
  const { data, loading } = usePolling(getHealth, 15000);

  if (loading || !data) {
    return (
      <div className="rounded-lg p-5" style={{ background: t.colors.surface, border: `1px solid ${t.colors.border}` }}>
        <p className="text-[13px]" style={{ color: t.colors.textMuted }}>Connecting...</p>
      </div>
    );
  }

  return (
    <div className="rounded-lg p-5" style={{ background: t.colors.surface, border: `1px solid ${t.colors.border}` }}>
      <h3 className="text-[13px] font-medium mb-3"
        style={{ color: t.colors.textMuted, textTransform: "uppercase", letterSpacing: "0.05em", fontFamily: t.fonts.heading }}>
        System Health
      </h3>
      <div className="space-y-0">
        <StatusRow label="Daemon"><ProcessBadge status={data.processes.daemon} /></StatusRow>
        <StatusRow label="Telegram Bot"><ProcessBadge status={data.processes.telegram_bot} /></StatusRow>
        <StatusRow label="Rebalancer"><ProcessBadge status={data.processes.vault_rebalancer} /></StatusRow>
        <StatusRow label="Tier">
          <TierChip tier={data.daemon.tier} />
        </StatusRow>
        <StatusRow label="Ticks">
          <span className="text-[13px]" style={{ color: t.colors.text, fontFamily: t.fonts.mono }}>{data.daemon.tick_count.toLocaleString()}</span>
        </StatusRow>
        <StatusRow label="Daily P&L">
          {data.daemon.daily_pnl === null ? (
            <span className="text-[13px]" style={{ color: t.colors.textDim, fontFamily: t.fonts.mono }}>—</span>
          ) : (
            <span className="text-[13px]" style={{ color: data.daemon.daily_pnl >= 0 ? t.colors.success : t.colors.danger, fontFamily: t.fonts.mono }}>
              ${data.daemon.daily_pnl.toFixed(2)}
            </span>
          )}
        </StatusRow>
        <div className="flex items-center justify-between py-2.5">
          <span className="text-[13px]" style={{ color: t.colors.textSecondary }}>Heartbeat</span>
          <span className="px-2.5 py-0.5 rounded-md text-[11px] font-medium"
            style={{
              background: data.heartbeat.escalation_level === 0 ? t.colors.successLight : t.colors.dangerLight,
              color: data.heartbeat.escalation_level === 0 ? t.colors.success : t.colors.danger,
              border: `1px solid ${data.heartbeat.escalation_level === 0 ? t.colors.successBorder : t.colors.dangerBorder}`,
            }}>
            L{data.heartbeat.escalation_level}
          </span>
        </div>
      </div>
    </div>
  );
}
