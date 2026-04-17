"use client";

import { useState } from "react";
import { usePolling } from "@/lib/hooks";
import { getCatalysts } from "@/lib/api";
import { theme as t } from "@/lib/theme";

// Shape of a catalyst record from the news API.
// Fields: id, headline_id, instruments, event_date, category, severity (1-5),
//         expected_direction, rationale, created_at
interface Catalyst {
  id?: string;
  headline_id?: string;
  instruments?: string[];
  event_date?: string;
  category?: string;
  severity?: number | string;
  expected_direction?: string | null;
  rationale?: string;
  created_at?: string;
  // legacy / enriched fields that may appear in older records
  title?: string;
  summary?: string;
  source?: string;
  timestamp?: number;
  timestamp_ms?: number;
  [key: string]: unknown;
}

/** Severity 1-5 → colour tokens */
function sevStyle(severity: number | string | undefined): { bg: string; text: string; border: string } {
  const n = typeof severity === "string" ? parseInt(severity, 10) : (severity ?? 0);
  if (n >= 5) return { bg: t.colors.dangerLight,   text: t.colors.danger,   border: t.colors.dangerBorder };
  if (n >= 4) return { bg: t.colors.warningLight,  text: t.colors.warning,  border: t.colors.warningBorder };
  if (n >= 3) return { bg: t.colors.tertiaryLight, text: t.colors.tertiary, border: t.colors.tertiaryBorder };
  return       { bg: t.colors.neutralLight,  text: t.colors.textMuted, border: "rgba(126,117,111,0.2)" };
}

/** Convert ISO string or unix-ms/s to "Xh ago" / "Xd ago" */
function timeAgo(ts: string | number | undefined): string {
  if (!ts) return "";
  let ms: number;
  if (typeof ts === "string") {
    ms = new Date(ts).getTime();
  } else {
    ms = ts > 1e12 ? ts : ts * 1000;
  }
  if (isNaN(ms) || ms <= 0) return "";
  const diffH = (Date.now() - ms) / 3_600_000;
  if (diffH < 1)   return `${Math.round(diffH * 60)}m ago`;
  if (diffH < 48)  return `${diffH.toFixed(1)}h ago`;
  return `${(diffH / 24).toFixed(1)}d ago`;
}

/** Format category slug → human label */
function fmtCategory(cat: string | undefined): string {
  if (!cat) return "Event";
  return cat.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

/** Strip xyz: prefix for display */
function fmtInstrument(inst: string): string {
  return inst.replace(/^xyz:/, "");
}

function CatalystItem({ item }: { item: Catalyst }) {
  const [expanded, setExpanded] = useState(false);

  // Prefer explicit title, else derive from category
  const title = item.title || fmtCategory(item.category);
  // Prefer explicit summary / rationale for the body text
  const body  = item.summary || item.rationale || "";
  // Timestamp: try created_at → event_date → legacy numeric fields
  const ageStr = timeAgo(item.created_at || item.event_date || item.timestamp_ms || item.timestamp);

  const sev = sevStyle(item.severity);
  const sevNum = typeof item.severity === "string" ? parseInt(item.severity, 10) : (item.severity ?? 0);

  const instruments: string[] = Array.isArray(item.instruments) ? item.instruments : [];
  const directionColor =
    item.expected_direction === "bull" ? t.colors.success :
    item.expected_direction === "bear" ? t.colors.danger  : undefined;

  return (
    <div
      className="py-3 cursor-pointer"
      style={{ borderBottom: `1px solid ${t.colors.borderLight}` }}
      onClick={() => setExpanded((e) => !e)}
    >
      {/* Title row */}
      <div className="flex items-start gap-2">
        {/* Severity badge (number) */}
        <span
          className="flex-shrink-0 w-5 h-5 rounded text-[10px] font-bold flex items-center justify-center mt-0.5"
          style={{ background: sev.bg, color: sev.text, border: `1px solid ${sev.border}` }}
          title={`Severity ${sevNum}/5`}
        >
          {sevNum || "?"}
        </span>

        <div className="flex-1 min-w-0">
          <p
            className={`text-[13px] font-medium leading-snug ${expanded ? "" : "line-clamp-1"}`}
            style={{ color: t.colors.text }}
          >
            {title}
          </p>

          {/* Meta row: instruments + direction + age */}
          <div className="flex flex-wrap items-center gap-1.5 mt-1">
            {instruments.map((inst) => (
              <span
                key={inst}
                className="px-1.5 py-0.5 rounded text-[10px] font-medium"
                style={{
                  background: t.colors.primaryLight,
                  color: t.colors.primary,
                  border: `1px solid ${t.colors.primaryBorder}`,
                }}
              >
                {fmtInstrument(inst)}
              </span>
            ))}
            {item.expected_direction && (
              <span
                className="px-1.5 py-0.5 rounded text-[10px] font-medium uppercase"
                style={{ color: directionColor ?? t.colors.textDim }}
              >
                {item.expected_direction}
              </span>
            )}
            {ageStr && (
              <span className="text-[11px]" style={{ color: t.colors.textDim }}>
                {ageStr}
              </span>
            )}
          </div>
        </div>
      </div>

      {/* Expanded detail */}
      {expanded && (
        <div
          className="mt-2 ml-7 rounded p-2 text-[11px] space-y-1"
          style={{ background: t.colors.borderLight, color: t.colors.textSecondary }}
        >
          {body && <p className="leading-relaxed">{body}</p>}
          {item.source && (
            <p><span style={{ color: t.colors.textMuted }}>Source:</span> {item.source as string}</p>
          )}
          {item.id && (
            <p className="font-mono" style={{ color: t.colors.textDim }}>
              id: {item.id}
            </p>
          )}
        </div>
      )}
    </div>
  );
}

export function NewsFeed() {
  const { data, loading } = usePolling(
    () => getCatalysts(10) as Promise<{ catalysts: Catalyst[] }>,
    60_000,
  );

  return (
    <div className="rounded-lg p-5" style={{ background: t.colors.surface, border: `1px solid ${t.colors.border}` }}>
      <h3
        className="text-[13px] font-medium mb-3"
        style={{
          color: t.colors.textMuted,
          textTransform: "uppercase",
          letterSpacing: "0.05em",
          fontFamily: t.fonts.heading,
        }}
      >
        Catalysts
      </h3>
      <div
        className="max-h-80 overflow-y-auto"
        style={{ scrollbarWidth: "thin", scrollbarColor: `${t.colors.border} transparent` }}
      >
        {loading || !data ? (
          <p className="text-[13px]" style={{ color: t.colors.textDim }}>Connecting…</p>
        ) : data.catalysts.length === 0 ? (
          <p className="text-[13px]" style={{ color: t.colors.textDim }}>No catalysts ingested yet</p>
        ) : (
          data.catalysts.slice(0, 10).map((item, i) => (
            <CatalystItem key={item.id ?? i} item={item} />
          ))
        )}
      </div>
    </div>
  );
}
