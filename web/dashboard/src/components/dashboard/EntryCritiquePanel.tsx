"use client";

import { useState } from "react";
import { usePolling } from "@/lib/hooks";
import { getEntryCritiques, EntryCritique, EntryCritiqueGrade } from "@/lib/api";
import { theme as t } from "@/lib/theme";

// ── Label → emoji mapping (matches the PASS/MIXED/FAIL/NO_THESIS spec) ──
const LABEL_EMOJI: Record<string, string> = {
  "GREAT ENTRY": "✅",
  "GOOD ENTRY": "✅",
  "OK ENTRY": "⚠️",
  "RISKY ENTRY": "🔴",
  "BAD ENTRY": "🔴",
  "MIXED ENTRY": "⚠️",
  "NO THESIS": "❓",
  GREAT: "✅",
  GOOD: "✅",
  OK: "⚠️",
  RISKY: "🔴",
  BAD: "🔴",
  MIXED: "⚠️",
  PASS: "✅",
  FAIL: "🔴",
};

function labelEmoji(overall: string): string {
  return LABEL_EMOJI[overall.toUpperCase()] ?? "·";
}

function labelColor(overall: string): string {
  const up = overall.toUpperCase();
  if (up.includes("GREAT") || up.includes("GOOD") || up === "PASS")
    return t.colors.success;
  if (up.includes("RISKY") || up.includes("BAD") || up === "FAIL")
    return t.colors.danger;
  if (up.includes("MIXED") || up.includes("OK")) return t.colors.warning;
  if (up.includes("NO THESIS")) return t.colors.textDim;
  return t.colors.textMuted;
}

function ageStr(createdAt: string): string {
  if (!createdAt) return "";
  const dt = new Date(createdAt);
  const secs = Math.floor((Date.now() - dt.getTime()) / 1000);
  if (secs < 60) return `${secs}s ago`;
  if (secs < 3600) return `${Math.floor(secs / 60)}m ago`;
  const h = Math.floor(secs / 3600);
  const m = Math.floor((secs % 3600) / 60);
  return m ? `${h}h ${m}m ago` : `${h}h ago`;
}

function stripXyz(name: string): string {
  return name.startsWith("xyz:") ? name.slice(4) : name;
}

// ── Grade axis row ───────────────────────────────────────────────────────
function GradeRow({
  label,
  verdict,
  detail,
}: {
  label: string;
  verdict: string;
  detail: string;
}) {
  const positive = ["GREAT", "ALIGNED", "LEAD", "SAFE", "CHEAP"].includes(
    verdict.toUpperCase()
  );
  const negative = ["OPPOSED", "BAD", "DANGER", "CASCADE_RISK"].includes(
    verdict.toUpperCase()
  );
  const neutral = verdict.toUpperCase() === "NO_THESIS";

  const color = positive
    ? t.colors.success
    : negative
    ? t.colors.danger
    : neutral
    ? t.colors.textDim
    : t.colors.warning;

  return (
    <div
      className="grid gap-1 py-1.5"
      style={{
        gridTemplateColumns: "72px 1fr",
        borderBottom: `1px solid ${t.colors.borderLight}`,
        fontSize: "12px",
      }}
    >
      <span style={{ color: t.colors.textMuted }}>{label}</span>
      <span>
        <span style={{ color, fontFamily: t.fonts.mono }}>{verdict}</span>
        {detail && (
          <span style={{ color: t.colors.textDim }}> — {detail}</span>
        )}
      </span>
    </div>
  );
}

// ── Expanded detail card ─────────────────────────────────────────────────
function ExpandedCritique({ row }: { row: EntryCritique }) {
  const g: EntryCritiqueGrade = row.grade || ({} as EntryCritiqueGrade);
  const s = row.signals || {};
  const overall = g.overall_label || "?";
  const color = labelColor(overall);
  const axes: [string, keyof EntryCritiqueGrade, string][] = [
    ["Sizing", "sizing", "sizing_detail"],
    ["Direction", "direction", "direction_detail"],
    ["Timing", "catalyst_timing", "catalyst_detail"],
    ["Liquidity", "liquidity", "liquidity_detail"],
    ["Funding", "funding", "funding_detail"],
  ];

  return (
    <div
      className="mt-2 rounded p-3"
      style={{
        background: t.colors.bg,
        border: `1px solid ${t.colors.border}`,
        fontSize: "12px",
      }}
    >
      {/* Grade axes */}
      <div>
        {axes.map(([label, axisKey, detailKey]) => (
          <GradeRow
            key={label}
            label={label}
            verdict={String(g[axisKey] ?? "?")}
            detail={String(g[detailKey as keyof EntryCritiqueGrade] ?? "")}
          />
        ))}
      </div>

      {/* Signals */}
      {(s.rsi != null || s.atr_pct != null || s.liquidation_cushion_pct != null) && (
        <div className="mt-2" style={{ color: t.colors.textDim }}>
          {s.rsi != null && <span className="mr-3">RSI {s.rsi.toFixed(1)}</span>}
          {s.atr_pct != null && (
            <span className="mr-3">ATR {s.atr_pct.toFixed(2)}%</span>
          )}
          {s.liquidation_cushion_pct != null && (
            <span className="mr-3">
              Liq-cushion {s.liquidation_cushion_pct.toFixed(1)}%
            </span>
          )}
          {(s.snapshot_flags || []).slice(0, 3).map((f: string) => (
            <span key={f} className="mr-2" style={{ color: t.colors.textDim }}>
              {f}
            </span>
          ))}
        </div>
      )}

      {/* Suggestions */}
      {g.suggestions && g.suggestions.length > 0 && (
        <div className="mt-2">
          <div style={{ color: t.colors.textMuted, marginBottom: "4px" }}>
            Suggestions
          </div>
          {g.suggestions.slice(0, 5).map((s: string, i: number) => (
            <div key={i} style={{ color: t.colors.textSecondary }}>
              · {s}
            </div>
          ))}
        </div>
      )}

      {/* Overall */}
      <div className="mt-2 pt-2" style={{ borderTop: `1px solid ${t.colors.border}` }}>
        <span style={{ color, fontWeight: 600 }}>
          {labelEmoji(overall)} {overall}
        </span>
        <span style={{ color: t.colors.textDim, marginLeft: "8px" }}>
          {g.pass_count}✅ / {g.warn_count}⚠️ / {g.fail_count}🔴
        </span>
      </div>

      {/* Degraded inputs */}
      {row.degraded && Object.values(row.degraded).some(Boolean) && (
        <div className="mt-1" style={{ color: t.colors.textDim, fontSize: "11px" }}>
          Degraded: {Object.entries(row.degraded).filter(([, v]) => v).map(([k]) => k).join(", ")}
        </div>
      )}
    </div>
  );
}

// ── Single row in the compact list ──────────────────────────────────────
function CritiqueRow({ row }: { row: EntryCritique }) {
  const [expanded, setExpanded] = useState(false);
  const g = row.grade || ({} as EntryCritiqueGrade);
  const overall = g.overall_label || "?";
  const color = labelColor(overall);
  const instrument = stripXyz(row.instrument || "?");
  const direction = (row.direction || "?").toUpperCase();
  const age = ageStr(row.created_at || "");
  const reason =
    g.suggestions && g.suggestions.length > 0
      ? g.suggestions[0].slice(0, 60)
      : overall;

  return (
    <div
      className="py-2.5"
      style={{ borderBottom: `1px solid ${t.colors.borderLight}` }}
    >
      <div
        className="flex items-center justify-between cursor-pointer"
        onClick={() => setExpanded((e) => !e)}
      >
        <div className="flex items-center gap-2">
          <span style={{ fontFamily: t.fonts.mono, fontSize: "13px", color: t.colors.text }}>
            {instrument}
          </span>
          <span
            style={{
              fontSize: "11px",
              padding: "1px 6px",
              borderRadius: "4px",
              background:
                direction === "LONG"
                  ? t.colors.successLight
                  : t.colors.dangerLight,
              color:
                direction === "LONG" ? t.colors.success : t.colors.danger,
              border: `1px solid ${direction === "LONG" ? t.colors.successBorder : t.colors.dangerBorder}`,
            }}
          >
            {direction}
          </span>
          <span
            style={{
              fontSize: "12px",
              fontWeight: 600,
              color,
            }}
          >
            {labelEmoji(overall)} {overall}
          </span>
        </div>
        <div
          className="flex items-center gap-3"
          style={{ fontSize: "11px", color: t.colors.textDim }}
        >
          <span>
            {g.pass_count ?? 0}✅/{g.warn_count ?? 0}⚠️/{g.fail_count ?? 0}🔴
          </span>
          <span>{age}</span>
          <span style={{ opacity: 0.5 }}>{expanded ? "▲" : "▼"}</span>
        </div>
      </div>

      {reason && reason !== overall && (
        <div
          className="mt-0.5"
          style={{ fontSize: "11px", color: t.colors.textDim }}
        >
          {reason}
        </div>
      )}

      {expanded && <ExpandedCritique row={row} />}
    </div>
  );
}

// ── Main panel ───────────────────────────────────────────────────────────
export function EntryCritiquePanel() {
  const { data, loading, error } = usePolling(
    () => getEntryCritiques(5),
    60_000
  );

  return (
    <div
      className="rounded-lg p-5"
      style={{
        background: t.colors.surface,
        border: `1px solid ${t.colors.border}`,
      }}
    >
      <div className="flex items-center justify-between mb-3">
        <h3
          className="text-[13px] font-medium"
          style={{
            color: t.colors.textMuted,
            textTransform: "uppercase",
            letterSpacing: "0.05em",
            fontFamily: t.fonts.heading,
          }}
        >
          Entry Critiques
        </h3>
        {data && (
          <span style={{ fontSize: "11px", color: t.colors.textDim }}>
            {data.total} total
          </span>
        )}
      </div>

      <div
        className="max-h-80 overflow-y-auto"
        style={{
          scrollbarWidth: "thin",
          scrollbarColor: `${t.colors.border} transparent`,
        }}
      >
        {loading && !data ? (
          <p style={{ fontSize: "13px", color: t.colors.textDim }}>
            Connecting...
          </p>
        ) : error ? (
          <p style={{ fontSize: "13px", color: t.colors.danger }}>{error}</p>
        ) : !data || data.critiques.length === 0 ? (
          <p style={{ fontSize: "13px", color: t.colors.textDim }}>
            No entry critiques yet — daemon entry_critic fires on every new
            position.
          </p>
        ) : (
          data.critiques.map((row, i) => <CritiqueRow key={i} row={row} />)
        )}
      </div>
    </div>
  );
}
