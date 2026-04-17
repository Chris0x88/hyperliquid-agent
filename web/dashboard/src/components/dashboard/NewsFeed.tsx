"use client";

// NewsFeed — Sprint-1 upgrade:
// 1. Full article expand (inline accordion, fetches /api/news/catalyst/:id)
// 2. Filter chips (severity / market / direction / read) → localStorage
// 3. Linked-thesis badge on collapsed card
// 4. Mark-as-read (eye toggle) → localStorage

/* eslint-disable react-hooks/set-state-in-effect */

import { useState, useEffect, useCallback } from "react";
import { usePolling } from "@/lib/hooks";
import { getCatalysts } from "@/lib/api";
import { theme as t } from "@/lib/theme";

// ── Local types ───────────────────────────────────────────────────────────────

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
  title?: string;
  summary?: string;
  source?: string;
  timestamp?: number;
  timestamp_ms?: number;
  [key: string]: unknown;
}

interface Headline {
  id?: string;
  source?: string;
  url?: string;
  title?: string;
  body_excerpt?: string;
  published_at?: string;
  fetched_at?: string;
  [key: string]: unknown;
}

interface LinkedThesisRow {
  market: string;
  direction: string;
  conviction: number;
  thesis_summary: string;
  invalidation_conditions: string[];
}

interface CatalystDetail {
  catalyst: Catalyst;
  headline: Headline | null;
  linked_theses: LinkedThesisRow[];
  audit_rows: Record<string, unknown>[];
  headline_missing: boolean;
}

// ── localStorage keys ─────────────────────────────────────────────────────────

const LS_FILTERS = "news.filters.v1";
const LS_READ = "news.read.v1";

// ── Filter state ──────────────────────────────────────────────────────────────

type ReadFilter = "all" | "unread" | "read";

interface FilterState {
  severity: number[];
  market: string[];
  direction: string[];
  readMode: ReadFilter;
}

const DEFAULT_FILTERS: FilterState = {
  severity: [],
  market: [],
  direction: [],
  readMode: "all",
};

const SEVERITY_OPTIONS = [1, 2, 3, 4, 5];
const MARKET_OPTIONS = ["BTC", "BRENTOIL", "GOLD", "SILVER", "CL", "SP500"];
const DIRECTION_OPTIONS = ["bull", "bear"];
const KNOWN_THESIS_MARKETS = ["BTC", "BRENTOIL", "GOLD", "SILVER", "CL", "SP500"];

function loadFilters(): FilterState {
  if (typeof window === "undefined") return DEFAULT_FILTERS;
  try {
    const raw = localStorage.getItem(LS_FILTERS);
    return raw ? { ...DEFAULT_FILTERS, ...(JSON.parse(raw) as Partial<FilterState>) } : DEFAULT_FILTERS;
  } catch {
    return DEFAULT_FILTERS;
  }
}

function saveFilters(f: FilterState): void {
  try {
    localStorage.setItem(LS_FILTERS, JSON.stringify(f));
  } catch {
    /* noop */
  }
}

function loadReadSet(): Set<string> {
  if (typeof window === "undefined") return new Set();
  try {
    const raw = localStorage.getItem(LS_READ);
    return raw ? new Set(JSON.parse(raw) as string[]) : new Set();
  } catch {
    return new Set();
  }
}

function saveReadSet(s: Set<string>): void {
  try {
    localStorage.setItem(LS_READ, JSON.stringify([...s]));
  } catch {
    /* noop */
  }
}

// ── Utilities ─────────────────────────────────────────────────────────────────

function sevStyle(severity: number | string | undefined): { bg: string; text: string; border: string } {
  const n = typeof severity === "string" ? parseInt(severity, 10) : (severity ?? 0);
  if (n >= 5) return { bg: t.colors.dangerLight, text: t.colors.danger, border: t.colors.dangerBorder };
  if (n >= 4) return { bg: t.colors.warningLight, text: t.colors.warning, border: t.colors.warningBorder };
  if (n >= 3) return { bg: t.colors.tertiaryLight, text: t.colors.tertiary, border: t.colors.tertiaryBorder };
  return { bg: t.colors.neutralLight, text: t.colors.textMuted, border: "rgba(126,117,111,0.2)" };
}

function timeAgo(ts: string | number | undefined): string {
  if (!ts) return "";
  const ms = typeof ts === "string" ? new Date(ts).getTime() : ts > 1e12 ? ts : ts * 1000;
  if (isNaN(ms) || ms <= 0) return "";
  const diffH = (Date.now() - ms) / 3_600_000;
  if (diffH < 1) return `${Math.round(diffH * 60)}m ago`;
  if (diffH < 48) return `${diffH.toFixed(1)}h ago`;
  return `${(diffH / 24).toFixed(1)}d ago`;
}

function fmtCategory(cat: string | undefined): string {
  if (!cat) return "Event";
  return cat.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function fmtInstrument(inst: string): string {
  return inst.replace(/^xyz:/, "");
}

function instrumentKey(inst: string): string {
  return inst.replace(/^xyz:/, "").toUpperCase();
}

function passesFilter(item: Catalyst, filters: FilterState, readSet: Set<string>): boolean {
  const id = item.id ?? "";
  const isRead = readSet.has(id);
  if (filters.readMode === "unread" && isRead) return false;
  if (filters.readMode === "read" && !isRead) return false;
  if (filters.severity.length > 0) {
    const sev = typeof item.severity === "string" ? parseInt(item.severity, 10) : (item.severity ?? 0);
    if (!filters.severity.includes(sev)) return false;
  }
  if (filters.market.length > 0) {
    const insts = (item.instruments ?? []).map(instrumentKey);
    if (!filters.market.some((m) => insts.includes(m))) return false;
  }
  if (filters.direction.length > 0) {
    const dir = (item.expected_direction ?? "").toLowerCase();
    if (!filters.direction.includes(dir)) return false;
  }
  return true;
}

// ── Filter chip ───────────────────────────────────────────────────────────────

function FilterChip({
  label,
  active,
  onClick,
  color,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
  color?: { text: string; bg: string; border: string };
}) {
  const activeColor = color ?? { text: t.colors.primary, bg: t.colors.primaryLight, border: t.colors.primaryBorder };
  return (
    <button
      onClick={onClick}
      className="px-2 py-0.5 rounded text-[11px] font-medium transition-all"
      style={
        active
          ? { background: activeColor.bg, color: activeColor.text, border: `1px solid ${activeColor.border}` }
          : { background: t.colors.borderLight, color: t.colors.textMuted, border: `1px solid ${t.colors.border}` }
      }
    >
      {label}
    </button>
  );
}

// ── Filter row ────────────────────────────────────────────────────────────────

function FilterRow({ filters, onChange }: { filters: FilterState; onChange: (f: FilterState) => void }) {
  function toggle<T>(arr: T[], val: T): T[] {
    return arr.includes(val) ? arr.filter((x) => x !== val) : [...arr, val];
  }

  const dirColors: Record<string, { text: string; bg: string; border: string }> = {
    bull: { text: t.colors.success, bg: t.colors.successLight, border: t.colors.successBorder },
    bear: { text: t.colors.danger, bg: t.colors.dangerLight, border: t.colors.dangerBorder },
  };
  const readColors: Record<ReadFilter, { text: string; bg: string; border: string }> = {
    all: { text: t.colors.textMuted, bg: t.colors.borderLight, border: t.colors.border },
    unread: { text: t.colors.tertiary, bg: t.colors.tertiaryLight, border: t.colors.tertiaryBorder },
    read: { text: t.colors.textDim, bg: t.colors.borderLight, border: t.colors.border },
  };

  return (
    <div className="space-y-1.5 mb-3">
      <div className="flex flex-wrap items-center gap-1">
        <span className="text-[10px] uppercase tracking-wider w-14 flex-shrink-0" style={{ color: t.colors.textDim }}>
          Sev
        </span>
        {SEVERITY_OPTIONS.map((n) => (
          <FilterChip
            key={n}
            label={String(n)}
            active={filters.severity.includes(n)}
            onClick={() => onChange({ ...filters, severity: toggle(filters.severity, n) })}
            color={sevStyle(n)}
          />
        ))}
      </div>
      <div className="flex flex-wrap items-center gap-1">
        <span className="text-[10px] uppercase tracking-wider w-14 flex-shrink-0" style={{ color: t.colors.textDim }}>
          Market
        </span>
        {MARKET_OPTIONS.map((m) => (
          <FilterChip
            key={m}
            label={m}
            active={filters.market.includes(m)}
            onClick={() => onChange({ ...filters, market: toggle(filters.market, m) })}
          />
        ))}
      </div>
      <div className="flex flex-wrap items-center gap-1">
        <span className="text-[10px] uppercase tracking-wider w-14 flex-shrink-0" style={{ color: t.colors.textDim }}>
          Dir
        </span>
        {DIRECTION_OPTIONS.map((d) => (
          <FilterChip
            key={d}
            label={d.toUpperCase()}
            active={filters.direction.includes(d)}
            onClick={() => onChange({ ...filters, direction: toggle(filters.direction, d) })}
            color={dirColors[d]}
          />
        ))}
      </div>
      <div className="flex flex-wrap items-center gap-1">
        <span className="text-[10px] uppercase tracking-wider w-14 flex-shrink-0" style={{ color: t.colors.textDim }}>
          Read
        </span>
        {(["all", "unread", "read"] as ReadFilter[]).map((mode) => (
          <FilterChip
            key={mode}
            label={mode === "all" ? "All" : mode === "unread" ? "Unread" : "Read"}
            active={filters.readMode === mode}
            onClick={() => onChange({ ...filters, readMode: mode })}
            color={readColors[mode]}
          />
        ))}
      </div>
    </div>
  );
}

// ── Linked-thesis badge (collapsed) ──────────────────────────────────────────

function ThesisBadge({ instruments }: { instruments: string[] }) {
  const hits = KNOWN_THESIS_MARKETS.filter((m) => instruments.map(instrumentKey).includes(m));
  if (hits.length === 0) return null;
  return (
    <>
      {hits.map((m) => (
        <span
          key={m}
          className="px-1.5 py-0.5 rounded text-[10px] font-medium"
          style={{ background: t.colors.tertiaryLight, color: t.colors.tertiary, border: `1px solid ${t.colors.tertiaryBorder}` }}
          title={`Linked to ${m} thesis`}
        >
          ⊕ {m}
        </span>
      ))}
    </>
  );
}

// ── Expanded detail pane ──────────────────────────────────────────────────────

function ExpandedDetail({ catalyst, detail, loading }: { catalyst: Catalyst; detail: CatalystDetail | null; loading: boolean }) {
  const hl = detail?.headline ?? null;
  const audit = detail?.audit_rows ?? [];

  return (
    <div
      className="mt-2 ml-7 rounded-lg p-3 space-y-3"
      style={{ background: t.colors.borderLight, border: `1px solid ${t.colors.border}` }}
    >
      {loading && (
        <p className="text-[11px]" style={{ color: t.colors.textDim }}>
          Loading…
        </p>
      )}

      {/* Daemon rationale */}
      {catalyst.rationale && (
        <div>
          <p className="text-[10px] uppercase tracking-wider mb-1" style={{ color: t.colors.textMuted, fontFamily: t.fonts.heading }}>
            Daemon analysis
          </p>
          <p className="text-[12px] leading-relaxed" style={{ color: t.colors.textSecondary }}>
            {catalyst.rationale}
          </p>
        </div>
      )}

      {/* Headline unavailable */}
      {detail?.headline_missing && !hl && (
        <p className="text-[11px] italic" style={{ color: t.colors.textDim }}>
          Full article unavailable — headline_id not found in headlines.jsonl
        </p>
      )}

      {/* Article */}
      {hl && (
        <div>
          <p className="text-[10px] uppercase tracking-wider mb-1" style={{ color: t.colors.textMuted, fontFamily: t.fonts.heading }}>
            Article
          </p>
          {hl.body_excerpt && (
            <div
              className="text-[12px] leading-relaxed overflow-y-auto pr-1"
              style={{ color: t.colors.textSecondary, maxHeight: "200px", scrollbarWidth: "thin", scrollbarColor: `${t.colors.border} transparent` }}
            >
              {hl.body_excerpt}
            </div>
          )}
          <div className="flex flex-wrap items-center gap-3 mt-2">
            {hl.source && (
              <span className="text-[11px]" style={{ color: t.colors.textMuted }}>
                Source: <span style={{ color: t.colors.textSecondary }}>{hl.source as string}</span>
              </span>
            )}
            {hl.url && (
              <a
                href={hl.url as string}
                target="_blank"
                rel="noopener noreferrer"
                className="text-[11px] underline"
                style={{ color: t.colors.tertiary }}
                onClick={(e) => e.stopPropagation()}
              >
                Open article ↗
              </a>
            )}
          </div>
          <div className="flex flex-wrap gap-4 mt-1">
            {hl.published_at && (
              <span className="text-[10px]" style={{ color: t.colors.textDim }}>
                Published: {new Date(hl.published_at as string).toLocaleString()}
              </span>
            )}
            {catalyst.created_at && (
              <span className="text-[10px]" style={{ color: t.colors.textDim }}>
                Ingested: {new Date(catalyst.created_at).toLocaleString()}
              </span>
            )}
          </div>
        </div>
      )}

      {/* Linked theses */}
      {detail && detail.linked_theses.length > 0 && (
        <div>
          <p className="text-[10px] uppercase tracking-wider mb-1" style={{ color: t.colors.textMuted, fontFamily: t.fonts.heading }}>
            Linked theses
          </p>
          <div className="space-y-1.5">
            {detail.linked_theses.map((ts, i) => (
              <div key={i} className="rounded p-2" style={{ background: t.colors.surface, border: `1px solid ${t.colors.border}` }}>
                <div className="flex items-center gap-2">
                  <span className="text-[11px] font-semibold" style={{ color: t.colors.text }}>
                    {ts.market.replace("xyz:", "")}
                  </span>
                  <span className="text-[10px] uppercase" style={{ color: t.colors.textMuted }}>
                    {ts.direction}
                  </span>
                  <span
                    className="text-[10px] font-medium"
                    style={{
                      color: ts.conviction > 0.5 ? t.colors.success : ts.conviction > 0.2 ? t.colors.warning : t.colors.danger,
                    }}
                  >
                    {Math.round(ts.conviction * 100)}% conviction
                  </span>
                </div>
                {ts.thesis_summary && (
                  <p className="text-[11px] mt-0.5 leading-snug" style={{ color: t.colors.textSecondary }}>
                    {ts.thesis_summary.length > 140 ? ts.thesis_summary.slice(0, 140) + "…" : ts.thesis_summary}
                  </p>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Conviction audit */}
      {audit.length > 0 && (
        <div>
          <p className="text-[10px] uppercase tracking-wider mb-1" style={{ color: t.colors.textMuted, fontFamily: t.fonts.heading }}>
            Conviction adjustments
          </p>
          {audit.map((row, i) => (
            <pre key={i} className="text-[11px] whitespace-pre-wrap break-words" style={{ color: t.colors.textSecondary }}>
              {JSON.stringify(row, null, 2)}
            </pre>
          ))}
        </div>
      )}

      {catalyst.id && (
        <p className="font-mono text-[10px]" style={{ color: t.colors.textDim }}>
          id: {catalyst.id}
        </p>
      )}
    </div>
  );
}

// ── Single catalyst card ──────────────────────────────────────────────────────

function CatalystCard({
  item,
  isRead,
  onToggleRead,
}: {
  item: Catalyst;
  isRead: boolean;
  onToggleRead: (id: string) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const [detail, setDetail] = useState<CatalystDetail | null>(null);
  const [detailLoading, setDL] = useState(false);

  const id = item.id ?? "";
  const title = item.title || fmtCategory(item.category);
  const ageStr = timeAgo(item.created_at || item.event_date || item.timestamp_ms || item.timestamp);
  const sev = sevStyle(item.severity);
  const sevNum = typeof item.severity === "string" ? parseInt(item.severity, 10) : (item.severity ?? 0);
  const instruments: string[] = Array.isArray(item.instruments) ? item.instruments : [];
  const directionColor = item.expected_direction === "bull" ? t.colors.success : item.expected_direction === "bear" ? t.colors.danger : undefined;

  const handleExpand = useCallback(() => {
    if (!expanded && !detail && id) {
      setDL(true);
      fetch(`/api/news/catalyst/${id}`)
        .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
        .then((d: CatalystDetail) => {
          setDetail(d);
          setDL(false);
        })
        .catch(() => {
          setDL(false);
        });
    }
    setExpanded((e) => !e);
  }, [expanded, detail, id]);

  const handleMarkRead = useCallback(
    (e: React.MouseEvent) => {
      e.stopPropagation();
      if (id) onToggleRead(id);
    },
    [id, onToggleRead],
  );

  return (
    <div
      className="py-3"
      style={{ borderBottom: `1px solid ${t.colors.borderLight}`, opacity: isRead ? 0.5 : 1, transition: "opacity 0.2s" }}
    >
      <div className="flex items-start gap-2 cursor-pointer" onClick={handleExpand}>
        <span
          className="flex-shrink-0 w-5 h-5 rounded text-[10px] font-bold flex items-center justify-center mt-0.5"
          style={{ background: sev.bg, color: sev.text, border: `1px solid ${sev.border}` }}
          title={`Severity ${sevNum}/5`}
        >
          {sevNum || "?"}
        </span>
        <div className="flex-1 min-w-0">
          <div className="flex items-start justify-between gap-1">
            <p className={`text-[13px] font-medium leading-snug ${expanded ? "" : "line-clamp-2"}`} style={{ color: t.colors.text }}>
              {title}
            </p>
            <div className="flex items-center gap-1.5 flex-shrink-0 ml-1">
              <button
                onClick={handleMarkRead}
                title={isRead ? "Mark unread" : "Mark read"}
                className="text-[14px] leading-none select-none hover:scale-110 transition-transform"
                style={{ color: isRead ? t.colors.primary : t.colors.textDim }}
              >
                {isRead ? "●" : "○"}
              </button>
              <span
                className="text-[10px]"
                style={{ color: t.colors.textDim, display: "inline-block", transform: expanded ? "rotate(180deg)" : "rotate(0deg)", transition: "transform 0.15s" }}
              >
                ▼
              </span>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-1.5 mt-1">
            {instruments.map((inst) => (
              <span
                key={inst}
                className="px-1.5 py-0.5 rounded text-[10px] font-medium"
                style={{ background: t.colors.primaryLight, color: t.colors.primary, border: `1px solid ${t.colors.primaryBorder}` }}
              >
                {fmtInstrument(inst)}
              </span>
            ))}
            {item.expected_direction && (
              <span className="px-1.5 py-0.5 rounded text-[10px] font-medium uppercase" style={{ color: directionColor ?? t.colors.textDim }}>
                {item.expected_direction}
              </span>
            )}
            {ageStr && (
              <span className="text-[11px]" style={{ color: t.colors.textDim }}>
                {ageStr}
              </span>
            )}
            <ThesisBadge instruments={instruments} />
          </div>
        </div>
      </div>
      {expanded && <ExpandedDetail catalyst={item} detail={detail} loading={detailLoading} />}
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

export function NewsFeed() {
  const { data, loading } = usePolling(() => getCatalysts(50), 60_000);

  const [filters, setFiltersRaw] = useState<FilterState>(DEFAULT_FILTERS);
  const [readSet, setReadSetRaw] = useState<Set<string>>(new Set());
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    setFiltersRaw(loadFilters());
    setReadSetRaw(loadReadSet());
    setHydrated(true);
  }, []);

  const setFilters = useCallback((f: FilterState) => {
    setFiltersRaw(f);
    saveFilters(f);
  }, []);

  const toggleRead = useCallback((id: string) => {
    setReadSetRaw((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      saveReadSet(next);
      return next;
    });
  }, []);

  const catalysts: Catalyst[] = (data as { catalysts: Catalyst[] } | null)?.catalysts ?? [];
  const visible = hydrated ? catalysts.filter((item) => passesFilter(item, filters, readSet)) : catalysts;

  const activeFilterCount =
    filters.severity.length + filters.market.length + filters.direction.length + (filters.readMode !== "all" ? 1 : 0);

  return (
    <div className="rounded-lg p-5" style={{ background: t.colors.surface, border: `1px solid ${t.colors.border}` }}>
      <div className="flex items-center justify-between mb-3">
        <h3
          className="text-[13px] font-medium"
          style={{ color: t.colors.textMuted, textTransform: "uppercase", letterSpacing: "0.05em", fontFamily: t.fonts.heading }}
        >
          Catalysts
        </h3>
        <div className="flex items-center gap-2">
          {activeFilterCount > 0 && (
            <button className="text-[10px] underline" style={{ color: t.colors.textDim }} onClick={() => setFilters(DEFAULT_FILTERS)}>
              clear
            </button>
          )}
          <span className="text-[11px]" style={{ color: t.colors.textDim }}>
            {visible.length}/{catalysts.length}
          </span>
        </div>
      </div>

      <FilterRow filters={filters} onChange={setFilters} />

      <div
        className="max-h-[480px] overflow-y-auto"
        style={{ scrollbarWidth: "thin", scrollbarColor: `${t.colors.border} transparent` }}
      >
        {loading || !data ? (
          <p className="text-[13px]" style={{ color: t.colors.textDim }}>
            Connecting…
          </p>
        ) : visible.length === 0 ? (
          <p className="text-[13px]" style={{ color: t.colors.textDim }}>
            {catalysts.length === 0 ? "No catalysts ingested yet" : "No catalysts match current filters"}
          </p>
        ) : (
          visible.map((item, i) => (
            <CatalystCard key={item.id ?? i} item={item} isRead={readSet.has(item.id ?? "")} onToggleRead={toggleRead} />
          ))
        )}
      </div>
    </div>
  );
}
