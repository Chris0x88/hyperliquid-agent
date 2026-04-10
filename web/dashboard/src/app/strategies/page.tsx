"use client";

import { useState } from "react";
import { usePolling } from "@/lib/hooks";
import {
  getStrategies,
  getOilBotState,
  getOilBotJournal,
  getOilBotConfig,
  type StrategyInfo,
  type SubSystemState,
  type JournalEntry,
} from "@/lib/api";
import { theme as t } from "@/lib/theme";

// ── Helpers ──────────────────────────────────────────────────────────────────

function fmt(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    return d.toLocaleString("en-AU", {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      timeZone: "Australia/Brisbane",
    });
  } catch {
    return iso;
  }
}

function fmtPnl(v: number): string {
  const sign = v >= 0 ? "+" : "";
  return `${sign}$${Math.abs(v).toFixed(2)}`;
}

// ── Sub-section label ─────────────────────────────────────────────────────────

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <h3
      className="text-[12px] font-semibold uppercase tracking-widest mb-3"
      style={{ color: t.colors.textMuted, fontFamily: t.fonts.heading }}
    >
      {children}
    </h3>
  );
}

// ── Strategy overview card ────────────────────────────────────────────────────

function StrategyCard({ strategy }: { strategy: StrategyInfo }) {
  const statusColor = strategy.enabled ? t.colors.success : t.colors.textDim;
  const statusBg = strategy.enabled ? t.colors.successLight : t.colors.neutralLight;
  const statusBorder = strategy.enabled ? t.colors.successBorder : t.colors.border;

  return (
    <div
      className="rounded-xl p-5"
      style={{ background: t.colors.surface, border: `1px solid ${t.colors.border}` }}
    >
      {/* Header */}
      <div className="flex items-start justify-between mb-4">
        <div>
          <h3
            className="text-[16px] font-semibold"
            style={{ color: t.colors.text, fontFamily: t.fonts.heading }}
          >
            {strategy.name}
          </h3>
          <p className="text-[12px] mt-0.5" style={{ color: t.colors.textMuted }}>
            {strategy.instruments.join(", ") || "No instruments"}
          </p>
        </div>
        <span
          className="text-[11px] font-semibold uppercase px-2.5 py-1 rounded-full"
          style={{ background: statusBg, color: statusColor, border: `1px solid ${statusBorder}` }}
        >
          {strategy.enabled ? "Active" : "Disabled"}
        </span>
      </div>

      {/* Key indicators */}
      <div className="grid grid-cols-3 gap-3 mb-4">
        <div
          className="rounded-lg p-3"
          style={{ background: t.colors.bg, border: `1px solid ${t.colors.borderLight}` }}
        >
          <p className="text-[10px] uppercase tracking-wider mb-1" style={{ color: t.colors.textDim }}>
            Mode
          </p>
          <p
            className="text-[13px] font-semibold"
            style={{ color: strategy.decisions_only ? t.colors.warning : t.colors.success }}
          >
            {strategy.decisions_only ? "Shadow" : "Live"}
          </p>
        </div>
        <div
          className="rounded-lg p-3"
          style={{ background: t.colors.bg, border: `1px solid ${t.colors.borderLight}` }}
        >
          <p className="text-[10px] uppercase tracking-wider mb-1" style={{ color: t.colors.textDim }}>
            Sub-systems
          </p>
          <p className="text-[13px] font-semibold" style={{ color: t.colors.text }}>
            {strategy.sub_system_count}
          </p>
        </div>
        <div
          className="rounded-lg p-3"
          style={{ background: t.colors.bg, border: `1px solid ${t.colors.borderLight}` }}
        >
          <p className="text-[10px] uppercase tracking-wider mb-1" style={{ color: t.colors.textDim }}>
            Brakes
          </p>
          <p
            className="text-[13px] font-semibold"
            style={{ color: strategy.brakes_tripped > 0 ? t.colors.danger : t.colors.success }}
          >
            {strategy.brakes_tripped > 0 ? `${strategy.brakes_tripped} tripped` : "Clear"}
          </p>
        </div>
      </div>

      {/* Kill switches */}
      <div className="flex flex-wrap gap-2">
        <KillSwitch label="Short legs" active={strategy.short_legs_enabled} />
        <KillSwitch label="Shadow mode" active={strategy.decisions_only} warnWhenActive />
      </div>
    </div>
  );
}

function KillSwitch({
  label,
  active,
  warnWhenActive = false,
}: {
  label: string;
  active: boolean;
  warnWhenActive?: boolean;
}) {
  const on = active;
  let color: string = on ? t.colors.success : t.colors.textDim;
  let bg: string = on ? t.colors.successLight : t.colors.neutralLight;
  let border: string = on ? t.colors.successBorder : t.colors.border;

  if (warnWhenActive && on) {
    color = t.colors.warning;
    bg = t.colors.warningLight;
    border = t.colors.warningBorder;
  }

  return (
    <span
      className="text-[11px] px-2.5 py-1 rounded-full font-medium"
      style={{ background: bg, color, border: `1px solid ${border}` }}
    >
      {label}: {on ? "ON" : "OFF"}
    </span>
  );
}

// ── Sub-system grid ───────────────────────────────────────────────────────────

function SubSystemGrid({ subsystems }: { subsystems: SubSystemState[] }) {
  return (
    <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-3">
      {subsystems.map((ss) => {
        const statusColor = ss.enabled ? t.colors.success : t.colors.textDim;
        const dot = ss.enabled ? t.colors.success : t.colors.textDim;
        return (
          <div
            key={ss.name}
            className="rounded-lg p-3.5"
            style={{ background: t.colors.surface, border: `1px solid ${t.colors.border}` }}
          >
            <div className="flex items-center justify-between mb-2">
              <span
                className="text-[10px] font-bold uppercase tracking-wider"
                style={{ color: t.colors.textDim }}
              >
                SS-{ss.id}
              </span>
              <div
                className="w-2 h-2 rounded-full"
                style={{
                  background: dot,
                  boxShadow: ss.enabled ? `0 0 6px ${dot}` : "none",
                }}
              />
            </div>
            <p
              className="text-[12px] font-semibold leading-tight"
              style={{ color: t.colors.text, fontFamily: t.fonts.heading }}
            >
              {ss.label}
            </p>
            <p
              className="text-[11px] mt-1 font-medium"
              style={{ color: statusColor }}
            >
              {ss.enabled ? "Enabled" : "Disabled"}
            </p>
            {!ss.has_config && (
              <p className="text-[10px] mt-0.5" style={{ color: t.colors.textDim }}>
                no config
              </p>
            )}
          </div>
        );
      })}
    </div>
  );
}

// ── PnL state panel ───────────────────────────────────────────────────────────

function StatePanel() {
  const { data, loading } = usePolling(getOilBotState, 15000);

  if (loading || !data)
    return (
      <p className="text-[13px]" style={{ color: t.colors.textDim }}>
        Loading state...
      </p>
    );

  const s = data.state;

  const rows = [
    { label: "Daily PnL", value: fmtPnl(s.daily_realised_pnl_usd), window: s.daily_window_start },
    { label: "Weekly PnL", value: fmtPnl(s.weekly_realised_pnl_usd), window: s.weekly_window_start },
    { label: "Monthly PnL", value: fmtPnl(s.monthly_realised_pnl_usd), window: s.monthly_window_start },
  ];

  const brakeRows = [
    { label: "Daily brake", at: s.daily_brake_tripped_at },
    { label: "Weekly brake", at: s.weekly_brake_tripped_at },
    { label: "Monthly brake", at: s.monthly_brake_tripped_at },
  ];

  const openCount = Object.keys(s.open_positions || {}).length;

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
      {/* PnL */}
      <div
        className="rounded-lg overflow-hidden"
        style={{ background: t.colors.surface, border: `1px solid ${t.colors.border}` }}
      >
        <div
          className="px-4 py-2.5 border-b"
          style={{ borderColor: t.colors.borderLight }}
        >
          <p
            className="text-[12px] font-semibold uppercase tracking-wider"
            style={{ color: t.colors.textMuted, fontFamily: t.fonts.heading }}
          >
            Realised PnL
          </p>
        </div>
        <div className="p-4 space-y-3">
          {rows.map((r) => (
            <div key={r.label} className="flex items-center justify-between">
              <div>
                <p className="text-[13px]" style={{ color: t.colors.text }}>
                  {r.label}
                </p>
                <p className="text-[11px]" style={{ color: t.colors.textDim }}>
                  {r.window}
                </p>
              </div>
              <span
                className="text-[14px] font-semibold font-mono"
                style={{
                  color:
                    parseFloat(r.value) >= 0 ? t.colors.success : t.colors.danger,
                  fontFamily: t.fonts.mono,
                }}
              >
                {r.value}
              </span>
            </div>
          ))}
          <div className="flex items-center justify-between pt-2" style={{ borderTop: `1px solid ${t.colors.borderLight}` }}>
            <p className="text-[13px]" style={{ color: t.colors.text }}>Open positions</p>
            <span className="text-[14px] font-semibold" style={{ color: t.colors.text, fontFamily: t.fonts.mono }}>
              {openCount}
            </span>
          </div>
        </div>
      </div>

      {/* Drawdown brakes */}
      <div
        className="rounded-lg overflow-hidden"
        style={{ background: t.colors.surface, border: `1px solid ${t.colors.border}` }}
      >
        <div
          className="px-4 py-2.5 border-b"
          style={{ borderColor: t.colors.borderLight }}
        >
          <p
            className="text-[12px] font-semibold uppercase tracking-wider"
            style={{ color: t.colors.textMuted, fontFamily: t.fonts.heading }}
          >
            Drawdown Brakes
          </p>
        </div>
        <div className="p-4 space-y-3">
          {brakeRows.map((r) => (
            <div key={r.label} className="flex items-center justify-between">
              <p className="text-[13px]" style={{ color: t.colors.text }}>
                {r.label}
              </p>
              <span
                className="text-[12px] font-medium"
                style={{
                  color: r.at ? t.colors.danger : t.colors.success,
                }}
              >
                {r.at ? `Tripped ${fmt(r.at)}` : "Clear"}
              </span>
            </div>
          ))}
          {s.brake_cleared_at && (
            <p className="text-[11px] pt-1" style={{ color: t.colors.textDim }}>
              Last cleared: {fmt(s.brake_cleared_at)}
            </p>
          )}
          {s.enabled_since && (
            <p className="text-[11px] pt-1" style={{ color: t.colors.textDim }}>
              Active since: {fmt(s.enabled_since)}
            </p>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Decision journal ──────────────────────────────────────────────────────────

const ACTION_STYLES: Record<string, { color: string; bg: string }> = {
  enter: { color: t.colors.success, bg: t.colors.successLight },
  exit: { color: t.colors.tertiary, bg: t.colors.tertiaryLight },
  skip: { color: t.colors.textDim, bg: t.colors.neutralLight },
  hold: { color: t.colors.warning, bg: t.colors.warningLight },
};

function JournalTable({ entries }: { entries: JournalEntry[] }) {
  if (entries.length === 0) {
    return (
      <div
        className="rounded-lg p-8 text-center"
        style={{ background: t.colors.surface, border: `1px solid ${t.colors.border}` }}
      >
        <p className="text-[13px]" style={{ color: t.colors.textDim }}>
          No journal entries yet.
        </p>
      </div>
    );
  }

  return (
    <div
      className="rounded-lg overflow-hidden"
      style={{ background: t.colors.surface, border: `1px solid ${t.colors.border}` }}
    >
      {/* Header */}
      <div
        className="grid gap-3 px-4 py-2 border-b"
        style={{
          gridTemplateColumns: "140px 90px 60px 60px 60px 1fr",
          borderColor: t.colors.borderLight,
        }}
      >
        {["Time", "Instrument", "Dir", "Action", "Edge", "Notes"].map((h) => (
          <span
            key={h}
            className="text-[10px] font-semibold uppercase tracking-wider"
            style={{ color: t.colors.textDim }}
          >
            {h}
          </span>
        ))}
      </div>

      {/* Rows */}
      <div
        className="max-h-[400px] overflow-y-auto"
        style={{ scrollbarWidth: "thin", scrollbarColor: `${t.colors.border} transparent` }}
      >
        {entries.map((e, i) => {
          const actionStyle =
            ACTION_STYLES[e.action] || { color: t.colors.textSecondary, bg: "transparent" };
          return (
            <div
              key={e.id || i}
              className="grid gap-3 px-4 py-2.5 items-center transition-colors hover:bg-[#1a1b22]"
              style={{
                gridTemplateColumns: "140px 90px 60px 60px 60px 1fr",
                borderBottom: `1px solid ${t.colors.borderLight}`,
              }}
            >
              <span className="text-[11px]" style={{ color: t.colors.textDim, fontFamily: t.fonts.mono }}>
                {fmt(e.decided_at)}
              </span>
              <span
                className="text-[12px] font-medium"
                style={{ color: t.colors.text, fontFamily: t.fonts.heading }}
              >
                {e.instrument}
              </span>
              <span
                className="text-[11px] uppercase font-semibold"
                style={{
                  color: e.direction === "long" ? t.colors.success : t.colors.danger,
                }}
              >
                {e.direction}
              </span>
              <span
                className="text-[11px] uppercase font-semibold px-1.5 py-0.5 rounded"
                style={{ background: actionStyle.bg, color: actionStyle.color }}
              >
                {e.action}
              </span>
              <span
                className="text-[12px] font-mono"
                style={{ color: t.colors.textSecondary, fontFamily: t.fonts.mono }}
              >
                {e.edge.toFixed(2)}
              </span>
              <span
                className="text-[11px] truncate"
                style={{ color: t.colors.textSecondary }}
                title={e.notes}
              >
                {e.notes || "—"}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function JournalSection() {
  const [limit, setLimit] = useState(20);
  const { data, loading } = usePolling(() => getOilBotJournal(limit), 20000);

  return (
    <div>
      <div className="flex items-center justify-between mb-3">
        <SectionLabel>Decision Journal</SectionLabel>
        <div className="flex gap-1">
          {[10, 20, 50].map((n) => (
            <button
              key={n}
              onClick={() => setLimit(n)}
              className="px-2.5 py-1 rounded text-[11px] font-medium transition-all"
              style={
                limit === n
                  ? { background: t.colors.primaryLight, color: t.colors.primary, border: `1px solid ${t.colors.primaryBorder}` }
                  : { color: t.colors.textDim, border: `1px solid ${t.colors.border}` }
              }
            >
              {n}
            </button>
          ))}
        </div>
      </div>
      {loading && !data ? (
        <p className="text-[13px]" style={{ color: t.colors.textDim }}>
          Loading journal...
        </p>
      ) : (
        <JournalTable entries={data?.journal || []} />
      )}
    </div>
  );
}

// ── Config viewer ─────────────────────────────────────────────────────────────

function ConfigSection() {
  const { data, loading } = usePolling(getOilBotConfig, 60000);
  const [expanded, setExpanded] = useState(false);

  if (loading && !data) {
    return <p className="text-[13px]" style={{ color: t.colors.textDim }}>Loading config...</p>;
  }

  const cfg = data?.config || {};

  // Key fields to highlight
  const keyFields: { key: string; label: string }[] = [
    { key: "enabled", label: "Enabled" },
    { key: "decisions_only", label: "Shadow mode" },
    { key: "short_legs_enabled", label: "Short legs" },
    { key: "tick_interval_s", label: "Tick interval (s)" },
    { key: "shadow_seed_balance_usd", label: "Shadow seed ($)" },
    { key: "long_min_edge", label: "Long min edge" },
    { key: "short_min_edge", label: "Short min edge" },
    { key: "shadow_sl_pct", label: "Shadow SL (%)" },
    { key: "shadow_tp_pct", label: "Shadow TP (%)" },
    { key: "funding_exit_pct", label: "Funding exit (%)" },
  ];

  return (
    <div>
      <div className="flex items-center justify-between mb-3">
        <SectionLabel>Strategy Config</SectionLabel>
        <button
          onClick={() => setExpanded(!expanded)}
          className="text-[11px] px-3 py-1 rounded transition-all"
          style={{
            color: t.colors.textMuted,
            border: `1px solid ${t.colors.border}`,
          }}
        >
          {expanded ? "Collapse" : "Show full config"}
        </button>
      </div>

      <div
        className="rounded-lg overflow-hidden"
        style={{ background: t.colors.surface, border: `1px solid ${t.colors.border}` }}
      >
        {/* Key params grid */}
        <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-5 gap-0">
          {keyFields.map((f, i) => {
            const raw = cfg[f.key];
            const val =
              raw === undefined
                ? "—"
                : typeof raw === "boolean"
                ? raw
                  ? "true"
                  : "false"
                : String(raw);
            return (
              <div
                key={f.key}
                className="p-3"
                style={{
                  borderRight: (i + 1) % 5 !== 0 ? `1px solid ${t.colors.borderLight}` : "none",
                  borderBottom: i < keyFields.length - 5 ? `1px solid ${t.colors.borderLight}` : "none",
                }}
              >
                <p className="text-[10px] uppercase tracking-wider mb-1" style={{ color: t.colors.textDim }}>
                  {f.label}
                </p>
                <p
                  className="text-[13px] font-semibold"
                  style={{
                    color:
                      val === "true"
                        ? t.colors.success
                        : val === "false"
                        ? t.colors.danger
                        : t.colors.text,
                    fontFamily: t.fonts.mono,
                  }}
                >
                  {val}
                </p>
              </div>
            );
          })}
        </div>

        {/* Full JSON */}
        {expanded && (
          <div style={{ borderTop: `1px solid ${t.colors.borderLight}` }}>
            <pre
              className="p-4 text-[11px] leading-5 overflow-auto max-h-[400px] whitespace-pre-wrap"
              style={{
                color: t.colors.textSecondary,
                fontFamily: t.fonts.mono,
                scrollbarWidth: "thin",
                scrollbarColor: `${t.colors.border} transparent`,
              }}
            >
              {JSON.stringify(cfg, null, 2)}
            </pre>
          </div>
        )}
      </div>
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function StrategiesPage() {
  const { data: strategiesData, loading } = usePolling(getStrategies, 30000);

  const strategies = strategiesData?.strategies || [];
  const oilBot = strategies.find((s) => s.id === "oil_botpattern");

  return (
    <div className="p-8 max-w-[1400px]">
      {/* Page header */}
      <div className="mb-7">
        <h2
          className="text-2xl font-semibold"
          style={{ color: t.colors.text, fontFamily: t.fonts.heading }}
        >
          Strategies
        </h2>
        <p className="text-[13px] mt-1" style={{ color: t.colors.textMuted }}>
          Strategy state, sub-system health, and decision journals
        </p>
      </div>

      {/* Strategy overview cards */}
      <div className="mb-8">
        <SectionLabel>Strategy Overview</SectionLabel>
        {loading && strategies.length === 0 ? (
          <p className="text-[13px]" style={{ color: t.colors.textDim }}>Loading strategies...</p>
        ) : strategies.length === 0 ? (
          <p className="text-[13px]" style={{ color: t.colors.textDim }}>No strategies found.</p>
        ) : (
          <div className="grid grid-cols-1 lg:grid-cols-2 xl:grid-cols-3 gap-4">
            {strategies.map((s) => (
              <StrategyCard key={s.id} strategy={s} />
            ))}
          </div>
        )}
      </div>

      {/* Oil Bot Pattern detail */}
      {oilBot && (
        <div className="space-y-8">
          {/* Divider */}
          <div
            className="flex items-center gap-4"
            style={{ borderTop: `1px solid ${t.colors.borderLight}`, paddingTop: "2rem" }}
          >
            <h3
              className="text-[18px] font-semibold whitespace-nowrap"
              style={{ color: t.colors.text, fontFamily: t.fonts.heading }}
            >
              Oil Bot Pattern
            </h3>
            <div className="flex-1" style={{ borderTop: `1px solid ${t.colors.borderLight}` }} />
          </div>

          {/* Sub-system grid */}
          <div>
            <SectionLabel>Sub-system Health</SectionLabel>
            <SubSystemGrid subsystems={oilBot.sub_systems} />
          </div>

          {/* PnL state */}
          <div>
            <SectionLabel>Runtime State</SectionLabel>
            <StatePanel />
          </div>

          {/* Decision journal */}
          <JournalSection />

          {/* Config */}
          <ConfigSection />
        </div>
      )}
    </div>
  );
}
