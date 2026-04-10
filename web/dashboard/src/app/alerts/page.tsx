"use client";

import { useState } from "react";
import { usePolling } from "@/lib/hooks";
import {
  getAlerts,
  getSignals,
  getThesisChallenges,
  getDisruptions,
  getSystemErrors,
  type AlertEntry,
  type AlertSeverity,
  type AlertType,
} from "@/lib/api";
import { theme as t } from "@/lib/theme";

// ── Severity styling ──────────────────────────────────────────────────────────

const SEVERITY_STYLES: Record<AlertSeverity, { color: string; bg: string; border: string; label: string }> = {
  critical: {
    color: t.colors.danger,
    bg: t.colors.dangerLight,
    border: t.colors.dangerBorder,
    label: "Critical",
  },
  high: {
    color: t.colors.warning,
    bg: t.colors.warningLight,
    border: t.colors.warningBorder,
    label: "High",
  },
  medium: {
    color: t.colors.tertiary,
    bg: t.colors.tertiaryLight,
    border: t.colors.tertiaryBorder,
    label: "Medium",
  },
  low: {
    color: t.colors.textMuted,
    bg: t.colors.neutralLight,
    border: t.colors.border,
    label: "Low",
  },
};

// ── Type labels ───────────────────────────────────────────────────────────────

const TYPE_LABELS: Record<AlertType, string> = {
  thesis_challenge: "Thesis Challenge",
  conviction_change: "Conviction",
  supply_disruption: "Supply",
  bot_pattern: "Bot Pattern",
  system_error: "System Error",
  catalyst: "Catalyst",
  heatmap_zone: "Heatmap",
};

// ── Timestamp formatter (Brisbane / AEST) ─────────────────────────────────────

function fmt(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    if (isNaN(d.getTime())) return iso;
    return d.toLocaleString("en-AU", {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      timeZone: "Australia/Brisbane",
    });
  } catch {
    return iso;
  }
}

// ── Severity badge ────────────────────────────────────────────────────────────

function SeverityBadge({ severity }: { severity: AlertSeverity }) {
  const s = SEVERITY_STYLES[severity] || SEVERITY_STYLES.low;
  return (
    <span
      className="text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-full whitespace-nowrap"
      style={{ color: s.color, background: s.bg, border: `1px solid ${s.border}` }}
    >
      {s.label}
    </span>
  );
}

// ── Type badge ────────────────────────────────────────────────────────────────

function TypeBadge({ type }: { type: AlertType }) {
  return (
    <span
      className="text-[10px] font-medium px-2 py-0.5 rounded"
      style={{
        color: t.colors.textSecondary,
        background: t.colors.neutralLight,
        border: `1px solid ${t.colors.border}`,
        fontFamily: t.fonts.mono,
      }}
    >
      {TYPE_LABELS[type] || type}
    </span>
  );
}

// ── Single alert row ──────────────────────────────────────────────────────────

function AlertRow({ entry }: { entry: AlertEntry }) {
  const [expanded, setExpanded] = useState(false);
  const hasDeets = !!entry.detail;

  return (
    <div
      className="transition-colors"
      style={{ borderBottom: `1px solid ${t.colors.borderLight}` }}
    >
      <button
        className="w-full text-left"
        onClick={() => hasDeets && setExpanded((v) => !v)}
        style={{ cursor: hasDeets ? "pointer" : "default" }}
      >
        <div className="flex items-start gap-3 px-4 py-3 hover:bg-[#1a1b22] transition-colors">
          {/* Left: severity stripe */}
          <div
            className="w-1 self-stretch rounded-full flex-shrink-0 mt-0.5"
            style={{
              background: SEVERITY_STYLES[entry.severity]?.color || t.colors.textDim,
              minHeight: "16px",
            }}
          />

          {/* Main content */}
          <div className="flex-1 min-w-0">
            <div className="flex flex-wrap items-center gap-2 mb-1">
              <SeverityBadge severity={entry.severity} />
              <TypeBadge type={entry.type} />
              {entry.market && (
                <span
                  className="text-[11px] font-semibold"
                  style={{ color: t.colors.primary, fontFamily: t.fonts.mono }}
                >
                  {entry.market}
                </span>
              )}
            </div>
            <p
              className="text-[13px] leading-snug"
              style={{ color: t.colors.text }}
            >
              {entry.summary}
            </p>
          </div>

          {/* Right: meta */}
          <div className="flex-shrink-0 text-right ml-2">
            <p
              className="text-[11px] mb-1"
              style={{ color: t.colors.textDim, fontFamily: t.fonts.mono }}
            >
              {fmt(entry.timestamp)}
            </p>
            <p
              className="text-[10px]"
              style={{ color: t.colors.textDim }}
            >
              {entry.source}
            </p>
          </div>
        </div>
      </button>

      {/* Expanded detail */}
      {expanded && hasDeets && (
        <div
          className="px-4 pb-3"
          style={{ marginLeft: "calc(0.25rem + 0.75rem)" }}
        >
          <p
            className="text-[12px] leading-relaxed p-3 rounded-lg"
            style={{
              color: t.colors.textSecondary,
              background: t.colors.bg,
              border: `1px solid ${t.colors.borderLight}`,
            }}
          >
            {entry.detail}
          </p>
        </div>
      )}
    </div>
  );
}

// ── Alert list wrapper ────────────────────────────────────────────────────────

function AlertList({ entries, emptyMessage }: { entries: AlertEntry[]; emptyMessage: string }) {
  if (entries.length === 0) {
    return (
      <div
        className="rounded-xl p-10 text-center"
        style={{ background: t.colors.surface, border: `1px solid ${t.colors.border}` }}
      >
        <p className="text-[13px]" style={{ color: t.colors.textDim }}>
          {emptyMessage}
        </p>
      </div>
    );
  }

  return (
    <div
      className="rounded-xl overflow-hidden"
      style={{ background: t.colors.surface, border: `1px solid ${t.colors.border}` }}
    >
      {entries.map((entry, i) => (
        <AlertRow key={entry.id || i} entry={entry} />
      ))}
    </div>
  );
}

// ── Stat chip ─────────────────────────────────────────────────────────────────

function StatChip({ label, count, severity }: { label: string; count: number; severity?: AlertSeverity }) {
  const color = severity ? SEVERITY_STYLES[severity].color : t.colors.textSecondary;
  return (
    <div
      className="rounded-lg px-4 py-2.5 flex items-center gap-2"
      style={{ background: t.colors.surface, border: `1px solid ${t.colors.border}` }}
    >
      <span className="text-[22px] font-bold" style={{ color, fontFamily: t.fonts.mono }}>
        {count}
      </span>
      <span className="text-[12px]" style={{ color: t.colors.textMuted }}>
        {label}
      </span>
    </div>
  );
}

// ── Tab definitions ───────────────────────────────────────────────────────────

type Tab = "all" | "signals" | "thesis" | "supply" | "errors";

const TABS: { id: Tab; label: string }[] = [
  { id: "all", label: "All" },
  { id: "signals", label: "Signals" },
  { id: "thesis", label: "Thesis" },
  { id: "supply", label: "Supply" },
  { id: "errors", label: "Errors" },
];

// ── Last-refreshed display ────────────────────────────────────────────────────

function LastRefreshed({ loading }: { loading: boolean }) {
  const now = new Date().toLocaleTimeString("en-AU", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    timeZone: "Australia/Brisbane",
  });
  if (loading) {
    return <span className="text-[12px]" style={{ color: t.colors.textDim }}>Refreshing…</span>;
  }
  return (
    <span className="text-[12px]" style={{ color: t.colors.textDim, fontFamily: t.fonts.mono }}>
      Updated {now} AEST
    </span>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function AlertsPage() {
  const [activeTab, setActiveTab] = useState<Tab>("all");

  // All feeds — 30s polling
  const { data: allData, loading: allLoading } = usePolling(getAlerts, 30000);
  const { data: signalsData, loading: signalsLoading } = usePolling(getSignals, 30000);
  const { data: thesisData, loading: thesisLoading } = usePolling(getThesisChallenges, 30000);
  const { data: supplyData, loading: supplyLoading } = usePolling(getDisruptions, 30000);
  const { data: errorsData, loading: errorsLoading } = usePolling(getSystemErrors, 30000);

  const allEntries = allData?.alerts || [];
  const signalEntries = signalsData?.signals || [];
  const thesisEntries = thesisData?.challenges || [];
  const supplyEntries = supplyData?.disruptions || [];
  const errorEntries = errorsData?.errors || [];

  // Severity counts across all alerts
  const critCount = allEntries.filter((e) => e.severity === "critical").length;
  const highCount = allEntries.filter((e) => e.severity === "high").length;
  const medCount = allEntries.filter((e) => e.severity === "medium").length;

  const isLoading =
    activeTab === "all" ? allLoading :
    activeTab === "signals" ? signalsLoading :
    activeTab === "thesis" ? thesisLoading :
    activeTab === "supply" ? supplyLoading :
    errorsLoading;

  const tabEntries: Record<Tab, AlertEntry[]> = {
    all: allEntries,
    signals: signalEntries,
    thesis: thesisEntries,
    supply: supplyEntries,
    errors: errorEntries,
  };

  const emptyMessages: Record<Tab, string> = {
    all: "No alerts in the feed.",
    signals: "No signals detected yet.",
    thesis: "No thesis challenges recorded.",
    supply: "No supply disruptions on file.",
    errors: "No system errors logged.",
  };

  const badgeCounts: Partial<Record<Tab, number>> = {
    errors: errorEntries.length,
    thesis: thesisEntries.length,
    supply: supplyEntries.length,
    signals: signalEntries.length,
  };

  return (
    <div className="p-8 max-w-[1200px]">
      {/* Page header */}
      <div className="mb-6">
        <h2
          className="text-2xl font-semibold"
          style={{ color: t.colors.text, fontFamily: t.fonts.heading }}
        >
          Alerts & Signals
        </h2>
        <p className="text-[13px] mt-1" style={{ color: t.colors.textMuted }}>
          Thesis challenges, supply disruptions, system errors, and market signals
        </p>
      </div>

      {/* Summary chips */}
      <div className="flex flex-wrap gap-3 mb-6">
        <StatChip label="Critical" count={critCount} severity="critical" />
        <StatChip label="High" count={highCount} severity="high" />
        <StatChip label="Medium" count={medCount} severity="medium" />
        <StatChip label="Total" count={allEntries.length} />
        <div className="flex-1" />
        <div className="flex items-center">
          <LastRefreshed loading={allLoading} />
        </div>
      </div>

      {/* Tab bar */}
      <div
        className="flex gap-1 mb-5 p-1 rounded-xl"
        style={{ background: t.colors.surface, border: `1px solid ${t.colors.border}`, width: "fit-content" }}
      >
        {TABS.map((tab) => {
          const active = activeTab === tab.id;
          const badge = badgeCounts[tab.id];
          return (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className="px-4 py-1.5 rounded-lg text-[13px] font-medium transition-all flex items-center gap-1.5"
              style={
                active
                  ? {
                      background: t.colors.primaryLight,
                      color: t.colors.primary,
                      border: `1px solid ${t.colors.primaryBorder}`,
                      fontFamily: t.fonts.heading,
                    }
                  : {
                      color: t.colors.textMuted,
                      border: "1px solid transparent",
                    }
              }
            >
              {tab.label}
              {badge !== undefined && badge > 0 && (
                <span
                  className="text-[10px] font-bold px-1.5 py-0.5 rounded-full"
                  style={{
                    background: active ? t.colors.primaryBorder : t.colors.neutralLight,
                    color: active ? t.colors.primary : t.colors.textDim,
                    fontFamily: t.fonts.mono,
                  }}
                >
                  {badge}
                </span>
              )}
            </button>
          );
        })}
      </div>

      {/* Alert list */}
      {isLoading && tabEntries[activeTab].length === 0 ? (
        <div
          className="rounded-xl p-10 text-center"
          style={{ background: t.colors.surface, border: `1px solid ${t.colors.border}` }}
        >
          <p className="text-[13px]" style={{ color: t.colors.textDim }}>
            Loading…
          </p>
        </div>
      ) : (
        <AlertList
          entries={tabEntries[activeTab]}
          emptyMessage={emptyMessages[activeTab]}
        />
      )}
    </div>
  );
}
