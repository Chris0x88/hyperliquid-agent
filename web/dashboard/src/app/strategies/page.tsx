"use client";

import { useState, useCallback } from "react";
import { usePolling } from "@/lib/hooks";
import {
  getStrategyRegistry,
  getOilBotDetail,
  getOilBotActivity,
  getLabStatus,
  runLabBacktest,
  type RegistryEntry,
  type SubSystemDetail,
  type Sub6Layer,
  type ActivityItem,
  type LabArchetype,
  type LabExperiment,
  type BacktestResult,
} from "@/lib/api";
import { theme as t } from "@/lib/theme";

// ── Utilities ─────────────────────────────────────────────────────────────────

function fmt(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString("en-AU", {
      month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
      timeZone: "Australia/Brisbane",
    });
  } catch { return iso; }
}

function fmtPnl(v: number | null | undefined, dash = true): string {
  if (v == null) return dash ? "—" : "$0.00";
  const sign = v >= 0 ? "+" : "";
  return `${sign}$${Math.abs(v).toFixed(2)}`;
}

function fmtPct(v: number | null | undefined): string {
  if (v == null) return "—";
  const sign = v >= 0 ? "+" : "";
  return `${sign}${(v * 100).toFixed(1)}%`;
}

function pnlColor(v: number | null | undefined): string {
  if (v == null) return t.colors.textDim;
  return v >= 0 ? t.colors.success : t.colors.danger;
}

// ── Design primitives ─────────────────────────────────────────────────────────

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <h3 className="text-[11px] font-semibold uppercase tracking-widest mb-3"
      style={{ color: t.colors.textMuted, fontFamily: t.fonts.heading }}>
      {children}
    </h3>
  );
}

function Badge({
  label, color, bg, border,
}: { label: string; color: string; bg: string; border: string }) {
  return (
    <span className="inline-flex items-center text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-full"
      style={{ color, background: bg, border: `1px solid ${border}` }}>
      {label}
    </span>
  );
}

const STATUS_BADGE: Record<string, { color: string; bg: string; border: string }> = {
  LIVE:    { color: t.colors.success, bg: t.colors.successLight, border: t.colors.successBorder },
  SHADOW:  { color: t.colors.warning, bg: t.colors.warningLight, border: t.colors.warningBorder },
  PAUSED:  { color: t.colors.textMuted, bg: t.colors.neutralLight, border: t.colors.border },
  DORMANT: { color: t.colors.textDim, bg: "transparent", border: t.colors.borderLight },
};

function StatusBadge({ status }: { status: string }) {
  const s = STATUS_BADGE[status] || STATUS_BADGE.DORMANT;
  return <Badge label={status} {...s} />;
}

function Card({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return (
    <div className={`rounded-xl ${className}`}
      style={{ background: t.colors.surface, border: `1px solid ${t.colors.border}` }}>
      {children}
    </div>
  );
}

function Dot({ on, warn = false }: { on: boolean; warn?: boolean }) {
  const color = on ? (warn ? t.colors.warning : t.colors.success) : t.colors.textDim;
  return (
    <span className="inline-block w-2 h-2 rounded-full flex-shrink-0"
      style={{ background: color, boxShadow: on ? `0 0 6px ${color}` : "none" }} />
  );
}

function Spinner() {
  return (
    <div className="flex items-center gap-2">
      <div className="w-3 h-3 rounded-full border-2 animate-spin"
        style={{ borderColor: `${t.colors.textDim} transparent transparent transparent` }} />
      <span className="text-[12px]" style={{ color: t.colors.textDim }}>Loading…</span>
    </div>
  );
}

// ── Tab navigation ────────────────────────────────────────────────────────────

type Tab = "overview" | "detail" | "lab";

function TabBar({ active, onChange }: { active: Tab; onChange: (t: Tab) => void }) {
  const tabs: { id: Tab; label: string }[] = [
    { id: "overview", label: "Strategy Overview" },
    { id: "detail",   label: "Oil Bot Pattern" },
    { id: "lab",      label: "Lab Engine" },
  ];
  return (
    <div className="flex gap-1 mb-8 border-b" style={{ borderColor: t.colors.borderLight }}>
      {tabs.map((tab) => (
        <button key={tab.id} onClick={() => onChange(tab.id)}
          className="px-4 py-2.5 text-[13px] font-medium transition-all relative"
          style={{
            color: active === tab.id ? t.colors.text : t.colors.textMuted,
            fontFamily: t.fonts.heading,
          }}>
          {tab.label}
          {active === tab.id && (
            <span className="absolute bottom-0 left-0 right-0 h-[2px] rounded-t"
              style={{ background: t.colors.primary }} />
          )}
        </button>
      ))}
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// TAB 1 — STRATEGY OVERVIEW (Registry)
// ═══════════════════════════════════════════════════════════════════════════════

function RegistryCard({ entry, onDrillDown }: {
  entry: RegistryEntry;
  onDrillDown?: () => void;
}) {
  const isOilBot = entry.id === "oil_botpattern";
  const hasShadowData = (entry.shadow_trades ?? 0) > 0;

  return (
    <Card className="p-4 flex flex-col gap-3">
      {/* Header */}
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap mb-1">
            <StatusBadge status={entry.status} />
            {entry.simulate && (
              <Badge label="simulate" color={t.colors.warning}
                bg={t.colors.warningLight} border={t.colors.warningBorder} />
            )}
          </div>
          <h3 className="text-[15px] font-semibold mt-1"
            style={{ color: t.colors.text, fontFamily: t.fonts.heading }}>
            {entry.name}
          </h3>
          <p className="text-[11px] mt-0.5" style={{ color: t.colors.textMuted }}>
            {(entry.markets || []).join(" · ")}
          </p>
        </div>
      </div>

      {/* Purpose */}
      <p className="text-[12px] leading-relaxed" style={{ color: t.colors.textSecondary }}>
        {entry.purpose}
      </p>

      {/* Shadow PnL row — only for entries with shadow data */}
      {isOilBot && (
        <div className="flex items-center justify-between pt-2 mt-auto"
          style={{ borderTop: `1px solid ${t.colors.borderLight}` }}>
          <div className="flex items-center gap-4">
            <div>
              <p className="text-[9px] uppercase tracking-wider" style={{ color: t.colors.textDim }}>Shadow PnL</p>
              <p className="text-[13px] font-semibold font-mono mt-0.5"
                style={{ color: pnlColor(entry.shadow_pnl_usd), fontFamily: t.fonts.mono }}>
                {fmtPnl(entry.shadow_pnl_usd)}
              </p>
            </div>
            {hasShadowData && (
              <div>
                <p className="text-[9px] uppercase tracking-wider" style={{ color: t.colors.textDim }}>Trades</p>
                <p className="text-[13px] font-semibold font-mono mt-0.5"
                  style={{ color: t.colors.text, fontFamily: t.fonts.mono }}>
                  {entry.shadow_trades ?? 0}
                </p>
              </div>
            )}
            {hasShadowData && entry.shadow_win_rate != null && (
              <div>
                <p className="text-[9px] uppercase tracking-wider" style={{ color: t.colors.textDim }}>Win rate</p>
                <p className="text-[13px] font-semibold font-mono mt-0.5"
                  style={{ color: t.colors.text, fontFamily: t.fonts.mono }}>
                  {(entry.shadow_win_rate * 100).toFixed(0)}%
                </p>
              </div>
            )}
          </div>
          {entry.last_activity && (
            <p className="text-[10px]" style={{ color: t.colors.textDim }}>
              Last: {fmt(entry.last_activity)}
            </p>
          )}
        </div>
      )}

      {/* Drill-down CTA */}
      {onDrillDown && (
        <button onClick={onDrillDown}
          className="w-full text-[12px] font-medium py-1.5 rounded-lg transition-all"
          style={{
            background: t.colors.primaryLight,
            color: t.colors.primary,
            border: `1px solid ${t.colors.primaryBorder}`,
          }}>
          View detail →
        </button>
      )}
    </Card>
  );
}

function DormantCard({ entry }: { entry: RegistryEntry }) {
  const [expanded, setExpanded] = useState(false);
  return (
    <div className="flex items-start gap-3 py-2.5 px-3 rounded-lg transition-all cursor-pointer"
      style={{ border: `1px solid ${t.colors.borderLight}` }}
      onClick={() => setExpanded(!expanded)}>
      <StatusBadge status="DORMANT" />
      <div className="flex-1 min-w-0">
        <div className="flex items-center justify-between">
          <p className="text-[13px] font-medium" style={{ color: t.colors.textSecondary }}>
            {entry.name}
          </p>
          <p className="text-[10px]" style={{ color: t.colors.textDim }}>
            {(entry.markets || []).join(" · ")}
          </p>
        </div>
        {expanded && (
          <p className="text-[11px] mt-1 leading-relaxed" style={{ color: t.colors.textDim }}>
            {entry.purpose}
          </p>
        )}
      </div>
    </div>
  );
}

function OverviewTab({ onDrillDown }: { onDrillDown: () => void }) {
  const { data, loading, error } = usePolling(getStrategyRegistry, 30000);

  if (loading && !data) return <Spinner />;
  if (error) return <p className="text-[13px]" style={{ color: t.colors.danger }}>Error: {error}</p>;
  if (!data) return null;

  return (
    <div className="space-y-8">
      {/* LIVE / SHADOW */}
      {data.live.length > 0 && (
        <div>
          <SectionLabel>
            Active — {data.counts.live} {data.counts.live === 1 ? "strategy" : "strategies"} running
          </SectionLabel>
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
            {data.live.map((e) => (
              <RegistryCard key={e.id} entry={e}
                onDrillDown={e.id === "oil_botpattern" ? onDrillDown : undefined} />
            ))}
          </div>
        </div>
      )}

      {/* PARKED */}
      {data.parked.length > 0 && (
        <div>
          <SectionLabel>
            Parked — {data.counts.parked} registered, kill-switched or simulate=true
          </SectionLabel>
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
            {data.parked.map((e) => (
              <RegistryCard key={e.id} entry={e} />
            ))}
          </div>
        </div>
      )}

      {/* LIBRARY */}
      {data.library.length > 0 && (
        <div>
          <SectionLabel>
            Library — {data.counts.library} dormant strategies (code exists, not in roster)
          </SectionLabel>
          <p className="text-[12px] mb-3" style={{ color: t.colors.textDim }}>
            These strategies are implemented but not registered with the daemon. Click any to see what it does.
          </p>
          <div className="space-y-1.5">
            {data.library.map((e) => (
              <DormantCard key={e.id} entry={e} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// TAB 2 — OIL BOT PATTERN DETAIL
// ═══════════════════════════════════════════════════════════════════════════════

function SubSystemCard({ ss, index }: { ss: SubSystemDetail; index: number }) {
  const [expanded, setExpanded] = useState(false);
  return (
    <Card className="p-4">
      <div className="flex items-start gap-3">
        {/* Number badge */}
        <div className="w-7 h-7 rounded-lg flex items-center justify-center flex-shrink-0 text-[12px] font-bold"
          style={{
            background: ss.enabled ? t.colors.primaryLight : t.colors.neutralLight,
            color: ss.enabled ? t.colors.primary : t.colors.textDim,
            border: `1px solid ${ss.enabled ? t.colors.primaryBorder : t.colors.border}`,
          }}>
          {index + 1}
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <Dot on={ss.enabled} />
            <span className="text-[14px] font-semibold"
              style={{ color: t.colors.text, fontFamily: t.fonts.heading }}>
              {ss.label}
            </span>
            <span className="text-[10px] font-medium ml-auto"
              style={{ color: ss.enabled ? t.colors.success : t.colors.textDim }}>
              {ss.enabled ? "Enabled" : "Disabled"}
            </span>
          </div>
          <p className="text-[12px] leading-relaxed" style={{ color: t.colors.textSecondary }}>
            {ss.description}
          </p>

          {/* Data flow — collapsible */}
          {expanded && (
            <div className="mt-3 grid grid-cols-2 gap-3">
              <div className="rounded-lg p-3" style={{ background: t.colors.bg }}>
                <p className="text-[9px] uppercase tracking-wider mb-1.5" style={{ color: t.colors.textDim }}>Data In</p>
                {ss.data_in.map((d) => (
                  <p key={d} className="text-[11px]" style={{ color: t.colors.textSecondary }}>→ {d}</p>
                ))}
              </div>
              <div className="rounded-lg p-3" style={{ background: t.colors.bg }}>
                <p className="text-[9px] uppercase tracking-wider mb-1.5" style={{ color: t.colors.textDim }}>Data Out</p>
                {ss.data_out.map((d) => (
                  <p key={d} className="text-[11px]" style={{ color: t.colors.textSecondary }}>← {d}</p>
                ))}
              </div>
            </div>
          )}

          <button onClick={() => setExpanded(!expanded)}
            className="mt-2 text-[11px] transition-colors"
            style={{ color: t.colors.textDim }}>
            {expanded ? "▲ Hide data flow" : "▼ Show data flow"}
          </button>
        </div>
      </div>
    </Card>
  );
}

function Sub6Stepper({ layers }: { layers: Sub6Layer[] }) {
  return (
    <div className="space-y-3">
      {layers.map((layer, i) => {
        const isActive = layer.enabled;
        return (
          <div key={layer.id} className="flex gap-4">
            {/* Vertical connector */}
            <div className="flex flex-col items-center">
              <div className="w-8 h-8 rounded-full flex items-center justify-center text-[11px] font-bold flex-shrink-0"
                style={{
                  background: isActive ? t.colors.successLight : t.colors.neutralLight,
                  border: `2px solid ${isActive ? t.colors.successBorder : t.colors.border}`,
                  color: isActive ? t.colors.success : t.colors.textDim,
                }}>
                {layer.id}
              </div>
              {i < layers.length - 1 && (
                <div className="w-px flex-1 mt-1" style={{
                  background: isActive ? t.colors.successBorder : t.colors.borderLight,
                  minHeight: "16px",
                }} />
              )}
            </div>
            {/* Content */}
            <Card className="p-4 flex-1 mb-3">
              <div className="flex items-center gap-2 mb-2">
                <span className="text-[14px] font-semibold"
                  style={{ color: t.colors.text, fontFamily: t.fonts.heading }}>
                  {layer.name}
                </span>
                <span className="ml-auto text-[10px] font-semibold px-2 py-0.5 rounded-full"
                  style={{
                    background: isActive ? t.colors.successLight : t.colors.neutralLight,
                    color: isActive ? t.colors.success : t.colors.textDim,
                    border: `1px solid ${isActive ? t.colors.successBorder : t.colors.border}`,
                  }}>
                  {isActive ? "ON" : "OFF"}
                </span>
              </div>
              <p className="text-[12px] leading-relaxed mb-2" style={{ color: t.colors.textSecondary }}>
                {layer.description}
              </p>
              <div className="grid grid-cols-2 gap-3 mt-3">
                <div className="rounded-lg p-2" style={{ background: t.colors.bg }}>
                  <p className="text-[9px] uppercase tracking-wider mb-1" style={{ color: t.colors.textDim }}>Produces</p>
                  <p className="text-[11px]" style={{ color: t.colors.textSecondary }}>{layer.what_it_produces}</p>
                </div>
                <div className="rounded-lg p-2" style={{ background: t.colors.bg }}>
                  <p className="text-[9px] uppercase tracking-wider mb-1" style={{ color: t.colors.textDim }}>Safe to enable when</p>
                  <p className="text-[11px]" style={{ color: t.colors.textSecondary }}>{layer.safe_to_enable}</p>
                </div>
              </div>
              {!isActive && !layer.has_config && (
                <p className="text-[10px] mt-2" style={{ color: t.colors.textDim }}>
                  No config file — enable via Control page.
                </p>
              )}
            </Card>
          </div>
        );
      })}
    </div>
  );
}

function ShadowBalancePanel({ balance, positionCount }: {
  balance: {
    seed_balance_usd: number;
    current_balance_usd: number;
    realised_pnl_usd: number;
    pnl_pct: number;
    win_rate: number;
    closed_trades: number;
    wins: number;
    losses: number;
    last_updated_at: string | null;
  } | null;
  positionCount: number;
}) {
  if (!balance) {
    return (
      <div className="rounded-lg p-6 text-center"
        style={{ background: t.colors.surface, border: `1px solid ${t.colors.border}` }}>
        <p className="text-[13px] mb-2" style={{ color: t.colors.textSecondary }}>
          No shadow balance data yet.
        </p>
        <p className="text-[12px]" style={{ color: t.colors.textDim }}>
          Shadow trading records appear once the strategy engine (SS-5) runs with{" "}
          <code className="font-mono text-[11px]" style={{ color: t.colors.primary }}>decisions_only=true</code>.
        </p>
      </div>
    );
  }

  const seed = balance.seed_balance_usd ?? 100_000;
  const current = balance.current_balance_usd ?? seed;
  const pnl = balance.realised_pnl_usd ?? 0;
  const hasTrades = (balance.closed_trades ?? 0) > 0;

  const stats = [
    { label: "Seed Balance",  value: `$${seed.toLocaleString("en", { maximumFractionDigits: 0 })}`, color: t.colors.textSecondary },
    { label: "Current Balance", value: `$${current.toLocaleString("en", { maximumFractionDigits: 2 })}`, color: t.colors.text },
    { label: "Shadow PnL",   value: fmtPnl(pnl), color: pnlColor(pnl) },
    { label: "Return",       value: hasTrades ? fmtPct(balance.pnl_pct) : "—", color: pnlColor(balance.pnl_pct) },
    { label: "Closed Trades", value: hasTrades ? String(balance.closed_trades) : "—", color: t.colors.text },
    { label: "Win / Loss",   value: hasTrades ? `${balance.wins}W / ${balance.losses}L` : "—", color: t.colors.text },
    { label: "Win Rate",     value: hasTrades ? `${(balance.win_rate * 100).toFixed(0)}%` : "—", color: t.colors.text },
    { label: "Open Positions", value: String(positionCount), color: t.colors.text },
  ];

  return (
    <div>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-3">
        {stats.map((s) => (
          <div key={s.label} className="rounded-lg p-3"
            style={{ background: t.colors.surface, border: `1px solid ${t.colors.border}` }}>
            <p className="text-[9px] uppercase tracking-wider mb-1" style={{ color: t.colors.textDim }}>{s.label}</p>
            <p className="text-[14px] font-semibold font-mono"
              style={{ color: s.color, fontFamily: t.fonts.mono }}>{s.value}</p>
          </div>
        ))}
      </div>
      {!hasTrades && (
        <div className="rounded-lg p-4" style={{ background: t.colors.bg, border: `1px solid ${t.colors.borderLight}` }}>
          <p className="text-[12px]" style={{ color: t.colors.textSecondary }}>
            <strong style={{ color: t.colors.warning }}>No closed shadow trades yet.</strong>{" "}
            The shadow balance is seeded at ${seed.toLocaleString()} and will accumulate P&amp;L as the strategy engine
            runs in <code className="font-mono" style={{ color: t.colors.primary }}>decisions_only=true</code> mode and virtual positions close.
          </p>
        </div>
      )}
      {balance.last_updated_at && (
        <p className="text-[10px] mt-2" style={{ color: t.colors.textDim }}>
          Last updated: {fmt(balance.last_updated_at)}
        </p>
      )}
    </div>
  );
}

function ActivityFeed({ items }: { items: ActivityItem[] }) {
  if (items.length === 0) {
    return (
      <div className="rounded-lg p-8 text-center"
        style={{ background: t.colors.surface, border: `1px solid ${t.colors.border}` }}>
        <p className="text-[13px] mb-2" style={{ color: t.colors.textSecondary }}>No activity yet.</p>
        <p className="text-[12px]" style={{ color: t.colors.textDim }}>
          Turn on <code className="font-mono" style={{ color: t.colors.primary }}>decisions_only=true</code>{" "}
          in the Control page to start logging shadow decisions.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {items.map((item, i) => {
        const isTrade = item.type === "shadow_trade";
        const actionColor = item.action === "hold" ? t.colors.textDim
          : item.action === "scale_out" ? t.colors.tertiary
          : item.action === "sl_hit" ? t.colors.danger
          : item.action === "tp_hit" ? t.colors.success
          : t.colors.textSecondary;

        return (
          <div key={i} className="flex items-start gap-3 rounded-lg p-3"
            style={{
              background: isTrade ? t.colors.bg : "transparent",
              border: `1px solid ${isTrade ? t.colors.border : t.colors.borderLight}`,
            }}>
            {/* Type indicator */}
            <div className="w-1.5 h-1.5 rounded-full mt-1.5 flex-shrink-0"
              style={{ background: isTrade ? t.colors.tertiary : t.colors.textDim }} />

            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 flex-wrap">
                <span className="text-[11px] font-medium"
                  style={{ color: t.colors.text, fontFamily: t.fonts.heading }}>
                  {item.instrument || "—"}
                </span>
                <span className="text-[10px] font-bold uppercase"
                  style={{ color: actionColor }}>{item.action || "—"}</span>
                {isTrade && item.pnl_usd != null && (
                  <span className="text-[10px] font-mono font-semibold"
                    style={{ color: pnlColor(item.pnl_usd), fontFamily: t.fonts.mono }}>
                    {fmtPnl(item.pnl_usd)}
                  </span>
                )}
                {isTrade && item.roe_pct != null && (
                  <span className="text-[10px]" style={{ color: t.colors.textDim }}>
                    ({(item.roe_pct).toFixed(1)}% ROE)
                  </span>
                )}
                <span className="ml-auto text-[10px]" style={{ color: t.colors.textDim }}>
                  {fmt(item.ts)}
                </span>
              </div>
              {item.reason && (
                <p className="text-[11px] mt-0.5 truncate" style={{ color: t.colors.textSecondary }}>
                  {item.reason}
                </p>
              )}
              {isTrade && item.hold_hours != null && (
                <p className="text-[10px] mt-0.5" style={{ color: t.colors.textDim }}>
                  Held {item.hold_hours.toFixed(1)}h
                  {item.edge != null ? ` · Edge ${item.edge.toFixed(2)}` : ""}
                </p>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function DetailTab() {
  const { data: detail, loading: detailLoading } = usePolling(getOilBotDetail, 30000);
  const [activityLimit, setActivityLimit] = useState(20);
  const [section, setSection] = useState<"subsystems" | "shadow" | "self6" | "activity" | "config">("subsystems");

  const { data: activity, loading: actLoading } = usePolling(
    () => getOilBotActivity(activityLimit), 20000
  );

  if (detailLoading && !detail) return <Spinner />;

  const sections = [
    { id: "subsystems" as const, label: "Sub-systems" },
    { id: "shadow" as const,    label: "Shadow P&L" },
    { id: "self6" as const,     label: "Self-Improvement (L1-L4)" },
    { id: "activity" as const,  label: "Activity Feed" },
    { id: "config" as const,    label: "Config" },
  ];

  return (
    <div>
      {/* Hero */}
      <div className="rounded-xl p-5 mb-6"
        style={{ background: t.colors.surface, border: `1px solid ${t.colors.border}` }}>
        <div className="flex items-start gap-4">
          <div className="flex-1">
            <div className="flex items-center gap-3 flex-wrap mb-2">
              <StatusBadge status="SHADOW" />
              <span className="text-[11px]" style={{ color: t.colors.textDim }}>
                decisions_only=true — no real orders placed
              </span>
            </div>
            <h2 className="text-[20px] font-semibold mb-1"
              style={{ color: t.colors.text, fontFamily: t.fonts.heading }}>
              Oil Bot Pattern
            </h2>
            <p className="text-[13px]" style={{ color: t.colors.textSecondary }}>
              Multi-subsystem oil trading strategy. Classifies bot vs informed moves using a 6-sub-system
              pipeline — news ingestion, supply ledger, order-book heatmap, bot classifier, strategy engine,
              and self-improvement harness. Currently runs all decision logic in shadow mode and logs
              everything to the adaptive log for review.
            </p>
            <p className="text-[12px] mt-2" style={{ color: t.colors.textDim }}>
              Markets: {(detail?.config?.instruments as string[] | undefined)?.join(", ") || "BRENTOIL, CL"}
            </p>
          </div>
        </div>
      </div>

      {/* Inner tab bar */}
      <div className="flex gap-1 mb-6 overflow-x-auto"
        style={{ borderBottom: `1px solid ${t.colors.borderLight}` }}>
        {sections.map((s) => (
          <button key={s.id} onClick={() => setSection(s.id)}
            className="px-3 py-2 text-[12px] font-medium whitespace-nowrap transition-all relative flex-shrink-0"
            style={{ color: section === s.id ? t.colors.text : t.colors.textMuted }}>
            {s.label}
            {section === s.id && (
              <span className="absolute bottom-0 left-0 right-0 h-[2px] rounded-t"
                style={{ background: t.colors.primary }} />
            )}
          </button>
        ))}
      </div>

      {/* SUB-SYSTEMS */}
      {section === "subsystems" && detail && (
        <div className="space-y-3">
          <p className="text-[12px] mb-4" style={{ color: t.colors.textSecondary }}>
            Sub-systems build on each other — SS-1 through SS-4 feed data into SS-5 (the strategy engine).
            SS-6 is the self-improvement harness. Toggling kill switches is done on the Control page.
          </p>
          {detail.sub_systems.map((ss, i) => (
            <SubSystemCard key={ss.id} ss={ss} index={i} />
          ))}
        </div>
      )}

      {/* SHADOW P&L */}
      {section === "shadow" && (
        <div className="space-y-6">
          <SectionLabel>Shadow Balance</SectionLabel>
          <ShadowBalancePanel
            balance={detail?.shadow_balance ?? null}
            positionCount={detail?.shadow_positions?.length ?? 0}
          />

          {detail?.recent_shadow_trades && detail.recent_shadow_trades.length > 0 && (
            <>
              <SectionLabel>Shadow Trade Log</SectionLabel>
              <Card className="overflow-hidden">
                {/* Header row */}
                <div className="grid gap-2 px-4 py-2"
                  style={{
                    gridTemplateColumns: "120px 60px 80px 80px 80px 80px 90px",
                    borderBottom: `1px solid ${t.colors.borderLight}`,
                  }}>
                  {["Time", "Side", "Entry", "Exit", "PnL", "ROE", "Reason"].map((h) => (
                    <span key={h} className="text-[9px] font-bold uppercase tracking-wider"
                      style={{ color: t.colors.textDim }}>{h}</span>
                  ))}
                </div>
                {detail.recent_shadow_trades.map((trade, i) => (
                  <div key={i} className="grid gap-2 px-4 py-2.5 items-center"
                    style={{
                      gridTemplateColumns: "120px 60px 80px 80px 80px 80px 90px",
                      borderBottom: i < detail.recent_shadow_trades.length - 1
                        ? `1px solid ${t.colors.borderLight}` : "none",
                    }}>
                    <span className="text-[10px]" style={{ color: t.colors.textDim, fontFamily: t.fonts.mono }}>
                      {fmt(trade.exit_ts)}
                    </span>
                    <span className="text-[11px] font-medium"
                      style={{ color: trade.side === "long" ? t.colors.success : t.colors.danger }}>
                      {trade.side}
                    </span>
                    <span className="text-[11px] font-mono" style={{ color: t.colors.textSecondary, fontFamily: t.fonts.mono }}>
                      ${trade.entry_price?.toFixed(2) ?? "—"}
                    </span>
                    <span className="text-[11px] font-mono" style={{ color: t.colors.textSecondary, fontFamily: t.fonts.mono }}>
                      ${trade.exit_price?.toFixed(2) ?? "—"}
                    </span>
                    <span className="text-[11px] font-semibold font-mono"
                      style={{ color: pnlColor(trade.pnl_usd), fontFamily: t.fonts.mono }}>
                      {fmtPnl(trade.pnl_usd)}
                    </span>
                    <span className="text-[11px] font-mono"
                      style={{ color: pnlColor(trade.roe_pct ? trade.roe_pct / 100 : null), fontFamily: t.fonts.mono }}>
                      {trade.roe_pct != null ? `${trade.roe_pct.toFixed(1)}%` : "—"}
                    </span>
                    <span className="text-[10px] uppercase font-medium"
                      style={{ color: trade.exit_reason === "sl_hit" ? t.colors.danger : t.colors.success }}>
                      {trade.exit_reason?.replace("_", " ") ?? "—"}
                    </span>
                  </div>
                ))}
              </Card>
            </>
          )}
        </div>
      )}

      {/* SELF-IMPROVEMENT */}
      {section === "self6" && detail && (
        <div>
          <p className="text-[12px] mb-6" style={{ color: t.colors.textSecondary }}>
            The self-improvement harness has 4 layers that activate in sequence. L3 (Pattern Library) is
            already on. L1 and L2 activate after more shadow trade history. L4 activates after L2 produces
            approved proposals. None of these layers place real orders — they tune parameters and grow the
            pattern library only.
          </p>
          <Sub6Stepper layers={detail.sub6_layers} />
          {detail.patternlib_state && Object.keys(detail.patternlib_state).length > 0 && (
            <div className="mt-4">
              <SectionLabel>Pattern Library State</SectionLabel>
              <div className="grid grid-cols-2 gap-3">
                {detail.patternlib_state.last_run_at != null && (
                  <div className="rounded-lg p-3" style={{ background: t.colors.surface, border: `1px solid ${t.colors.border}` }}>
                    <p className="text-[9px] uppercase tracking-wider mb-1" style={{ color: t.colors.textDim }}>Last Run</p>
                    <p className="text-[13px] font-mono" style={{ color: t.colors.text, fontFamily: t.fonts.mono }}>
                      {fmt(String(detail.patternlib_state.last_run_at))}
                    </p>
                  </div>
                )}
                {detail.patternlib_state.last_candidate_id != null && (
                  <div className="rounded-lg p-3" style={{ background: t.colors.surface, border: `1px solid ${t.colors.border}` }}>
                    <p className="text-[9px] uppercase tracking-wider mb-1" style={{ color: t.colors.textDim }}>Candidates Written</p>
                    <p className="text-[13px] font-semibold font-mono" style={{ color: t.colors.text, fontFamily: t.fonts.mono }}>
                      {String(detail.patternlib_state.last_candidate_id)}
                    </p>
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      )}

      {/* ACTIVITY FEED */}
      {section === "activity" && (
        <div>
          <div className="flex items-center justify-between mb-4">
            <SectionLabel>Recent Decisions & Shadow Trades</SectionLabel>
            <div className="flex gap-1">
              {[20, 50, 100].map((n) => (
                <button key={n} onClick={() => setActivityLimit(n)}
                  className="px-2.5 py-1 rounded text-[11px] font-medium transition-all"
                  style={activityLimit === n
                    ? { background: t.colors.primaryLight, color: t.colors.primary, border: `1px solid ${t.colors.primaryBorder}` }
                    : { color: t.colors.textDim, border: `1px solid ${t.colors.border}` }}>
                  {n}
                </button>
              ))}
            </div>
          </div>
          {actLoading && !activity ? <Spinner /> : (
            <ActivityFeed items={activity?.activity || []} />
          )}
        </div>
      )}

      {/* CONFIG */}
      {section === "config" && detail && (
        <ConfigViewer config={detail.config} />
      )}
    </div>
  );
}

function ConfigViewer({ config }: { config: Record<string, unknown> }) {
  const [expanded, setExpanded] = useState(false);

  const keyFields = [
    { key: "enabled",              label: "Enabled" },
    { key: "decisions_only",       label: "Shadow Mode" },
    { key: "short_legs_enabled",   label: "Short Legs" },
    { key: "tick_interval_s",      label: "Tick (s)" },
    { key: "shadow_seed_balance_usd", label: "Seed ($)" },
    { key: "long_min_edge",        label: "Long Min Edge" },
    { key: "short_min_edge",       label: "Short Min Edge" },
    { key: "shadow_sl_pct",        label: "Shadow SL%" },
    { key: "shadow_tp_pct",        label: "Shadow TP%" },
    { key: "funding_exit_pct",     label: "Funding Exit%" },
  ];

  return (
    <div>
      <div className="flex items-center justify-between mb-3">
        <SectionLabel>Strategy Config</SectionLabel>
        <button onClick={() => setExpanded(!expanded)}
          className="text-[11px] px-3 py-1 rounded transition-all"
          style={{ color: t.colors.textMuted, border: `1px solid ${t.colors.border}` }}>
          {expanded ? "Collapse" : "Show full JSON"}
        </button>
      </div>

      <Card className="overflow-hidden">
        <div className="grid grid-cols-2 sm:grid-cols-3 xl:grid-cols-5">
          {keyFields.map((f, i) => {
            const raw = config[f.key];
            const val = raw === undefined ? "—"
              : typeof raw === "boolean" ? (raw ? "true" : "false")
              : String(raw);
            const isTrue = val === "true";
            const isFalse = val === "false";
            return (
              <div key={f.key} className="p-3"
                style={{
                  borderRight: (i + 1) % 5 !== 0 ? `1px solid ${t.colors.borderLight}` : "none",
                  borderBottom: i < keyFields.length - 5 ? `1px solid ${t.colors.borderLight}` : "none",
                }}>
                <p className="text-[9px] uppercase tracking-wider mb-1" style={{ color: t.colors.textDim }}>
                  {f.label}
                </p>
                <p className="text-[13px] font-semibold font-mono"
                  style={{
                    color: isTrue ? t.colors.success : isFalse ? t.colors.danger : t.colors.text,
                    fontFamily: t.fonts.mono,
                  }}>
                  {val}
                </p>
              </div>
            );
          })}
        </div>
        {expanded && (
          <div style={{ borderTop: `1px solid ${t.colors.borderLight}` }}>
            <pre className="p-4 text-[11px] leading-5 overflow-auto max-h-[400px] whitespace-pre-wrap"
              style={{
                color: t.colors.textSecondary,
                fontFamily: t.fonts.mono,
                scrollbarWidth: "thin",
                scrollbarColor: `${t.colors.border} transparent`,
              }}>
              {JSON.stringify(config, null, 2)}
            </pre>
          </div>
        )}
      </Card>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// TAB 3 — LAB ENGINE
// ═══════════════════════════════════════════════════════════════════════════════

const KANBAN_COLUMNS = [
  { id: "hypothesis",    label: "Hypothesis",    desc: "Experiment created, awaiting backtest" },
  { id: "backtesting",   label: "Backtesting",   desc: "Running historical simulation" },
  { id: "paper_trading", label: "Paper Trading", desc: "Live paper trade validation" },
  { id: "graduated",     label: "Graduated",     desc: "Passed all graduation thresholds" },
  { id: "production",    label: "Production",    desc: "Running in production" },
  { id: "retired",       label: "Retired",       desc: "Experiment archived" },
];

function ExperimentCard({ exp }: { exp: LabExperiment }) {
  const metrics = exp.backtest_metrics || exp.paper_metrics || {};
  const hasMets = Object.keys(metrics).length > 0;

  return (
    <div className="rounded-lg p-3 mb-2"
      style={{ background: t.colors.bg, border: `1px solid ${t.colors.border}` }}>
      <div className="flex items-center gap-2 mb-1">
        <span className="text-[10px] font-mono" style={{ color: t.colors.textDim, fontFamily: t.fonts.mono }}>
          {exp.id}
        </span>
        <span className="text-[11px] font-semibold"
          style={{ color: t.colors.text, fontFamily: t.fonts.heading }}>
          {exp.strategy} / {exp.market}
        </span>
      </div>
      {hasMets && (
        <div className="grid grid-cols-3 gap-1 mt-2">
          {metrics.sharpe != null && (
            <div>
              <p className="text-[8px] uppercase" style={{ color: t.colors.textDim }}>Sharpe</p>
              <p className="text-[11px] font-mono" style={{ color: t.colors.text, fontFamily: t.fonts.mono }}>
                {metrics.sharpe.toFixed(2)}
              </p>
            </div>
          )}
          {metrics.win_rate != null && (
            <div>
              <p className="text-[8px] uppercase" style={{ color: t.colors.textDim }}>Win %</p>
              <p className="text-[11px] font-mono" style={{ color: t.colors.text, fontFamily: t.fonts.mono }}>
                {(metrics.win_rate * 100).toFixed(0)}%
              </p>
            </div>
          )}
          {metrics.max_drawdown != null && (
            <div>
              <p className="text-[8px] uppercase" style={{ color: t.colors.textDim }}>Max DD</p>
              <p className="text-[11px] font-mono" style={{ color: t.colors.danger, fontFamily: t.fonts.mono }}>
                {(metrics.max_drawdown * 100).toFixed(1)}%
              </p>
            </div>
          )}
        </div>
      )}
      {exp.backtest_trades > 0 && (
        <p className="text-[10px] mt-1" style={{ color: t.colors.textDim }}>
          {exp.backtest_trades} backtest trades
        </p>
      )}
    </div>
  );
}

function KanbanBoard({ kanban }: { kanban: Record<string, LabExperiment[]> }) {
  const cols = KANBAN_COLUMNS.filter((c) => {
    const items = kanban[c.id] || [];
    return items.length > 0 || ["hypothesis", "backtesting", "paper_trading", "graduated"].includes(c.id);
  });

  return (
    <div className="grid gap-4" style={{ gridTemplateColumns: `repeat(${cols.length}, minmax(200px, 1fr))` }}>
      {cols.map((col) => {
        const items = kanban[col.id] || [];
        return (
          <div key={col.id}>
            <div className="flex items-center gap-2 mb-3">
              <p className="text-[11px] font-semibold uppercase tracking-wider"
                style={{ color: t.colors.textMuted, fontFamily: t.fonts.heading }}>
                {col.label}
              </p>
              {items.length > 0 && (
                <span className="text-[10px] px-1.5 py-0.5 rounded-full font-bold"
                  style={{ background: t.colors.primaryLight, color: t.colors.primary }}>
                  {items.length}
                </span>
              )}
            </div>
            <div className="rounded-lg min-h-[100px] p-2"
              style={{ background: t.colors.surface, border: `1px solid ${t.colors.border}` }}>
              {items.length === 0 ? (
                <p className="text-[11px] p-2" style={{ color: t.colors.textDim }}>{col.desc}</p>
              ) : (
                items.map((exp) => <ExperimentCard key={exp.id} exp={exp} />)
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function ArchetypeRow({ arch }: { arch: LabArchetype }) {
  return (
    <div className="flex items-start gap-3 p-3 rounded-lg"
      style={{ background: t.colors.bg, border: `1px solid ${t.colors.borderLight}` }}>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 mb-0.5">
          <span className="text-[12px] font-semibold"
            style={{ color: t.colors.text, fontFamily: t.fonts.heading }}>
            {arch.id.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())}
          </span>
          {arch.wired ? (
            <Badge label="Wired" color={t.colors.success} bg={t.colors.successLight} border={t.colors.successBorder} />
          ) : (
            <Badge label="Stub" color={t.colors.textDim} bg={t.colors.neutralLight} border={t.colors.border} />
          )}
        </div>
        <p className="text-[11px]" style={{ color: t.colors.textSecondary }}>{arch.description}</p>
        <p className="text-[10px] mt-1" style={{ color: t.colors.textDim }}>
          Signals: {arch.signals.join(", ")}
        </p>
      </div>
    </div>
  );
}

function BacktestForm({ archetypes, approvedMarkets }: {
  archetypes: LabArchetype[];
  approvedMarkets: string[];
}) {
  const [market, setMarket] = useState("BRENTOIL");
  const [archetype, setArchetype] = useState("momentum_breakout");
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<BacktestResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleRun = useCallback(async () => {
    setRunning(true);
    setResult(null);
    setError(null);
    try {
      const res = await runLabBacktest(market, archetype);
      setResult(res);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unknown error");
    } finally {
      setRunning(false);
    }
  }, [market, archetype]);

  const selectedArch = archetypes.find((a) => a.id === archetype);

  return (
    <Card className="p-5">
      <h3 className="text-[14px] font-semibold mb-4"
        style={{ color: t.colors.text, fontFamily: t.fonts.heading }}>
        Run Backtest
      </h3>
      <div className="grid grid-cols-2 gap-4 mb-4">
        <div>
          <label className="block text-[10px] uppercase tracking-wider mb-1.5"
            style={{ color: t.colors.textDim }}>Market</label>
          <select value={market} onChange={(e) => setMarket(e.target.value)}
            className="w-full px-3 py-2 rounded-lg text-[13px]"
            style={{
              background: t.colors.bg,
              border: `1px solid ${t.colors.border}`,
              color: t.colors.text,
              outline: "none",
            }}>
            {approvedMarkets.map((m) => (
              <option key={m} value={m}>{m}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="block text-[10px] uppercase tracking-wider mb-1.5"
            style={{ color: t.colors.textDim }}>Archetype</label>
          <select value={archetype} onChange={(e) => setArchetype(e.target.value)}
            className="w-full px-3 py-2 rounded-lg text-[13px]"
            style={{
              background: t.colors.bg,
              border: `1px solid ${t.colors.border}`,
              color: t.colors.text,
              outline: "none",
            }}>
            {archetypes.map((a) => (
              <option key={a.id} value={a.id}>
                {a.id.replace(/_/g, " ")} {a.wired ? "" : "(stub — raises error)"}
              </option>
            ))}
          </select>
        </div>
      </div>

      {selectedArch && (
        <div className="rounded-lg p-3 mb-4"
          style={{ background: t.colors.bg, border: `1px solid ${t.colors.borderLight}` }}>
          <p className="text-[11px]" style={{ color: t.colors.textSecondary }}>
            {selectedArch.description}
          </p>
          {!selectedArch.wired && (
            <p className="text-[11px] mt-1 font-medium" style={{ color: t.colors.warning }}>
              This archetype is a stub — clicking Run will surface the &quot;not yet wired&quot; error cleanly.
            </p>
          )}
        </div>
      )}

      <button onClick={handleRun} disabled={running}
        className="px-5 py-2 rounded-lg text-[13px] font-semibold transition-all"
        style={{
          background: running ? t.colors.neutralLight : t.colors.primary,
          color: running ? t.colors.textDim : "#fff",
          opacity: running ? 0.7 : 1,
          cursor: running ? "not-allowed" : "pointer",
        }}>
        {running ? "Running backtest…" : "Run Backtest →"}
      </button>

      {/* Result */}
      {result && (
        <div className="mt-5 rounded-lg p-4"
          style={{
            background: result.status === "not_implemented" ? t.colors.warningLight
              : result.error ? t.colors.dangerLight
              : t.colors.successLight,
            border: `1px solid ${result.status === "not_implemented" ? t.colors.warningBorder
              : result.error ? t.colors.dangerBorder
              : t.colors.successBorder}`,
          }}>
          <div className="flex items-center gap-2 mb-2">
            <span className="text-[11px] font-bold uppercase"
              style={{
                color: result.status === "not_implemented" ? t.colors.warning
                  : result.error ? t.colors.danger
                  : t.colors.success,
              }}>
              {result.status === "not_implemented" ? "Not Implemented"
                : result.error ? "Error"
                : `Status: ${result.status}`}
            </span>
            {result.experiment_id && (
              <span className="text-[10px] font-mono" style={{ color: t.colors.textDim, fontFamily: t.fonts.mono }}>
                {result.experiment_id}
              </span>
            )}
          </div>

          {result.error && (
            <p className="text-[12px]" style={{ color: t.colors.textSecondary }}>{result.error}</p>
          )}

          {result.metrics && Object.keys(result.metrics).length > 0 && (
            <div className="grid grid-cols-3 gap-3 mt-3">
              {Object.entries(result.metrics).map(([k, v]) => (
                <div key={k}>
                  <p className="text-[9px] uppercase tracking-wider" style={{ color: t.colors.textDim }}>
                    {k.replace(/_/g, " ")}
                  </p>
                  <p className="text-[13px] font-semibold font-mono"
                    style={{ color: t.colors.text, fontFamily: t.fonts.mono }}>
                    {typeof v === "number" ? v.toFixed(3) : String(v)}
                  </p>
                </div>
              ))}
            </div>
          )}
          {result.trades > 0 && (
            <p className="text-[11px] mt-2" style={{ color: t.colors.textSecondary }}>
              {result.trades} trades in backtest window
            </p>
          )}
        </div>
      )}

      {error && (
        <div className="mt-4 rounded-lg p-3" style={{ background: t.colors.dangerLight, border: `1px solid ${t.colors.dangerBorder}` }}>
          <p className="text-[12px]" style={{ color: t.colors.danger }}>Network error: {error}</p>
        </div>
      )}
    </Card>
  );
}

function LabTab() {
  const { data, loading, error } = usePolling(getLabStatus, 60000);

  if (loading && !data) return <Spinner />;
  if (error) return <p className="text-[13px]" style={{ color: t.colors.danger }}>Error: {error}</p>;
  if (!data) return null;

  const totalExps = Object.values(data.kanban).reduce((s, arr) => s + arr.length, 0);

  return (
    <div className="space-y-8">
      {/* Lab status banner */}
      <div className="rounded-xl p-5"
        style={{ background: t.colors.surface, border: `1px solid ${t.colors.border}` }}>
        <div className="flex items-center gap-3 mb-2">
          <Dot on={data.enabled} />
          <span className="text-[14px] font-semibold"
            style={{ color: t.colors.text, fontFamily: t.fonts.heading }}>
            Lab Engine
          </span>
          <span className="text-[11px] font-medium px-2 py-0.5 rounded-full"
            style={{
              background: data.enabled ? t.colors.successLight : t.colors.neutralLight,
              color: data.enabled ? t.colors.success : t.colors.textDim,
              border: `1px solid ${data.enabled ? t.colors.successBorder : t.colors.border}`,
            }}>
            {data.enabled ? "Enabled" : "Disabled (kill switch off)"}
          </span>
        </div>
        <p className="text-[12px]" style={{ color: t.colors.textSecondary }}>
          The Lab Engine runs a discover → backtest → paper trade → graduate pipeline. Experiments move
          through the kanban below. Only the <strong>momentum_breakout</strong> archetype is wired to a
          real strategy class; others raise NotImplementedError until their strategy classes are implemented.
          Kill switch: <code className="font-mono text-[11px]" style={{ color: t.colors.primary }}>data/config/lab.json</code>
        </p>
        {totalExps > 0 && (
          <p className="text-[11px] mt-2" style={{ color: t.colors.textDim }}>
            {totalExps} experiment{totalExps !== 1 ? "s" : ""} in pipeline
          </p>
        )}
      </div>

      {/* Kanban */}
      <div>
        <SectionLabel>Experiment Pipeline</SectionLabel>
        {totalExps === 0 ? (
          <div className="rounded-lg p-6 text-center"
            style={{ background: t.colors.surface, border: `1px solid ${t.colors.border}` }}>
            <p className="text-[13px] mb-1" style={{ color: t.colors.textSecondary }}>No experiments yet.</p>
            <p className="text-[12px]" style={{ color: t.colors.textDim }}>
              Run a backtest below to create your first experiment, or enable the lab iterator to let it
              auto-discover strategies via <code className="font-mono" style={{ color: t.colors.primary }}>LabEngine.discover(market)</code>.
            </p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <KanbanBoard kanban={data.kanban} />
          </div>
        )}
      </div>

      {/* Graduation thresholds */}
      {data.graduation_thresholds && Object.keys(data.graduation_thresholds).length > 0 && (
        <div>
          <SectionLabel>Graduation Thresholds</SectionLabel>
          <div className="grid grid-cols-3 md:grid-cols-6 gap-3">
            {Object.entries(data.graduation_thresholds).map(([k, v]) => (
              <div key={k} className="rounded-lg p-3"
                style={{ background: t.colors.surface, border: `1px solid ${t.colors.border}` }}>
                <p className="text-[9px] uppercase tracking-wider mb-1" style={{ color: t.colors.textDim }}>
                  {k.replace(/_/g, " ")}
                </p>
                <p className="text-[13px] font-semibold font-mono"
                  style={{ color: t.colors.text, fontFamily: t.fonts.mono }}>
                  {typeof v === "number" && v < 1 && !k.includes("hours") && !k.includes("trades")
                    ? `${(v * 100).toFixed(0)}%` : String(v)}
                </p>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Archetypes */}
      <div>
        <SectionLabel>Strategy Archetypes</SectionLabel>
        <div className="space-y-2">
          {data.archetypes.map((arch) => (
            <ArchetypeRow key={arch.id} arch={arch} />
          ))}
        </div>
      </div>

      {/* Backtest form */}
      <div>
        <SectionLabel>Interactive Backtest</SectionLabel>
        <BacktestForm archetypes={data.archetypes} approvedMarkets={data.approved_markets} />
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// Main page
// ═══════════════════════════════════════════════════════════════════════════════

export default function StrategiesPage() {
  const [activeTab, setActiveTab] = useState<Tab>("overview");

  const handleDrillDown = useCallback(() => setActiveTab("detail"), []);

  return (
    <div className="p-6 md:p-8 max-w-[1400px]">
      {/* Page header */}
      <div className="mb-6">
        <h2 className="text-2xl font-semibold"
          style={{ color: t.colors.text, fontFamily: t.fonts.heading }}>
          Strategies
        </h2>
        <p className="text-[13px] mt-1" style={{ color: t.colors.textMuted }}>
          Strategy registry, oil bot pattern drill-down, self-improvement layers, and lab engine backtest pipeline.
        </p>
      </div>

      <TabBar active={activeTab} onChange={setActiveTab} />

      {activeTab === "overview" && <OverviewTab onDrillDown={handleDrillDown} />}
      {activeTab === "detail"   && <DetailTab />}
      {activeTab === "lab"      && <LabTab />}
    </div>
  );
}
