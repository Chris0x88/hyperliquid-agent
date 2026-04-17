"use client";

import { useState, useEffect, useRef, useCallback, useMemo } from "react";
import { usePolling } from "@/lib/hooks";
import { getLogSources, getLogHistory } from "@/lib/api";
import { theme as t } from "@/lib/theme";

interface LogLine {
  text: string;
  level: string;
}

interface FilterPreset {
  name: string;
  regex: string;
  iterators: string[];
}

const LEVEL_COLORS: Record<string, string> = {
  error: t.colors.danger,
  critical: t.colors.danger,
  warning: t.colors.warning,
  warn: t.colors.warning,
  info: t.colors.tertiary,
  debug: t.colors.textDim,
};

// Parse iterator name from a log line. Lines often look like:
//   2024-01-01 12:00:00 [iterator_name] INFO message
//   or: INFO:iterator_name:message
function parseIterator(text: string): string | null {
  // bracket form: [iterator_name]
  const bracketMatch = text.match(/\[([^\]]+)\]/);
  if (bracketMatch) return bracketMatch[1];
  // colon form: LEVEL:iterator_name:
  const colonMatch = text.match(/(?:INFO|DEBUG|WARNING|ERROR|CRITICAL):([^:]+):/i);
  if (colonMatch) return colonMatch[1].trim();
  return null;
}

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

  const set = useCallback((v: T) => {
    setValue(v);
    try { localStorage.setItem(key, JSON.stringify(v)); } catch { /* ignore */ }
  }, [key]);

  return [value, set];
}

function LogEntry({ line, highlight }: { line: LogLine; highlight?: RegExp }) {
  const color = LEVEL_COLORS[line.level] || t.colors.textSecondary;
  if (!highlight) {
    return (
      <div className="py-0.5 px-3 hover:bg-[#1e1f26] font-mono text-[12px] leading-5 whitespace-pre-wrap break-all" style={{ color }}>
        {line.text}
      </div>
    );
  }

  // Split text by regex and highlight matches
  const parts: { text: string; match: boolean }[] = [];
  let lastIndex = 0;
  let m: RegExpExecArray | null;
  const re = new RegExp(highlight.source, highlight.flags.includes("g") ? highlight.flags : highlight.flags + "g");
  while ((m = re.exec(line.text)) !== null) {
    if (m.index > lastIndex) parts.push({ text: line.text.slice(lastIndex, m.index), match: false });
    parts.push({ text: m[0], match: true });
    lastIndex = re.lastIndex;
    if (m[0].length === 0) { re.lastIndex++; } // avoid infinite loop on zero-length match
  }
  if (lastIndex < line.text.length) parts.push({ text: line.text.slice(lastIndex), match: false });

  return (
    <div className="py-0.5 px-3 hover:bg-[#1e1f26] font-mono text-[12px] leading-5 whitespace-pre-wrap break-all" style={{ color }}>
      {parts.map((p, i) =>
        p.match ? (
          <mark key={i} style={{ background: "rgba(162,107,50,0.4)", color, borderRadius: "2px" }}>{p.text}</mark>
        ) : (
          <span key={i}>{p.text}</span>
        )
      )}
    </div>
  );
}

export default function LogsPage() {
  const [source, setSource] = useState("daemon");
  const [lines, setLines] = useState<LogLine[]>([]);
  const [streaming, setStreaming] = useState(false);
  const [followTail, setFollowTail] = useLocalStorage("logs.followTail.v1", true);
  const [regexRaw, setRegexRaw] = useLocalStorage("logs.regex.v1", "");
  const [regexError, setRegexError] = useState<string | null>(null);
  const [compiledRegex, setCompiledRegex] = useState<RegExp | null>(null);
  const [selectedIterators, setSelectedIterators] = useLocalStorage<string[]>("logs.iteratorFilter.v1", []);
  const [presets, setPresets] = useLocalStorage<FilterPreset[]>("logs.presets.v1", []);
  const [presetNameInput, setPresetNameInput] = useState("");
  const [showPresetInput, setShowPresetInput] = useState(false);
  const [isAtTail, setIsAtTail] = useState(true);
  const scrollRef = useRef<HTMLDivElement>(null);
  const eventSourceRef = useRef<EventSource | null>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Load available sources
  const { data: sourcesData } = usePolling(
    getLogSources as () => Promise<{ sources: { name: string; size_bytes: number }[] }>,
    30000,
  );

  // Load history when source changes
  useEffect(() => {
    async function load() {
      try {
        const resp = (await getLogHistory(source, 300)) as { lines: LogLine[] };
        setLines(resp.lines || []);
      } catch {
        setLines([]);
      }
    }
    load();
  }, [source]);

  // SSE streaming
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
      } catch { /* ignore */ }
    });
    return () => {
      es.close();
      eventSourceRef.current = null;
    };
  }, [streaming, source]);

  // Debounced regex compilation
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
    return () => { if (debounceRef.current) clearTimeout(debounceRef.current); };
  }, [regexRaw]);

  // Derive iterators from log lines
  const allIterators = useMemo(() => {
    const seen = new Set<string>();
    for (const l of lines) {
      const it = parseIterator(l.text);
      if (it) seen.add(it);
    }
    return [...seen].sort();
  }, [lines]);

  // Sync selectedIterators: add new iterators as selected by default
  useEffect(() => {
    if (allIterators.length === 0) return;
    const current = new Set(selectedIterators);
    const missing = allIterators.filter((it) => !current.has(it));
    // only update if something is genuinely missing (avoid loop)
    if (missing.length > 0 && selectedIterators.length === 0) {
      setSelectedIterators(allIterators);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [allIterators]);

  // Filtered lines
  const filteredLines = useMemo(() => {
    let result = lines;
    // Iterator filter
    if (allIterators.length > 0 && selectedIterators.length > 0 && selectedIterators.length < allIterators.length) {
      const itSet = new Set(selectedIterators);
      result = result.filter((l) => {
        const it = parseIterator(l.text);
        return it ? itSet.has(it) : true;
      });
    }
    // Regex filter
    if (compiledRegex) {
      result = result.filter((l) => compiledRegex.test(l.text));
    }
    return result;
  }, [lines, compiledRegex, selectedIterators, allIterators]);

  // Track scroll position to know if we're at tail
  const handleScroll = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
    setIsAtTail(atBottom);
  }, []);

  // Auto-scroll to bottom when followTail is on and new lines arrive
  useEffect(() => {
    if (followTail && isAtTail && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [filteredLines, followTail, isAtTail]);

  // Scroll to tail when followTail is toggled on
  useEffect(() => {
    if (followTail && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
      setIsAtTail(true);
    }
  }, [followTail]);

  const sources = sourcesData?.sources || [];

  // Preset management
  function savePreset() {
    if (!presetNameInput.trim()) return;
    const newPreset: FilterPreset = {
      name: presetNameInput.trim(),
      regex: regexRaw,
      iterators: selectedIterators,
    };
    setPresets([...presets.filter((p) => p.name !== newPreset.name), newPreset]);
    setPresetNameInput("");
    setShowPresetInput(false);
  }

  function applyPreset(p: FilterPreset) {
    setRegexRaw(p.regex);
    setSelectedIterators(p.iterators);
  }

  function deletePreset(name: string) {
    setPresets(presets.filter((p) => p.name !== name));
  }

  function toggleIterator(it: string) {
    setSelectedIterators(
      selectedIterators.includes(it)
        ? selectedIterators.filter((i) => i !== it)
        : [...selectedIterators, it]
    );
  }

  return (
    <div className="p-8 max-w-[1400px] h-full flex flex-col">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h2 className="text-2xl font-semibold" style={{ color: t.colors.text, fontFamily: t.fonts.heading }}>
            Logs
          </h2>
          <p className="text-[13px] mt-1" style={{ color: t.colors.textMuted }}>
            Real-time log streaming and history
          </p>
        </div>
        <div className="flex items-center gap-3">
          {/* Follow tail toggle */}
          <label className="flex items-center gap-2 cursor-pointer select-none">
            <div
              className="relative w-9 h-5 rounded-full transition-colors"
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
            <span className="text-[12px]" style={{ color: t.colors.textSecondary }}>Follow tail</span>
          </label>
          {/* Stream button */}
          <button
            onClick={() => setStreaming(!streaming)}
            className="flex items-center gap-2 px-4 py-2 rounded-lg text-[13px] font-medium transition-all"
            style={{
              background: streaming ? t.colors.primaryLight : t.colors.surface,
              color: streaming ? t.colors.primary : t.colors.textSecondary,
              border: `1px solid ${streaming ? t.colors.primaryBorder : t.colors.border}`,
            }}
          >
            <div className="w-2 h-2 rounded-full" style={{
              background: streaming ? t.colors.primary : t.colors.textDim,
              boxShadow: streaming ? `0 0 6px ${t.colors.primary}` : "none",
            }} />
            {streaming ? "Streaming" : "Start Stream"}
          </button>
        </div>
      </div>

      {/* Source tabs */}
      <div className="flex gap-1 mb-4 overflow-x-auto pb-1">
        {sources.map((s) => (
          <button
            key={s.name}
            onClick={() => setSource(s.name)}
            className="px-3 py-1.5 rounded-lg text-[12px] font-medium whitespace-nowrap transition-all"
            style={source === s.name ? {
              background: t.colors.primaryLight,
              color: t.colors.primary,
              border: `1px solid ${t.colors.primaryBorder}`,
            } : {
              background: "transparent",
              color: t.colors.textMuted,
              border: `1px solid transparent`,
            }}
          >
            {s.name}
            <span className="ml-1.5 text-[10px] opacity-60">
              {(s.size_bytes / 1024).toFixed(0)}KB
            </span>
          </button>
        ))}
      </div>

      {/* Filter toolbar */}
      <div className="flex flex-col gap-2 mb-4">
        {/* Row 1: regex + iterator dropdown */}
        <div className="flex items-center gap-3">
          {/* Regex input */}
          <div className="relative flex-1 max-w-[400px]">
            <input
              type="text"
              value={regexRaw}
              onChange={(e) => setRegexRaw(e.target.value)}
              placeholder="Filter by regex…"
              className="w-full px-3 py-1.5 rounded-lg text-[12px] font-mono outline-none transition-all"
              style={{
                background: t.colors.surface,
                color: t.colors.text,
                border: `1px solid ${regexError ? t.colors.danger : t.colors.border}`,
              }}
              title={regexError ?? undefined}
            />
            {regexError && (
              <div
                className="absolute top-full mt-1 left-0 z-20 px-2 py-1 rounded text-[11px] max-w-[300px]"
                style={{ background: t.colors.dangerLight, color: t.colors.danger, border: `1px solid ${t.colors.dangerBorder}` }}
              >
                {regexError}
              </div>
            )}
          </div>

          {/* Iterator multi-select dropdown */}
          {allIterators.length > 0 && (
            <IteratorDropdown
              all={allIterators}
              selected={selectedIterators}
              onToggle={toggleIterator}
              onSelectAll={() => setSelectedIterators(allIterators)}
              onClearAll={() => setSelectedIterators([])}
            />
          )}

          {/* Preset: save button */}
          <div className="relative">
            {showPresetInput ? (
              <div className="flex items-center gap-1">
                <input
                  autoFocus
                  type="text"
                  value={presetNameInput}
                  onChange={(e) => setPresetNameInput(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter") savePreset(); if (e.key === "Escape") setShowPresetInput(false); }}
                  placeholder="Preset name…"
                  className="px-2 py-1.5 rounded-lg text-[12px] outline-none w-[140px]"
                  style={{ background: t.colors.surface, color: t.colors.text, border: `1px solid ${t.colors.border}` }}
                />
                <button onClick={savePreset} className="px-2 py-1.5 rounded-lg text-[12px]" style={{ background: t.colors.primaryLight, color: t.colors.primary, border: `1px solid ${t.colors.primaryBorder}` }}>
                  Save
                </button>
                <button onClick={() => setShowPresetInput(false)} className="px-2 py-1.5 rounded-lg text-[12px]" style={{ color: t.colors.textMuted }}>
                  Cancel
                </button>
              </div>
            ) : (
              <button
                onClick={() => setShowPresetInput(true)}
                className="px-3 py-1.5 rounded-lg text-[12px] transition-all"
                style={{ background: t.colors.surface, color: t.colors.textSecondary, border: `1px solid ${t.colors.border}` }}
              >
                + Save view
              </button>
            )}
          </div>
        </div>

        {/* Row 2: presets chips */}
        {presets.length > 0 && (
          <div className="flex items-center gap-1.5 flex-wrap">
            <span className="text-[11px]" style={{ color: t.colors.textDim }}>Presets:</span>
            {presets.map((p) => (
              <div key={p.name} className="flex items-center gap-0.5">
                <button
                  onClick={() => applyPreset(p)}
                  className="px-2 py-0.5 rounded text-[11px] transition-all"
                  style={{ background: t.colors.surface, color: t.colors.textSecondary, border: `1px solid ${t.colors.border}` }}
                >
                  {p.name}
                </button>
                <button
                  onClick={() => deletePreset(p.name)}
                  className="w-4 h-4 flex items-center justify-center rounded text-[10px] transition-all hover:opacity-100 opacity-40"
                  style={{ color: t.colors.danger }}
                  title="Delete preset"
                >
                  ×
                </button>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Log output — relative container for floating button */}
      <div className="relative flex-1 min-h-0">
        <div
          ref={scrollRef}
          onScroll={handleScroll}
          className="h-full min-h-[400px] rounded-lg overflow-y-auto"
          style={{
            background: t.colors.surface,
            border: `1px solid ${t.colors.border}`,
            scrollbarWidth: "thin",
            scrollbarColor: `${t.colors.border} transparent`,
          }}
        >
          {filteredLines.length === 0 ? (
            <div className="p-8 text-center">
              <p className="text-[13px]" style={{ color: t.colors.textDim }}>
                {lines.length > 0 ? "No lines match the current filter." : "No log entries. Select a source or start streaming."}
              </p>
            </div>
          ) : (
            <div className="py-2">
              {filteredLines.map((line, i) => (
                <LogEntry key={i} line={line} highlight={compiledRegex ?? undefined} />
              ))}
            </div>
          )}
        </div>

        {/* "Back to live" floating button */}
        {!isAtTail && (
          <button
            onClick={() => {
              setFollowTail(true);
              if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
              setIsAtTail(true);
            }}
            className="absolute bottom-4 right-4 flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[12px] font-medium shadow-lg transition-all"
            style={{ background: t.colors.primary, color: "#fff" }}
          >
            <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M19 14l-7 7m0 0l-7-7m7 7V3" />
            </svg>
            Back to live
          </button>
        )}
      </div>

      {/* Footer stats */}
      <div className="flex items-center justify-between mt-3">
        <span className="text-[11px]" style={{ color: t.colors.textDim }}>
          {compiledRegex || (selectedIterators.length > 0 && selectedIterators.length < allIterators.length)
            ? `Showing ${filteredLines.length} of ${lines.length} lines`
            : `${lines.length} lines`}
          {" | "}Source: {source}
        </span>
        <button
          onClick={() => setLines([])}
          className="text-[11px] px-2 py-1 rounded hover:bg-[#1e1f26] transition-colors"
          style={{ color: t.colors.textDim }}
        >
          Clear
        </button>
      </div>
    </div>
  );
}

// --- Iterator multi-select dropdown ---

interface IteratorDropdownProps {
  all: string[];
  selected: string[];
  onToggle: (it: string) => void;
  onSelectAll: () => void;
  onClearAll: () => void;
}

function IteratorDropdown({ all, selected, onToggle, onSelectAll, onClearAll }: IteratorDropdownProps) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handler(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  const allSelected = selected.length === all.length;

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[12px] transition-all"
        style={{
          background: t.colors.surface,
          color: t.colors.textSecondary,
          border: `1px solid ${t.colors.border}`,
        }}
      >
        <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={1.5}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M3 4.5h14.25M3 9h9.75M3 13.5h9.75m4.5-4.5v12m0 0l-3.75-3.75M17.25 21L21 17.25" />
        </svg>
        Iterators
        {!allSelected && (
          <span className="px-1 rounded text-[10px]" style={{ background: t.colors.primaryLight, color: t.colors.primary }}>
            {selected.length}/{all.length}
          </span>
        )}
        <svg className="w-3 h-3 opacity-50" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d={open ? "M5 15l7-7 7 7" : "M19 9l-7 7-7-7"} />
        </svg>
      </button>
      {open && (
        <div
          className="absolute top-full mt-1 left-0 z-30 rounded-lg shadow-lg min-w-[200px] max-h-[260px] overflow-y-auto"
          style={{ background: t.colors.bg, border: `1px solid ${t.colors.border}` }}
        >
          <div className="flex gap-1 p-2 border-b" style={{ borderColor: t.colors.borderLight }}>
            <button onClick={onSelectAll} className="flex-1 px-2 py-1 rounded text-[11px]" style={{ background: t.colors.surface, color: t.colors.textSecondary }}>
              All
            </button>
            <button onClick={onClearAll} className="flex-1 px-2 py-1 rounded text-[11px]" style={{ background: t.colors.surface, color: t.colors.textSecondary }}>
              None
            </button>
          </div>
          {all.map((it) => (
            <label
              key={it}
              className="flex items-center gap-2 px-3 py-1.5 cursor-pointer hover:bg-[#1e1f26] transition-colors"
            >
              <input
                type="checkbox"
                checked={selected.includes(it)}
                onChange={() => onToggle(it)}
                className="w-3.5 h-3.5 rounded"
                style={{ accentColor: t.colors.primary }}
              />
              <span className="text-[12px] font-mono" style={{ color: t.colors.textSecondary }}>{it}</span>
            </label>
          ))}
          {all.length === 0 && (
            <p className="px-3 py-2 text-[11px]" style={{ color: t.colors.textDim }}>
              No iterators detected yet
            </p>
          )}
        </div>
      )}
    </div>
  );
}
