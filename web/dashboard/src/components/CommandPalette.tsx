"use client";

/**
 * CommandPalette — global Cmd+K (Mac) / Ctrl+K (other) shortcut.
 *
 * Command registry pattern: add new entries to COMMANDS (or call registerCommand)
 * for one-liner extensibility. Each command is a plain object with:
 *   - id: string (unique)
 *   - label: string (shown in list)
 *   - group?: string (shown as section header, purely cosmetic)
 *   - keywords?: string[] (extra fuzzy-match tokens)
 *   - action: (router, dispatch?) => void
 */

import {
  useState,
  useEffect,
  useRef,
  useMemo,
  useCallback,
  type KeyboardEvent,
} from "react";
import { useRouter } from "next/navigation";
import { theme as t } from "@/lib/theme";

// ---------------------------------------------------------------------------
// Command registry types
// ---------------------------------------------------------------------------

export interface Command {
  id: string;
  label: string;
  group?: string;
  /** Extra tokens added to the fuzzy-match index beyond the label */
  keywords?: string[];
  action: (router: ReturnType<typeof useRouter>) => void | Promise<void>;
}

// ---------------------------------------------------------------------------
// Command list
// ---------------------------------------------------------------------------

const APPROVED_MARKETS = ["BTC", "BRENTOIL", "GOLD", "SILVER", "CL", "SP500"] as const;
const THESIS_MARKETS = ["BTC", "BRENTOIL", "GOLD", "SILVER"] as const;
const TOP_PAGES = [
  { label: "Dashboard", href: "/" },
  { label: "Control", href: "/control" },
  { label: "Strategies", href: "/strategies" },
  { label: "Alerts", href: "/alerts" },
  { label: "Charts", href: "/charts" },
  { label: "Logs", href: "/logs" },
] as const;

// Iterators list — kept in sync with daemon; extended at runtime via log parsing
// (static fallback so palette works before any logs are loaded)
const KNOWN_ITERATORS = [
  "conviction_engine",
  "catalyst_deleverage",
  "news_ingest",
  "heartbeat",
  "vault_rebalancer",
  "position_monitor",
  "funding_tracker",
] as const;

function buildStaticCommands(): Command[] {
  const cmds: Command[] = [];

  // Navigation — top-level pages
  for (const page of TOP_PAGES) {
    cmds.push({
      id: `nav:${page.href}`,
      label: `Go to ${page.label}`,
      group: "Navigation",
      keywords: [page.label.toLowerCase(), "navigate", "go"],
      action: (router) => router.push(page.href),
    });
  }

  // Go to Charts: <market>
  for (const market of APPROVED_MARKETS) {
    cmds.push({
      id: `charts:${market}`,
      label: `Go to Charts: ${market}`,
      group: "Charts",
      keywords: ["chart", "candle", market.toLowerCase()],
      action: (router) => router.push(`/charts?market=${market}`),
    });
  }

  // Go to Logs: <iterator>
  for (const it of KNOWN_ITERATORS) {
    cmds.push({
      id: `logs:${it}`,
      label: `Go to Logs: ${it}`,
      group: "Logs",
      keywords: ["log", "stream", it],
      action: (router) => {
        // Pre-apply iterator filter via localStorage then navigate
        try {
          localStorage.setItem("logs.iteratorFilter.v1", JSON.stringify([it]));
        } catch { /* ignore */ }
        router.push("/logs");
      },
    });
  }

  // Open thesis editor
  for (const market of THESIS_MARKETS) {
    cmds.push({
      id: `thesis:${market}`,
      label: `Open ${market} thesis editor`,
      group: "Thesis",
      keywords: ["thesis", "edit", market.toLowerCase(), "conviction"],
      action: (router) => router.push(`/control/thesis/${market}`),
    });
  }

  // Toggle iterator kill switch
  for (const it of KNOWN_ITERATORS) {
    cmds.push({
      id: `kill:${it}`,
      label: `Toggle kill switch: ${it}`,
      group: "Control",
      keywords: ["kill", "toggle", "disable", "enable", it],
      action: (router) => router.push(`/control?focus=${it}`),
    });
  }

  // Misc
  cmds.push({
    id: "hwm:reset",
    label: "Reset HWM",
    group: "Control",
    keywords: ["hwm", "high water mark", "reset", "drawdown"],
    action: (router) => router.push("/control?modal=hwm"),
  });

  cmds.push({
    id: "catalysts:today",
    label: "View today's catalysts",
    group: "Navigation",
    keywords: ["catalyst", "news", "events", "today"],
    action: (router) => {
      router.push("/");
      // Give the page time to mount then scroll
      setTimeout(() => {
        document.getElementById("catalysts-section")?.scrollIntoView({ behavior: "smooth" });
      }, 300);
    },
  });

  cmds.push({
    id: "checklist:evening",
    label: "Show /evening checklist",
    group: "Checklist",
    keywords: ["checklist", "evening", "wrap", "daily"],
    // eslint-disable-next-line @typescript-eslint/no-unused-vars
    action: (_r) => {
      // Handled specially — action dispatches a window event to trigger in-palette display
      window.dispatchEvent(new CustomEvent("cmdpalette:checklist", { detail: { type: "evening" } }));
    },
  });

  return cmds;
}

// Mutable registry — allows runtime extension
const _registry: Command[] = buildStaticCommands();

/** One-liner to add new commands at runtime */
export function registerCommand(cmd: Command) {
  const idx = _registry.findIndex((c) => c.id === cmd.id);
  if (idx >= 0) _registry[idx] = cmd;
  else _registry.push(cmd);
}

// ---------------------------------------------------------------------------
// Fuzzy match — simple substring / token scoring
// ---------------------------------------------------------------------------

function fuzzyScore(query: string, cmd: Command): number {
  if (!query) return 1;
  const q = query.toLowerCase();
  const label = cmd.label.toLowerCase();
  const tokens = [label, ...(cmd.keywords ?? []), cmd.group?.toLowerCase() ?? ""];
  const full = tokens.join(" ");

  // Exact label match
  if (label === q) return 100;
  // Label starts with query
  if (label.startsWith(q)) return 80;
  // Label contains query
  if (label.includes(q)) return 60;
  // Any token contains query
  if (tokens.some((tok) => tok.includes(q))) return 40;
  // All query words present somewhere
  const words = q.split(/\s+/);
  if (words.every((w) => full.includes(w))) return 20;
  return 0;
}

function filterCommands(query: string, registry: Command[]): Command[] {
  if (!query.trim()) return registry;
  return registry
    .map((cmd) => ({ cmd, score: fuzzyScore(query, cmd) }))
    .filter((x) => x.score > 0)
    .sort((a, b) => b.score - a.score)
    .map((x) => x.cmd);
}

// ---------------------------------------------------------------------------
// Checklist result modal helper
// ---------------------------------------------------------------------------

interface ChecklistResult {
  lines: string[];
  loading: boolean;
  error: string | null;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function CommandPalette() {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [activeIdx, setActiveIdx] = useState(0);
  const [checklist, setChecklist] = useState<ChecklistResult | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  const commands = useMemo(() => filterCommands(query, _registry), [query]);

  // Clamp active index when list changes
  useEffect(() => {
    setActiveIdx((prev) => Math.min(prev, Math.max(0, commands.length - 1)));
  }, [commands.length]);

  // Scroll active item into view
  useEffect(() => {
    const item = listRef.current?.children[activeIdx] as HTMLElement | undefined;
    item?.scrollIntoView({ block: "nearest" });
  }, [activeIdx]);

  // Cmd+K / Ctrl+K handler — don't steal from contenteditable / inputs
  useEffect(() => {
    function onKeyDown(e: globalThis.KeyboardEvent) {
      const mac = navigator.platform.toLowerCase().includes("mac");
      const trigger = mac ? e.metaKey && e.key === "k" : e.ctrlKey && e.key === "k";
      if (!trigger) return;

      // Don't open when user is typing in a focused input/textarea/contenteditable
      // UNLESS they're already in the palette input
      const active = document.activeElement;
      if (
        active &&
        active !== inputRef.current &&
        (active.tagName === "INPUT" ||
          active.tagName === "TEXTAREA" ||
          (active as HTMLElement).isContentEditable)
      ) {
        return; // let the keydown propagate naturally
      }

      e.preventDefault();
      setOpen((prev) => !prev);
    }

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  // Focus input when opened
  useEffect(() => {
    if (open) {
      setQuery("");
      setActiveIdx(0);
      setChecklist(null);
      setTimeout(() => inputRef.current?.focus(), 0);
    }
  }, [open]);

  // Checklist event
  useEffect(() => {
    async function handler(e: Event) {
      const detail = (e as CustomEvent).detail as { type: string };
      setChecklist({ lines: [], loading: true, error: null });
      try {
        const res = await fetch(`/api/checklist/${detail.type}`);
        if (!res.ok) throw new Error(`${res.status}`);
        const data = (await res.json()) as { lines?: string[]; items?: string[] };
        const lines = data.lines ?? data.items ?? [];
        setChecklist({ lines, loading: false, error: null });
      } catch (err) {
        setChecklist({ lines: [], loading: false, error: String(err) });
      }
    }
    window.addEventListener("cmdpalette:checklist", handler);
    return () => window.removeEventListener("cmdpalette:checklist", handler);
  }, []);

  const close = useCallback(() => {
    setOpen(false);
    setChecklist(null);
  }, []);

  const execute = useCallback(
    (cmd: Command) => {
      close();
      cmd.action(router);
    },
    [close, router]
  );

  const onKeyDown = useCallback(
    (e: KeyboardEvent<HTMLInputElement>) => {
      if (e.key === "Escape") { close(); return; }
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setActiveIdx((prev) => Math.min(prev + 1, commands.length - 1));
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        setActiveIdx((prev) => Math.max(prev - 1, 0));
      } else if (e.key === "Enter") {
        e.preventDefault();
        const cmd = commands[activeIdx];
        if (cmd) execute(cmd);
      }
    },
    [close, commands, activeIdx, execute]
  );

  if (!open) return null;

  // Group commands for rendering
  const grouped: { group: string; items: Command[] }[] = [];
  const seenGroups = new Map<string, number>();
  for (const cmd of commands) {
    const g = cmd.group ?? "Other";
    if (!seenGroups.has(g)) {
      seenGroups.set(g, grouped.length);
      grouped.push({ group: g, items: [] });
    }
    grouped[seenGroups.get(g)!].items.push(cmd);
  }

  // Flat command list with their original index for keyboard nav
  const flatCommands = grouped.flatMap((g) => g.items);

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 z-[9998]"
        style={{ background: "rgba(0,0,0,0.6)", backdropFilter: "blur(2px)" }}
        onClick={close}
      />

      {/* Modal */}
      <div
        className="fixed z-[9999] left-1/2 top-[20vh] -translate-x-1/2 w-full max-w-[600px] rounded-xl shadow-2xl overflow-hidden flex flex-col"
        style={{
          background: t.colors.bg,
          border: `1px solid ${t.colors.border}`,
          maxHeight: "60vh",
        }}
        role="dialog"
        aria-modal="true"
        aria-label="Command palette"
      >
        {/* Search input */}
        <div
          className="flex items-center gap-3 px-4 py-3"
          style={{ borderBottom: `1px solid ${t.colors.border}` }}
        >
          <svg className="w-4 h-4 flex-shrink-0" style={{ color: t.colors.textMuted }} fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={1.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z" />
          </svg>
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={(e) => { setQuery(e.target.value); setActiveIdx(0); }}
            onKeyDown={onKeyDown}
            placeholder="Search commands…"
            className="flex-1 bg-transparent outline-none text-[14px]"
            style={{ color: t.colors.text, caretColor: t.colors.primary }}
            autoComplete="off"
            spellCheck={false}
          />
          <kbd
            className="hidden sm:flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[10px] font-mono"
            style={{ background: t.colors.surface, color: t.colors.textDim, border: `1px solid ${t.colors.border}` }}
          >
            esc
          </kbd>
        </div>

        {/* Checklist result pane */}
        {checklist && (
          <div className="px-4 py-3 overflow-y-auto text-[12px] font-mono" style={{ color: t.colors.textSecondary, borderBottom: `1px solid ${t.colors.border}` }}>
            {checklist.loading && <span style={{ color: t.colors.textDim }}>Loading checklist…</span>}
            {checklist.error && <span style={{ color: t.colors.danger }}>Error: {checklist.error}</span>}
            {!checklist.loading && !checklist.error && (
              checklist.lines.length === 0
                ? <span style={{ color: t.colors.textDim }}>No items returned.</span>
                : checklist.lines.map((l, i) => <div key={i}>{l}</div>)
            )}
          </div>
        )}

        {/* Command list */}
        <div ref={listRef} className="overflow-y-auto flex-1" style={{ scrollbarWidth: "thin", scrollbarColor: `${t.colors.border} transparent` }}>
          {grouped.length === 0 && (
            <div className="px-4 py-8 text-center text-[13px]" style={{ color: t.colors.textDim }}>
              No commands match &ldquo;{query}&rdquo;
            </div>
          )}
          {grouped.map((grp) => (
            <div key={grp.group}>
              {/* Section header (only when there are multiple groups or user has typed a query) */}
              {(grouped.length > 1 || !query) && (
                <div
                  className="px-4 pt-2.5 pb-0.5 text-[10px] uppercase tracking-wider font-semibold"
                  style={{ color: t.colors.textDim }}
                >
                  {grp.group}
                </div>
              )}
              {grp.items.map((cmd) => {
                const flatIdx = flatCommands.indexOf(cmd);
                const isActive = flatIdx === activeIdx;
                return (
                  <button
                    key={cmd.id}
                    className="w-full flex items-center gap-3 px-4 py-2.5 text-left text-[13px] transition-colors"
                    style={{
                      background: isActive ? t.colors.primaryLight : "transparent",
                      color: isActive ? t.colors.primary : t.colors.textSecondary,
                      borderLeft: isActive ? `2px solid ${t.colors.primary}` : "2px solid transparent",
                    }}
                    onMouseEnter={() => setActiveIdx(flatIdx)}
                    onClick={() => execute(cmd)}
                  >
                    <CmdIcon id={cmd.id} active={isActive} />
                    <span>{cmd.label}</span>
                  </button>
                );
              })}
            </div>
          ))}
        </div>

        {/* Footer hints */}
        <div
          className="px-4 py-2 flex items-center gap-3 text-[10px]"
          style={{ color: t.colors.textDim, borderTop: `1px solid ${t.colors.borderLight}` }}
        >
          <span><kbd className="font-mono">↑↓</kbd> navigate</span>
          <span><kbd className="font-mono">↵</kbd> select</span>
          <span><kbd className="font-mono">esc</kbd> close</span>
          <span className="ml-auto">{flatCommands.length} command{flatCommands.length !== 1 ? "s" : ""}</span>
        </div>
      </div>
    </>
  );
}

// ---------------------------------------------------------------------------
// Icon helper — maps command id prefix to a small SVG icon
// ---------------------------------------------------------------------------

function CmdIcon({ id, active }: { id: string; active: boolean }) {
  const color = active ? t.colors.primary : t.colors.textDim;
  const props = { className: "w-4 h-4 flex-shrink-0", fill: "none", stroke: color, viewBox: "0 0 24 24", strokeWidth: 1.5 };

  if (id.startsWith("charts:"))
    return <svg {...props}><path strokeLinecap="round" strokeLinejoin="round" d="M3 13.125C3 12.504 3.504 12 4.125 12h2.25c.621 0 1.125.504 1.125 1.125v6.75C7.5 20.496 6.996 21 6.375 21h-2.25A1.125 1.125 0 013 19.875v-6.75zM9.75 8.625c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125v11.25c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V8.625zM16.5 4.125c0-.621.504-1.125 1.125-1.125h2.25C20.496 3 21 3.504 21 4.125v15.75c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V4.125z" /></svg>;

  if (id.startsWith("logs:"))
    return <svg {...props}><path strokeLinecap="round" strokeLinejoin="round" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" /></svg>;

  if (id.startsWith("thesis:"))
    return <svg {...props}><path strokeLinecap="round" strokeLinejoin="round" d="M16.862 4.487l1.687-1.688a1.875 1.875 0 112.652 2.652L6.832 19.82a4.5 4.5 0 01-1.897 1.13l-2.685.8.8-2.685a4.5 4.5 0 011.13-1.897L16.863 4.487zm0 0L19.5 7.125" /></svg>;

  if (id.startsWith("kill:"))
    return <svg {...props}><path strokeLinecap="round" strokeLinejoin="round" d="M5.636 5.636a9 9 0 1012.728 0M12 3v9" /></svg>;

  if (id === "hwm:reset")
    return <svg {...props}><path strokeLinecap="round" strokeLinejoin="round" d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0l3.181 3.183a8.25 8.25 0 0013.803-3.7M4.031 9.865a8.25 8.25 0 0113.803-3.7l3.181 3.182m0-4.991v4.99" /></svg>;

  if (id === "catalysts:today")
    return <svg {...props}><path strokeLinecap="round" strokeLinejoin="round" d="M6.75 3v2.25M17.25 3v2.25M3 18.75V7.5a2.25 2.25 0 012.25-2.25h13.5A2.25 2.25 0 0121 7.5v11.25m-18 0A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75m-18 0v-7.5A2.25 2.25 0 015.25 9h13.5A2.25 2.25 0 0121 9v7.5" /></svg>;

  if (id === "checklist:evening")
    return <svg {...props}><path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>;

  // Default: nav arrow
  return <svg {...props}><path strokeLinecap="round" strokeLinejoin="round" d="M13.5 4.5L21 12m0 0l-7.5 7.5M21 12H3" /></svg>;
}
