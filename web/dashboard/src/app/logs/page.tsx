"use client";

import {
  useState,
  useEffect,
  useRef,
  useCallback,
  useMemo,
  memo,
} from "react";
import { usePolling } from "@/lib/hooks";
import { getLogSources, getLogHistory } from "@/lib/api";
import { theme as t } from "@/lib/theme";

// ─── Types ────────────────────────────────────────────────────────────────────

interface LogLine {
  text: string;
  level: string;
}

interface FilterPreset {
  name: string;
  regex: string;
  iterators: string[];
}

interface ParsedLine {
  timestamp: string;
  level: string;
  iterator: string | null;
  message: string;
  raw: string;
}

// ─── Constants ────────────────────────────────────────────────────────────────

/** Badge label → display text */
const LEVEL_LABEL: Record<string, string> = {
  error: "ERROR",
  critical: "CRIT",
  warning: "WARN",
  warn: "WARN",
  info: "INFO",
  debug: "DBG",
};

/** Badge colours — WARN/ERROR pop, INFO/DEBUG recede */
const LEVEL_BADGE_BG: Record<string, string> = {
  error: "rgba(239,68,68,0.18)",
  critical: "rgba(239,68,68,0.18)",
  warning: "rgba(248,155,75,0.18)",
  warn: "rgba(248,155,75,0.18)",
  info: "rgba(135,202,230,0.10)",
  debug: "rgba(79,86,102,0.18)",
};

const LEVEL_BADGE_COLOR: Record<string, string> = {
  error: t.colors.danger,
  critical: t.colors.danger,
  warning: t.colors.warning,
  warn: t.colors.warning,
  info: t.colors.tertiary,
  debug: t.colors.textDim,
};

/** Text colour of the message body — lower alpha for INFO/DEBUG */
const LEVEL_TEXT_COLOR: Record<string, string> = {
  error: t.colors.danger,
  critical: t.colors.danger,
  warning: t.colors.warning,
  warn: t.colors.warning,
  info: t.colors.textSecondary,
  debug: t.colors.textDim,
};

// ─── Helpers ──────────────────────────────────────────────────────────────────

/**
 * Parse a raw log string into structured parts.
 * Handles common formats:
 *   2024-01-01 12:00:00,123 INFO message
 *   2024-01-01T12:00:00.123Z [iterator] INFO message
 *   INFO:iterator_name:message
 */
function parseLine(raw: string): ParsedLine {
  // Try: ISO-ish timestamp at the start
  // e.g. "2024-01-15 08:31:22,456 WARNING some.module: message"
  const isoMatch = raw.match(
    /^(\d{4}-\d{2}-\d{2}[\sT]\d{2}:\d{2}:\d{2}(?:[.,]\d{1,6})?(?:Z)?)\s+(?:\[([^\]]+)\]\s+)?(ERROR|CRITICAL|WARNING|WARN|INFO|DEBUG)\s*(.*)/i
  );
  if (isoMatch) {
    return {
      timestamp: isoMatch[1],
      level: isoMatch[3].toLowerCase(),
      iterator: isoMatch[2] ?? extractIteratorFromMessage(isoMatch[4]),
      message: isoMatch[4],
      raw,
    };
  }

  // Try colon-separated: "INFO:module.name:message"
  const colonMatch = raw.match(/^(ERROR|CRITICAL|WARNING|WARN|INFO|DEBUG):([^:]+):(.*)/i);
  if (colonMatch) {
    return {
      timestamp: "",
      level: colonMatch[1].toLowerCase(),
      iterator: colonMatch[2].trim(),
      message: colonMatch[3].trim(),
      raw,
    };
  }

  // Fallback: look for level word anywhere early in the line
  const levelMatch = raw.match(/\b(ERROR|CRITICAL|WARNING|WARN|INFO|DEBUG)\b/i);
  const level = levelMatch ? levelMatch[1].toLowerCase() : "info";

  return {
    timestamp: "",
    level,
    iterator: extractIteratorFromMessage(raw),
    message: raw,
    raw,
  };
}

function extractIteratorFromMessage(text: string): string | null {
  const bracketMatch = text.match(/\[([^\]]+)\]/);
  if (bracketMatch) return bracketMatch[1];
  return null;
}

function formatTimestamp(ts: string, showMs: boolean): string {
  if (!ts) return "";
  // Strip date, keep time portion
  const timeMatch = ts.match(/\d{2}:\d{2}:\d{2}(?:[.,](\d{1,6}))?/);
  if (!timeMatch) return ts.slice(-8);
  const base = timeMatch[0].slice(0, 8); // HH:MM:SS
  const ms = timeMatch[1];
  if (showMs && ms) return `${base}.${ms.slice(0, 3)}`;
  return base;
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes}B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)}KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)}MB`;
}

// ─── localStorage hook ────────────────────────────────────────────────────────

function useLocalStorage<T>(key: string, defaultValue: T): [T, (v: T) => void] {
  const [value, setValue] = useState<T>(() => {
    if (typeof window === "undefined") return defaultValue;
    try {
      const stored = localStorage.getItem(key);
      return stored ? (JSON.parse(stored) as T) : defaultValue;
    } catch {
      return defaultValue;
    }
  });

  const set = useCallback(
    (v: T) => {
      setValue(v);
      try {
        localStorage.setItem(key, JSON.stringify(v));
      } catch {
        /* ignore */
      }
    },
    [key]
  );

  return [value, set];
}

// ─── Severity filter pills ────────────────────────────────────────────────────

const ALL_LEVELS = ["error", "warning", "info", "debug"] as const;
type Level = (typeof ALL_LEVELS)[number];

const PILL_LABELS: Record<Level, string> = {
  error: "ERROR",
  warning: "WARN",
  info: "INFO",
  debug: "DBG",
};

// Canonical levels: warning covers warn/warning, error covers error/critical
function levelMatchesPill(lineLevel: string, pill: Level): boolean {
  if (pill === "error") return lineLevel === "error" || lineLevel === "critical";
  if (pill === "warning") return lineLevel === "warning" || lineLevel === "warn";
  return lineLevel === pill;
}

// ─── Highlight helper ─────────────────────────────────────────────────────────

function highlightText(text: string, re: RegExp, baseColor: string): React.ReactNode {
  const parts: { text: string; match: boolean }[] = [];
  let lastIndex = 0;
  const flags = re.flags.includes("g") ? re.flags : re.flags + "g";
  const glob = new RegExp(re.source, flags);
  let m: RegExpExecArray | null;
  while ((m = glob.exec(text)) !== null) {
    if (m.index > lastIndex) parts.push({ text: text.slice(lastIndex, m.index), match: false });
    parts.push({ text: m[0], match: true });
    lastIndex = glob.lastIndex;
    if (m[0].length === 0) glob.lastIndex++;
  }
  if (lastIndex < text.length) parts.push({ text: text.slice(lastIndex), match: false });

  return (
    <>
      {parts.map((p, i) =>
        p.match ? (
          <mark
            key={i}
            style={{
              background: "rgba(162,107,50,0.35)",
              color: t.colors.primary,
              borderRadius: "2px",
              padding: "0 1px",
            }}
          >
            {p.text}
          </mark>
        ) : (
          <span key={i} style={{ color: baseColor }}>
            {p.text}
          </span>
        )
      )}
    </>
  );
}

// ─── LogRow ───────────────────────────────────────────────────────────────────

interface LogRowProps {
  parsed: ParsedLine;
  showMs: boolean;
  highlight: RegExp | null;
  onClickIterator: (it: string) => void;
  index: number;
}

const LogRow = memo(function LogRow({
  parsed,
  showMs,
  highlight,
  onClickIterator,
  index,
}: LogRowProps) {
  const level = parsed.level || "info";
  const badgeBg = LEVEL_BADGE_BG[level] ?? LEVEL_BADGE_BG.info;
  const badgeColor = LEVEL_BADGE_COLOR[level] ?? t.colors.textSecondary;
  const msgColor = LEVEL_TEXT_COLOR[level] ?? t.colors.textSecondary;
  const label = LEVEL_LABEL[level] ?? level.toUpperCase().slice(0, 4);
  const ts = formatTimestamp(parsed.timestamp, showMs);
  const isEvenRow = index % 2 === 0;

  return (
    <div
      className="log-row flex items-start gap-0 hover:bg-[#242530] transition-colors"
      style={{
        background: isEvenRow ? "transparent" : "rgba(255,255,255,0.018)",
        minHeight: "24px",
      }}
    >
      {/* Timestamp column */}
      <div
        className="shrink-0 w-[88px] px-3 pt-[5px] text-right font-mono text-[11px] leading-[18px] select-none"
        style={{ color: t.colors.textDim }}
        title={parsed.timestamp || undefined}
      >
        {ts}
      </div>

      {/* Severity badge */}
      <div className="shrink-0 w-[52px] px-1 pt-[4px] flex justify-center">
        <span
          className="inline-block font-mono text-[10px] font-semibold px-[5px] py-[1px] rounded-[3px] leading-[14px] tracking-wide"
          style={{ background: badgeBg, color: badgeColor }}
        >
          {label}
        </span>
      </div>

      {/* Message body */}
      <div
        className="flex-1 px-2 py-[4px] font-mono text-[12px] leading-[18px] whitespace-pre-wrap break-all min-w-0"
        style={{ color: msgColor }}
      >
        {/* Iterator chip — inline before message */}
        {parsed.iterator && (
          <button
            onClick={() => onClickIterator(parsed.iterator!)}
            className="inline-block mr-1.5 mb-[1px] px-1.5 py-[1px] rounded text-[10px] font-mono align-middle leading-[14px] transition-colors hover:opacity-80"
            style={{
              background: "rgba(143,113,86,0.18)",
              color: t.colors.secondary,
              border: "1px solid rgba(143,113,86,0.25)",
              verticalAlign: "baseline",
            }}
            title={`Filter to: ${parsed.iterator}`}
          >
            {parsed.iterator}
          </button>
        )}
        {/* Message text — highlighted or plain */}
        {highlight
          ? highlightText(parsed.message || parsed.raw, highlight, msgColor)
          : (parsed.message || parsed.raw)}
      </div>
    </div>
  );
});

// ─── Skeleton loader rows ─────────────────────────────────────────────────────

function SkeletonRows() {
  return (
    <div className="py-2">
      {Array.from({ length: 12 }).map((_, i) => (
        <div
          key={i}
          className="flex items-center gap-0 h-6"
          style={{ background: i % 2 === 0 ? "transparent" : "rgba(255,255,255,0.018)" }}
        >
          <div className="shrink-0 w-[88px] px-3">
            <div
              className="h-2.5 rounded animate-pulse"
              style={{ background: t.colors.borderLight, width: `${40 + (i % 4) * 8}px` }}
            />
          </div>
          <div className="shrink-0 w-[52px] px-1 flex justify-center">
            <div
              className="h-[14px] w-[36px] rounded-[3px] animate-pulse"
              style={{ background: t.colors.borderLight }}
            />
          </div>
          <div className="flex-1 px-2 flex items-center gap-2">
            {i % 3 === 0 && (
              <div
                className="h-[14px] w-16 rounded animate-pulse"
                style={{ background: "rgba(143,113,86,0.12)" }}
              />
            )}
            <div
              className="h-2.5 rounded animate-pulse"
              style={{
                background: t.colors.borderLight,
                width: `${120 + (i * 47) % 200}px`,
                opacity: 0.6 + (i % 3) * 0.13,
              }}
            />
          </div>
        </div>
      ))}
    </div>
  );
}

// ─── Filters panel ────────────────────────────────────────────────────────────

interface FiltersPanelProps {
  allIterators: string[];
  selectedIterators: string[];
  onToggleIterator: (it: string) => void;
  onSelectAllIterators: () => void;
  onClearAllIterators: () => void;
  presets: FilterPreset[];
  onApplyPreset: (p: FilterPreset) => void;
  onDeletePreset: (name: string) => void;
  onSavePreset: (name: string) => void;
}

function FiltersPanel({
  allIterators,
  selectedIterators,
  onToggleIterator,
  onSelectAllIterators,
  onClearAllIterators,
  presets,
  onApplyPreset,
  onDeletePreset,
  onSavePreset,
}: FiltersPanelProps) {
  const [presetNameInput, setPresetNameInput] = useState("");
  const [showSaveInput, setShowSaveInput] = useState(false);
  const allSelected = selectedIterators.length === allIterators.length;
  const someSelected = selectedIterators.length > 0 && !allSelected;

  function handleSave() {
    if (!presetNameInput.trim()) return;
    onSavePreset(presetNameInput.trim());
    setPresetNameInput("");
    setShowSaveInput(false);
  }

  return (
    <div
      className="rounded-lg mb-2 overflow-hidden"
      style={{ background: t.colors.surface, border: `1px solid ${t.colors.border}` }}
    >
      <div className="p-4 flex flex-col gap-4">
        {/* Iterator multi-select */}
        {allIterators.length > 0 && (
          <div>
            <div className="flex items-center justify-between mb-2">
              <span className="text-[11px] font-medium uppercase tracking-wider" style={{ color: t.colors.textDim }}>
                Iterators
              </span>
              <div className="flex items-center gap-2">
                <button
                  onClick={onSelectAllIterators}
                  className="text-[11px] transition-colors hover:opacity-80"
                  style={{ color: t.colors.textMuted }}
                >
                  All
                </button>
                <span style={{ color: t.colors.textDim }}>·</span>
                <button
                  onClick={onClearAllIterators}
                  className="text-[11px] transition-colors hover:opacity-80"
                  style={{ color: t.colors.textMuted }}
                >
                  None
                </button>
                {someSelected && (
                  <span className="text-[11px] ml-1 px-1.5 py-0.5 rounded" style={{ background: t.colors.primaryLight, color: t.colors.primary }}>
                    {selectedIterators.length}/{allIterators.length}
                  </span>
                )}
              </div>
            </div>
            <div className="flex flex-wrap gap-1.5">
              {allIterators.map((it) => {
                const active = selectedIterators.includes(it);
                return (
                  <button
                    key={it}
                    onClick={() => onToggleIterator(it)}
                    className="px-2 py-1 rounded font-mono text-[11px] transition-all"
                    style={{
                      background: active ? "rgba(143,113,86,0.18)" : t.colors.borderLight,
                      color: active ? t.colors.secondary : t.colors.textDim,
                      border: `1px solid ${active ? "rgba(143,113,86,0.3)" : "transparent"}`,
                    }}
                  >
                    {it}
                  </button>
                );
              })}
            </div>
          </div>
        )}

        {/* Presets */}
        <div>
          <div className="flex items-center justify-between mb-2">
            <span className="text-[11px] font-medium uppercase tracking-wider" style={{ color: t.colors.textDim }}>
              Saved presets
            </span>
            {!showSaveInput && (
              <button
                onClick={() => setShowSaveInput(true)}
                className="text-[11px] transition-colors hover:opacity-80"
                style={{ color: t.colors.primary }}
              >
                + Save current view
              </button>
            )}
          </div>

          {showSaveInput && (
            <div className="flex items-center gap-2 mb-2">
              <input
                autoFocus
                type="text"
                value={presetNameInput}
                onChange={(e) => setPresetNameInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") handleSave();
                  if (e.key === "Escape") setShowSaveInput(false);
                }}
                placeholder="Preset name…"
                className="flex-1 px-2 py-1.5 rounded text-[12px] outline-none"
                style={{
                  background: t.colors.bg,
                  color: t.colors.text,
                  border: `1px solid ${t.colors.border}`,
                }}
              />
              <button
                onClick={handleSave}
                className="px-3 py-1.5 rounded text-[12px]"
                style={{
                  background: t.colors.primaryLight,
                  color: t.colors.primary,
                  border: `1px solid ${t.colors.primaryBorder}`,
                }}
              >
                Save
              </button>
              <button
                onClick={() => setShowSaveInput(false)}
                className="px-2 py-1.5 rounded text-[12px]"
                style={{ color: t.colors.textMuted }}
              >
                Cancel
              </button>
            </div>
          )}

          {presets.length === 0 && !showSaveInput && (
            <p className="text-[11px]" style={{ color: t.colors.textDim }}>
              No presets saved yet.
            </p>
          )}

          <div className="flex flex-wrap gap-1.5">
            {presets.map((p) => (
              <div key={p.name} className="flex items-center">
                <button
                  onClick={() => onApplyPreset(p)}
                  className="px-2 py-1 rounded-l text-[11px] transition-all"
                  style={{
                    background: t.colors.borderLight,
                    color: t.colors.textSecondary,
                    border: `1px solid ${t.colors.border}`,
                    borderRight: "none",
                  }}
                >
                  {p.name}
                </button>
                <button
                  onClick={() => onDeletePreset(p.name)}
                  className="px-1.5 py-1 rounded-r text-[12px] leading-none transition-all hover:opacity-100 opacity-50"
                  style={{
                    background: t.colors.borderLight,
                    color: t.colors.danger,
                    border: `1px solid ${t.colors.border}`,
                  }}
                  title="Delete preset"
                >
                  ×
                </button>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── Main page ────────────────────────────────────────────────────────────────

export default function LogsPage() {
  // ── Source / data state ──────────────────────────────────────────────────
  const [source, setSource] = useState("daemon");
  const [lines, setLines] = useState<LogLine[]>([]);
  const [loading, setLoading] = useState(true);
  const [streaming, setStreaming] = useState(false);

  // ── Persisted filter state ───────────────────────────────────────────────
  const [followTail, setFollowTail] = useLocalStorage("logs.followTail.v1", true);
  const [regexRaw, setRegexRaw] = useLocalStorage("logs.regex.v1", "");
  const [selectedIterators, setSelectedIterators] = useLocalStorage<string[]>(
    "logs.iteratorFilter.v1",
    []
  );
  const [presets, setPresets] = useLocalStorage<FilterPreset[]>("logs.presets.v1", []);

  // ── Ephemeral UI state ───────────────────────────────────────────────────
  const [regexError, setRegexError] = useState<string | null>(null);
  const [compiledRegex, setCompiledRegex] = useState<RegExp | null>(null);
  const [isAtTail, setIsAtTail] = useState(true);
  const [showFilters, setShowFilters] = useState(false);
  const [showMs, setShowMs] = useState(false);
  const [activeLevels, setActiveLevels] = useState<Set<Level>>(
    new Set(ALL_LEVELS as unknown as Level[])
  );

  const scrollRef = useRef<HTMLDivElement>(null);
  const eventSourceRef = useRef<EventSource | null>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // ── Load available sources ───────────────────────────────────────────────
  const { data: sourcesData } = usePolling(
    getLogSources as () => Promise<{ sources: { name: string; size_bytes: number }[] }>,
    30000
  );

  // ── Load history when source changes ────────────────────────────────────
  useEffect(() => {
    setLoading(true);
    async function load() {
      try {
        const resp = (await getLogHistory(source, 300)) as { lines: LogLine[] };
        setLines(resp.lines || []);
      } catch {
        setLines([]);
      } finally {
        setLoading(false);
      }
    }
    load();
  }, [source]);

  // ── SSE streaming ─────────────────────────────────────────────────────────
  useEffect(() => {
    if (!streaming) {
      eventSourceRef.current?.close();
      eventSourceRef.current = null;
      return;
    }
    const es = new EventSource(`/api/logs/stream?source=${source}`);
    eventSourceRef.current = es;
    es.addEventListener("log_line", (e) => {
      try {
        const entry = JSON.parse(e.data) as LogLine;
        setLines((prev) => [...prev.slice(-500), entry]);
      } catch {
        /* ignore */
      }
    });
    return () => {
      es.close();
      eventSourceRef.current = null;
    };
  }, [streaming, source]);

  // ── Debounced regex compilation ──────────────────────────────────────────
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      if (!regexRaw.trim()) {
        setCompiledRegex(null);
        setRegexError(null);
        return;
      }
      try {
        setCompiledRegex(new RegExp(regexRaw, "i"));
        setRegexError(null);
      } catch (e) {
        setCompiledRegex(null);
        setRegexError(e instanceof Error ? e.message : "Invalid regex");
      }
    }, 200);
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [regexRaw]);

  // ── Parse all lines (memoised) ───────────────────────────────────────────
  const parsedLines = useMemo(() => lines.map((l) => parseLine(l.text)), [lines]);

  // ── Derive all iterators ─────────────────────────────────────────────────
  const allIterators = useMemo(() => {
    const seen = new Set<string>();
    for (const p of parsedLines) {
      if (p.iterator) seen.add(p.iterator);
    }
    return [...seen].sort();
  }, [parsedLines]);

  // ── Sync selectedIterators on first load ─────────────────────────────────
  useEffect(() => {
    if (allIterators.length === 0) return;
    if (selectedIterators.length === 0) {
      setSelectedIterators(allIterators);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [allIterators]);

  // ── Filtered lines ───────────────────────────────────────────────────────
  const filteredLines = useMemo(() => {
    let result = parsedLines;

    // Level filter
    if (activeLevels.size < ALL_LEVELS.length) {
      result = result.filter((p) =>
        [...activeLevels].some((pill) => levelMatchesPill(p.level, pill))
      );
    }

    // Iterator filter
    if (
      allIterators.length > 0 &&
      selectedIterators.length > 0 &&
      selectedIterators.length < allIterators.length
    ) {
      const itSet = new Set(selectedIterators);
      result = result.filter((p) => (p.iterator ? itSet.has(p.iterator) : true));
    }

    // Regex filter
    if (compiledRegex) {
      result = result.filter((p) => compiledRegex.test(p.raw));
    }

    return result;
  }, [parsedLines, compiledRegex, selectedIterators, allIterators, activeLevels]);

  // ── Scroll tracking ───────────────────────────────────────────────────────
  const handleScroll = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
    setIsAtTail(atBottom);
  }, []);

  useEffect(() => {
    if (followTail && isAtTail && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [filteredLines, followTail, isAtTail]);

  useEffect(() => {
    if (followTail && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
      setIsAtTail(true);
    }
  }, [followTail]);

  // ── Derived ───────────────────────────────────────────────────────────────
  const sources = sourcesData?.sources || [];
  const isFiltered =
    compiledRegex !== null ||
    activeLevels.size < ALL_LEVELS.length ||
    (selectedIterators.length > 0 && selectedIterators.length < allIterators.length);

  // ── Iterator chip click — add to filter ──────────────────────────────────
  const handleClickIterator = useCallback(
    (it: string) => {
      if (!selectedIterators.includes(it)) {
        setSelectedIterators([...selectedIterators, it]);
      }
    },
    [selectedIterators, setSelectedIterators]
  );

  // ── Preset helpers ────────────────────────────────────────────────────────
  function savePreset(name: string) {
    const p: FilterPreset = { name, regex: regexRaw, iterators: selectedIterators };
    setPresets([...presets.filter((x) => x.name !== name), p]);
  }

  function applyPreset(p: FilterPreset) {
    setRegexRaw(p.regex);
    setSelectedIterators(p.iterators);
  }

  function deletePreset(name: string) {
    setPresets(presets.filter((p) => p.name !== name));
  }

  function toggleLevel(level: Level) {
    setActiveLevels((prev) => {
      const next = new Set(prev);
      if (next.has(level)) {
        next.delete(level);
      } else {
        next.add(level);
      }
      return next;
    });
  }

  function clearAllFilters() {
    setRegexRaw("");
    setSelectedIterators(allIterators);
    setActiveLevels(new Set(ALL_LEVELS as unknown as Level[]));
  }

  // ─── Render ───────────────────────────────────────────────────────────────

  return (
    <div
      className="flex flex-col h-full overflow-hidden"
      style={{ maxWidth: "1400px", margin: "0 auto", width: "100%" }}
    >
      {/* ── Top chrome ── */}
      <div
        className="shrink-0 px-5 pt-4 pb-0"
        style={{ borderBottom: `1px solid ${t.colors.borderLight}` }}
      >
        {/* Source tabs */}
        <div className="flex items-end gap-0 overflow-x-auto">
          {sources.length === 0 ? (
            /* Skeleton tabs while loading */
            ["daemon", "heartbeat", "telegram"].map((name) => (
              <div
                key={name}
                className="px-4 py-2.5 text-[13px] border-b-2 border-transparent"
                style={{ color: t.colors.textDim }}
              >
                {name}
              </div>
            ))
          ) : (
            sources.map((s) => {
              const active = source === s.name;
              return (
                <button
                  key={s.name}
                  onClick={() => setSource(s.name)}
                  className="relative px-4 py-2.5 text-[13px] font-medium transition-colors whitespace-nowrap border-b-2"
                  style={{
                    color: active ? t.colors.primary : t.colors.textMuted,
                    borderColor: active ? t.colors.primary : "transparent",
                    background: "transparent",
                  }}
                >
                  {s.name}
                  {/* File size subscript — dim, not in the tab label */}
                  <span
                    className="ml-1.5 text-[10px]"
                    style={{ color: t.colors.textDim, opacity: 0.7 }}
                  >
                    {formatFileSize(s.size_bytes)}
                  </span>
                </button>
              );
            })
          )}
        </div>
      </div>

      {/* ── Header bar: search / severity pills / tail toggle ── */}
      <div
        className="shrink-0 flex items-center gap-3 px-5 py-3"
        style={{ borderBottom: `1px solid ${t.colors.borderLight}` }}
      >
        {/* Search / regex — prominent, left */}
        <div className="relative flex-1 max-w-[380px]">
          {/* Search icon */}
          <svg
            className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 pointer-events-none"
            style={{ color: regexError ? t.colors.danger : t.colors.textDim }}
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
            strokeWidth={2}
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M21 21l-4.35-4.35m0 0A7 7 0 1 0 6.65 6.65a7 7 0 0 0 9.9 9.9z"
            />
          </svg>
          <input
            type="text"
            value={regexRaw}
            onChange={(e) => setRegexRaw(e.target.value)}
            placeholder="Filter by regex…"
            className="w-full pl-8 pr-3 py-2 rounded-lg text-[12px] font-mono outline-none transition-all"
            style={{
              background: t.colors.surface,
              color: t.colors.text,
              border: `1px solid ${regexError ? t.colors.danger : t.colors.border}`,
            }}
            title={regexError ?? undefined}
          />
          {regexError && (
            <div
              className="absolute top-full mt-1 left-0 z-20 px-2 py-1 rounded text-[11px] max-w-[300px] shadow-lg"
              style={{
                background: t.colors.dangerLight,
                color: t.colors.danger,
                border: `1px solid ${t.colors.dangerBorder}`,
              }}
            >
              {regexError}
            </div>
          )}
        </div>

        {/* Severity pills — centre */}
        <div className="flex items-center gap-1.5">
          {ALL_LEVELS.map((level) => {
            const active = activeLevels.has(level);
            const badgeBg = LEVEL_BADGE_BG[level];
            const badgeColor = LEVEL_BADGE_COLOR[level];
            return (
              <button
                key={level}
                onClick={() => toggleLevel(level)}
                className="px-2.5 py-[5px] rounded-md font-mono text-[11px] font-semibold tracking-wide transition-all"
                style={{
                  background: active ? badgeBg : "transparent",
                  color: active ? badgeColor : t.colors.textDim,
                  border: `1px solid ${active ? "rgba(255,255,255,0.08)" : t.colors.borderLight}`,
                  opacity: active ? 1 : 0.55,
                }}
                title={`Toggle ${level} logs`}
              >
                {PILL_LABELS[level]}
              </button>
            );
          })}
        </div>

        {/* Spacer */}
        <div className="flex-1" />

        {/* ms toggle */}
        <button
          onClick={() => setShowMs(!showMs)}
          className="text-[11px] px-2 py-1.5 rounded transition-colors"
          style={{
            color: showMs ? t.colors.primary : t.colors.textDim,
            background: showMs ? t.colors.primaryLight : "transparent",
          }}
          title="Show milliseconds in timestamps"
        >
          .ms
        </button>

        {/* Filters panel toggle */}
        <button
          onClick={() => setShowFilters(!showFilters)}
          className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-[12px] transition-all"
          style={{
            background: showFilters
              ? t.colors.primaryLight
              : (presets.length > 0 || allIterators.length > 0)
              ? t.colors.surface
              : "transparent",
            color: showFilters ? t.colors.primary : t.colors.textMuted,
            border: `1px solid ${showFilters ? t.colors.primaryBorder : t.colors.border}`,
          }}
          title="Show iterator filter and saved presets"
        >
          <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={1.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 3c2.755 0 5.455.232 8.083.678.533.09.917.556.917 1.096v1.044a2.25 2.25 0 0 1-.659 1.591L15.25 12.75v6.75a.75.75 0 0 1-.375.652l-3 1.75A.75.75 0 0 1 10.75 21V12.75L5.659 7.409A2.25 2.25 0 0 1 5 5.818V4.774c0-.54.384-1.006.917-1.096A48.32 48.32 0 0 1 12 3Z" />
          </svg>
          Filters
          {(allIterators.length > 0 && selectedIterators.length < allIterators.length) && (
            <span
              className="text-[10px] px-1 rounded"
              style={{ background: t.colors.primaryLight, color: t.colors.primary }}
            >
              {selectedIterators.length}/{allIterators.length}
            </span>
          )}
        </button>

        {/* Follow-tail toggle */}
        <label className="flex items-center gap-2 cursor-pointer select-none">
          <div
            className="relative w-9 h-5 rounded-full transition-colors cursor-pointer"
            style={{ background: followTail ? t.colors.primary : t.colors.border }}
            onClick={() => setFollowTail(!followTail)}
          >
            <div
              className="absolute top-0.5 w-4 h-4 rounded-full transition-transform"
              style={{
                background: "#fff",
                left: followTail ? "calc(100% - 18px)" : "2px",
              }}
            />
          </div>
          <span className="text-[12px]" style={{ color: t.colors.textSecondary }}>
            Tail
          </span>
        </label>

        {/* Stream button */}
        <button
          onClick={() => setStreaming(!streaming)}
          className="flex items-center gap-2 px-3 py-1.5 rounded-lg text-[12px] font-medium transition-all"
          style={{
            background: streaming ? t.colors.primaryLight : t.colors.surface,
            color: streaming ? t.colors.primary : t.colors.textSecondary,
            border: `1px solid ${streaming ? t.colors.primaryBorder : t.colors.border}`,
          }}
        >
          <div
            className="w-1.5 h-1.5 rounded-full"
            style={{
              background: streaming ? t.colors.primary : t.colors.textDim,
              boxShadow: streaming ? `0 0 5px ${t.colors.primary}` : "none",
            }}
          />
          {streaming ? "Live" : "Stream"}
        </button>
      </div>

      {/* ── Collapsible filters panel ── */}
      {showFilters && (
        <div className="shrink-0 px-5 pt-3">
          <FiltersPanel
            allIterators={allIterators}
            selectedIterators={selectedIterators}
            onToggleIterator={(it) =>
              setSelectedIterators(
                selectedIterators.includes(it)
                  ? selectedIterators.filter((i) => i !== it)
                  : [...selectedIterators, it]
              )
            }
            onSelectAllIterators={() => setSelectedIterators(allIterators)}
            onClearAllIterators={() => setSelectedIterators([])}
            presets={presets}
            onApplyPreset={applyPreset}
            onDeletePreset={deletePreset}
            onSavePreset={savePreset}
          />
        </div>
      )}

      {/* ── Log stream ── */}
      <div className="relative flex-1 min-h-0 px-5 py-3">
        <div
          ref={scrollRef}
          onScroll={handleScroll}
          className="h-full rounded-lg overflow-y-auto"
          style={{
            background: t.colors.surface,
            border: `1px solid ${t.colors.border}`,
            scrollbarWidth: "thin",
            scrollbarColor: `${t.colors.border} transparent`,
          }}
        >
          {loading ? (
            <SkeletonRows />
          ) : filteredLines.length === 0 ? (
            /* Empty state */
            <div className="flex flex-col items-center justify-center h-full min-h-[200px] gap-3 py-16">
              <svg
                className="w-8 h-8"
                style={{ color: t.colors.textDim }}
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
                strokeWidth={1.5}
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  d="M3.98 8.223A10.477 10.477 0 0 0 1.934 12C3.226 16.338 7.244 19.5 12 19.5c.993 0 1.953-.138 2.863-.395M6.228 6.228A10.451 10.451 0 0 1 12 4.5c4.756 0 8.773 3.162 10.065 7.498a10.522 10.522 0 0 1-4.293 5.774M6.228 6.228 3 3m3.228 3.228 3.65 3.65m7.894 7.894L21 21m-3.228-3.228-3.65-3.65m0 0a3 3 0 1 0-4.243-4.243m4.242 4.242L9.88 9.88"
                />
              </svg>
              <p className="text-[14px]" style={{ color: t.colors.textDim }}>
                {lines.length > 0
                  ? "No log lines match current filters."
                  : "No log entries. Select a source or start streaming."}
              </p>
              {isFiltered && (
                <button
                  onClick={clearAllFilters}
                  className="text-[12px] underline transition-colors hover:opacity-80"
                  style={{ color: t.colors.primary }}
                >
                  Clear filters
                </button>
              )}
            </div>
          ) : (
            <div className="py-1">
              {filteredLines.map((parsed, i) => (
                <LogRow
                  key={i}
                  parsed={parsed}
                  showMs={showMs}
                  highlight={compiledRegex}
                  onClickIterator={handleClickIterator}
                  index={i}
                />
              ))}
            </div>
          )}
        </div>

        {/* ── "Jump to live" floating button ── */}
        {!isAtTail && !loading && (
          <button
            onClick={() => {
              setFollowTail(true);
              if (scrollRef.current)
                scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
              setIsAtTail(true);
            }}
            className="absolute bottom-7 right-9 flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[12px] font-medium shadow-lg transition-all"
            style={{ background: t.colors.primary, color: "#fff" }}
          >
            <svg
              className="w-3 h-3"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
              strokeWidth={2}
            >
              <path strokeLinecap="round" strokeLinejoin="round" d="M19 14l-7 7m0 0l-7-7m7 7V3" />
            </svg>
            Jump to live
          </button>
        )}
      </div>

      {/* ── Footer stats ── */}
      <div
        className="shrink-0 flex items-center justify-between px-5 py-2"
        style={{ borderTop: `1px solid ${t.colors.borderLight}` }}
      >
        <span className="text-[11px]" style={{ color: t.colors.textDim }}>
          {isFiltered
            ? `${filteredLines.length} of ${lines.length} lines · ${source}`
            : `${lines.length} lines · ${source}`}
          {streaming && (
            <span style={{ color: t.colors.primary }}> · streaming</span>
          )}
        </span>
        <button
          onClick={() => setLines([])}
          className="text-[11px] px-2 py-1 rounded transition-colors hover:opacity-80"
          style={{ color: t.colors.textDim }}
        >
          Clear buffer
        </button>
      </div>
    </div>
  );
}
