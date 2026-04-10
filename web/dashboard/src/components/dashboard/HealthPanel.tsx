"use client";

import { usePolling } from "@/lib/hooks";
import { getHealth, type ProcessStatus } from "@/lib/api";
import { theme as t } from "@/lib/theme";

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

function TierBadge({ tier }: { tier: string }) {
  const styles: Record<string, { bg: string; text: string; border: string }> = {
    watch: { bg: t.colors.tertiaryLight, text: t.colors.tertiary, border: t.colors.tertiaryBorder },
    rebalance: { bg: t.colors.warningLight, text: t.colors.warning, border: t.colors.warningBorder },
    opportunistic: { bg: t.colors.primaryLight, text: t.colors.primary, border: t.colors.primaryBorder },
  };
  const s = styles[tier] || styles.watch;
  return (
    <span className="px-2.5 py-0.5 rounded-md text-[11px] font-semibold uppercase tracking-wider"
      style={{ background: s.bg, color: s.text, border: `1px solid ${s.border}` }}>
      {tier}
    </span>
  );
}

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
        <StatusRow label="Tier"><TierBadge tier={data.daemon.tier} /></StatusRow>
        <StatusRow label="Ticks">
          <span className="text-[13px]" style={{ color: t.colors.text, fontFamily: t.fonts.mono }}>{data.daemon.tick_count.toLocaleString()}</span>
        </StatusRow>
        <StatusRow label="Daily P&L">
          <span className="text-[13px]" style={{ color: data.daemon.daily_pnl >= 0 ? t.colors.success : t.colors.danger, fontFamily: t.fonts.mono }}>
            ${data.daemon.daily_pnl.toFixed(2)}
          </span>
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
