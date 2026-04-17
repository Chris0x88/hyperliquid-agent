"use client";

import { useState, useEffect, useMemo } from "react";
import { useRouter } from "next/navigation";
import { usePolling } from "@/lib/hooks";
import {
  getIterators,
  toggleIterator,
  listConfigs,
  getConfig,
  updateConfig,
  getAuthority,
  setAuthority,
  type Iterator,
  type ConfigMeta,
} from "@/lib/api";
import { theme as t } from "@/lib/theme";

// ─── Category order and labels ────────────────────────────────────────────────
const CATEGORY_ORDER = ["Trading", "Safety", "Intelligence", "Self-improvement", "Operations"] as const;
type Category = typeof CATEGORY_ORDER[number];

const CATEGORY_COLORS: Record<Category, { bg: string; text: string; border: string }> = {
  "Trading":          { bg: t.colors.primaryLight,   text: t.colors.primary,   border: t.colors.primaryBorder },
  "Safety":           { bg: t.colors.dangerLight,    text: t.colors.danger,    border: t.colors.dangerBorder },
  "Intelligence":     { bg: t.colors.tertiaryLight,  text: t.colors.tertiary,  border: t.colors.tertiaryBorder },
  "Self-improvement": { bg: t.colors.warningLight,   text: t.colors.warning,   border: t.colors.warningBorder },
  "Operations":       { bg: t.colors.secondaryLight, text: t.colors.secondary, border: "rgba(143, 113, 86, 0.3)" },
};

const EXPANDED_STORAGE_KEY = "control.iterator.expanded.v1";

// ─── Toast ────────────────────────────────────────────────────────────────────
type ToastKind = "success" | "error";
interface ToastState { msg: string; kind: ToastKind }

function Toast({ toast, onDismiss }: { toast: ToastState; onDismiss: () => void }) {
  const bg = toast.kind === "success" ? t.colors.successLight : t.colors.dangerLight;
  const border = toast.kind === "success" ? t.colors.successBorder : t.colors.dangerBorder;
  const color = toast.kind === "success" ? t.colors.success : t.colors.danger;
  return (
    <div
      className="fixed bottom-6 right-6 px-4 py-3 rounded-lg text-[13px] font-medium z-50 flex items-center gap-3"
      style={{ background: bg, border: `1px solid ${border}`, color }}
    >
      {toast.msg}
      <button onClick={onDismiss} className="opacity-60 hover:opacity-100 ml-1" style={{ color }}>✕</button>
    </div>
  );
}

// ─── Confirm Dialog ───────────────────────────────────────────────────────────
interface ConfirmDialogProps {
  filename: string;
  onConfirm: () => void;
  onCancel: () => void;
}
function ConfirmDialog({ filename, onConfirm, onCancel }: ConfirmDialogProps) {
  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center" style={{ background: "rgba(0,0,0,0.6)" }}>
      <div className="rounded-xl p-6 max-w-sm w-full mx-4"
        style={{ background: t.colors.surface, border: `1px solid ${t.colors.border}` }}>
        <h3 className="text-[15px] font-semibold mb-2" style={{ color: t.colors.text, fontFamily: t.fonts.heading }}>
          Confirm Save
        </h3>
        <p className="text-[13px] mb-5" style={{ color: t.colors.textSecondary }}>
          <span style={{ color: t.colors.warning, fontFamily: t.fonts.mono }}>{filename}</span> is a critical
          config. Incorrect values can affect live trading. Are you sure you want to save?
        </p>
        <div className="flex gap-2 justify-end">
          <button onClick={onCancel}
            className="px-4 py-2 rounded-lg text-[13px] font-medium"
            style={{ background: t.colors.borderLight, color: t.colors.textMuted, border: `1px solid ${t.colors.border}` }}>
            Cancel
          </button>
          <button onClick={onConfirm}
            className="px-4 py-2 rounded-lg text-[13px] font-semibold"
            style={{ background: t.colors.dangerLight, color: t.colors.danger, border: `1px solid ${t.colors.dangerBorder}` }}>
            Save Anyway
          </button>
        </div>
      </div>
    </div>
  );
}

// ─── ConfigBrowser ────────────────────────────────────────────────────────────
const CRITICAL_CONFIGS = new Set(["oil_botpattern.json", "risk_caps.json"]);

function ConfigBrowser() {
  const { data } = usePolling(listConfigs, 60000);
  const [selected, setSelected] = useState<string | null>(null);
  const [savedText, setSavedText] = useState<string>("");
  const [editText, setEditText] = useState<string>("");
  const [saving, setSaving] = useState(false);
  const [toast, setToast] = useState<ToastState | null>(null);
  const [confirmPending, setConfirmPending] = useState(false);
  const [parseError, setParseError] = useState<string | null>(null);

  const isDirty = editText !== savedText;

  const showToast = (msg: string, kind: ToastKind) => {
    setToast({ msg, kind });
    setTimeout(() => setToast(null), 4000);
  };

  const handleSelect = async (filename: string) => {
    setSelected(filename);
    setParseError(null);
    try {
      const resp = await getConfig(filename) as { data: unknown };
      const text = JSON.stringify(resp.data, null, 2);
      setSavedText(text);
      setEditText(text);
    } catch {
      const errText = "Error loading config";
      setSavedText(errText);
      setEditText(errText);
    }
  };

  const handleEditChange = (value: string) => {
    setEditText(value);
    // Validate JSON on the fly
    try {
      JSON.parse(value);
      setParseError(null);
    } catch (e) {
      setParseError(e instanceof Error ? e.message : "Invalid JSON");
    }
  };

  const doSave = async () => {
    if (!selected || parseError) return;
    setSaving(true);
    try {
      const parsed = JSON.parse(editText);
      await updateConfig(selected, parsed);
      setSavedText(editText);
      showToast(`Saved ${selected}`, "success");
    } catch (e) {
      showToast(e instanceof Error ? e.message : "Save failed", "error");
    } finally {
      setSaving(false);
    }
  };

  const handleSaveClick = () => {
    if (!selected || parseError) return;
    if (CRITICAL_CONFIGS.has(selected)) {
      setConfirmPending(true);
    } else {
      doSave();
    }
  };

  if (!data) return <p className="text-[13px]" style={{ color: t.colors.textDim }}>Loading configs...</p>;

  return (
    <>
      {toast && <Toast toast={toast} onDismiss={() => setToast(null)} />}
      {confirmPending && selected && (
        <ConfirmDialog
          filename={selected}
          onConfirm={() => { setConfirmPending(false); doSave(); }}
          onCancel={() => setConfirmPending(false)}
        />
      )}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* File list */}
        <div className="rounded-lg overflow-hidden"
          style={{ background: t.colors.surface, border: `1px solid ${t.colors.border}` }}>
          <div className="max-h-[420px] overflow-y-auto"
            style={{ scrollbarWidth: "thin", scrollbarColor: `${t.colors.border} transparent` }}>
            {(data as { configs: ConfigMeta[] }).configs.map((cfg: ConfigMeta) => (
              <button key={cfg.filename} onClick={() => handleSelect(cfg.filename)}
                className="w-full text-left px-4 py-2.5 flex items-center justify-between transition-colors"
                style={{
                  borderBottom: `1px solid ${t.colors.borderLight}`,
                  background: selected === cfg.filename ? t.colors.primaryLight : "transparent",
                  color: selected === cfg.filename ? t.colors.primary : t.colors.text,
                }}>
                <span className="text-[13px] font-medium flex items-center gap-2">
                  {cfg.filename}
                  {CRITICAL_CONFIGS.has(cfg.filename) && (
                    <span className="text-[9px] uppercase px-1.5 py-0.5 rounded"
                      style={{ background: t.colors.warningLight, color: t.colors.warning, border: `1px solid ${t.colors.warningBorder}` }}>
                      critical
                    </span>
                  )}
                </span>
                <span className="text-[11px]" style={{ color: t.colors.textDim }}>
                  {cfg.type} &middot; {(cfg.size_bytes / 1024).toFixed(1)}KB
                </span>
              </button>
            ))}
          </div>
        </div>

        {/* Editor panel */}
        <div className="rounded-lg overflow-hidden flex flex-col"
          style={{ background: t.colors.surface, border: `1px solid ${t.colors.border}` }}>
          {selected ? (
            <>
              {/* Header bar */}
              <div className="flex items-center justify-between px-4 py-2.5"
                style={{ borderBottom: `1px solid ${t.colors.border}` }}>
                <div className="flex items-center gap-2">
                  <span className="text-[12px] font-medium" style={{ color: t.colors.primary, fontFamily: t.fonts.heading }}>
                    {selected}
                  </span>
                  {isDirty && !parseError && (
                    <span className="text-[10px] px-1.5 py-0.5 rounded"
                      style={{ background: t.colors.warningLight, color: t.colors.warning, border: `1px solid ${t.colors.warningBorder}` }}>
                      modified
                    </span>
                  )}
                  {!isDirty && (
                    <span className="text-[10px] px-1.5 py-0.5 rounded"
                      style={{ background: t.colors.successLight, color: t.colors.success, border: `1px solid ${t.colors.successBorder}` }}>
                      saved
                    </span>
                  )}
                  {parseError && (
                    <span className="text-[10px] px-1.5 py-0.5 rounded"
                      style={{ background: t.colors.dangerLight, color: t.colors.danger, border: `1px solid ${t.colors.dangerBorder}` }}>
                      invalid json
                    </span>
                  )}
                </div>
                <button
                  onClick={handleSaveClick}
                  disabled={!isDirty || !!parseError || saving}
                  className="px-3 py-1 rounded-md text-[12px] font-semibold transition-opacity"
                  style={{
                    background: (!isDirty || !!parseError || saving) ? t.colors.borderLight : t.colors.primaryLight,
                    color: (!isDirty || !!parseError || saving) ? t.colors.textDim : t.colors.primary,
                    border: `1px solid ${(!isDirty || !!parseError || saving) ? t.colors.border : t.colors.primaryBorder}`,
                    opacity: (!isDirty || !!parseError || saving) ? 0.5 : 1,
                    cursor: (!isDirty || !!parseError || saving) ? "not-allowed" : "pointer",
                  }}>
                  {saving ? "Saving…" : "Save"}
                </button>
              </div>
              {/* Parse error hint */}
              {parseError && (
                <div className="px-4 py-1.5 text-[11px]"
                  style={{ background: t.colors.dangerLight, color: t.colors.danger, borderBottom: `1px solid ${t.colors.dangerBorder}` }}>
                  {parseError}
                </div>
              )}
              {/* Textarea editor */}
              <textarea
                value={editText}
                onChange={(e) => handleEditChange(e.target.value)}
                spellCheck={false}
                className="flex-1 w-full p-4 resize-none text-[11px] leading-5 focus:outline-none"
                style={{
                  background: "transparent",
                  color: t.colors.textSecondary,
                  fontFamily: t.fonts.mono,
                  minHeight: "360px",
                  scrollbarWidth: "thin",
                  scrollbarColor: `${t.colors.border} transparent`,
                  tabSize: 2,
                }}
              />
            </>
          ) : (
            <div className="p-8 text-center flex-1 flex items-center justify-center">
              <p className="text-[13px]" style={{ color: t.colors.textDim }}>Select a config file to edit</p>
            </div>
          )}
        </div>
      </div>
    </>
  );
}

// ─── Chip ─────────────────────────────────────────────────────────────────────
function Chip({ label, mono = false }: { label: string; mono?: boolean }) {
  return (
    <span
      className="inline-block text-[10px] px-1.5 py-0.5 rounded"
      style={{
        background: t.colors.borderLight,
        color: t.colors.textMuted,
        border: `1px solid ${t.colors.border}`,
        fontFamily: mono ? t.fonts.mono : undefined,
        whiteSpace: "nowrap",
        maxWidth: "100%",
        overflow: "hidden",
        textOverflow: "ellipsis",
      }}
    >
      {label}
    </span>
  );
}

// ─── IteratorCard ─────────────────────────────────────────────────────────────
function IteratorCard({
  it,
  expanded,
  onToggleExpand,
  onToggle,
}: {
  it: Iterator;
  expanded: boolean;
  onToggleExpand: () => void;
  onToggle: () => void;
}) {
  const catStyle = CATEGORY_COLORS[it.category as Category] ?? {
    bg: t.colors.borderLight,
    text: t.colors.textMuted,
    border: t.colors.border,
  };

  return (
    <div
      className="rounded-lg overflow-hidden transition-all"
      style={{
        background: t.colors.surface,
        border: `1px solid ${expanded ? t.colors.primaryBorder : t.colors.border}`,
      }}
    >
      {/* ── Card header ── */}
      <div
        className="flex items-start gap-2 px-3 py-2.5 cursor-pointer"
        onClick={onToggleExpand}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => e.key === "Enter" && onToggleExpand()}
        aria-expanded={expanded}
      >
        {/* Name + category + description */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <p className="text-[13px] font-semibold" style={{ color: t.colors.text, fontFamily: t.fonts.heading }}>
              {it.name}
            </p>
            <span
              className="text-[9px] uppercase px-1.5 py-0.5 rounded font-semibold"
              style={{ background: catStyle.bg, color: catStyle.text, border: `1px solid ${catStyle.border}` }}
            >
              {it.category}
            </span>
          </div>
          {it.description ? (
            <p className="text-[11px] mt-0.5 leading-4" style={{ color: t.colors.textSecondary }}>
              {it.description}
            </p>
          ) : (
            <p className="text-[11px] mt-0.5 italic" style={{ color: t.colors.textDim }}>
              No description available
            </p>
          )}
        </div>

        {/* Expand chevron */}
        <span
          className="text-[11px] mt-0.5 flex-shrink-0 select-none"
          style={{ color: t.colors.textDim }}
          aria-hidden
        >
          {expanded ? "▲" : "▼"}
        </span>

        {/* Toggle — stop propagation so click doesn't also expand */}
        <button
          onClick={(e) => { e.stopPropagation(); onToggle(); }}
          className="w-10 h-5 rounded-full relative transition-colors flex-shrink-0 mt-0.5"
          style={{ background: it.enabled ? t.colors.primary : t.colors.border }}
          aria-label={it.enabled ? "Disable iterator" : "Enable iterator"}
        >
          <div className="w-4 h-4 rounded-full bg-white absolute top-0.5 transition-all"
            style={{ left: it.enabled ? "22px" : "2px" }} />
        </button>
      </div>

      {/* ── Expanded detail panel ── */}
      {expanded && (
        <div
          className="px-3 pb-3 space-y-3"
          style={{ borderTop: `1px solid ${t.colors.borderLight}` }}
        >
          {/* Tiers */}
          <div className="flex gap-1 flex-wrap pt-2">
            {it.tier_set.map(tier => (
              <span key={tier} className="text-[9px] uppercase px-1.5 py-0.5 rounded"
                style={{ background: t.colors.borderLight, color: t.colors.textDim, border: `1px solid ${t.colors.border}` }}>
                {tier}
              </span>
            ))}
          </div>

          {/* Purpose */}
          {it.purpose && (
            <div>
              <p className="text-[10px] uppercase font-semibold mb-1"
                style={{ color: t.colors.textMuted, letterSpacing: "0.06em", fontFamily: t.fonts.heading }}>
                What it does
              </p>
              <p className="text-[12px] leading-5" style={{ color: t.colors.textSecondary }}>
                {it.purpose}
              </p>
            </div>
          )}

          {/* Kill-switch impact */}
          {it.kill_switch_impact && (
            <div className="rounded-md px-3 py-2"
              style={{ background: t.colors.dangerLight, border: `1px solid ${t.colors.dangerBorder}` }}>
              <p className="text-[10px] uppercase font-semibold mb-1"
                style={{ color: t.colors.danger, letterSpacing: "0.06em", fontFamily: t.fonts.heading }}>
                If turned OFF
              </p>
              <p className="text-[12px] leading-5" style={{ color: t.colors.textSecondary }}>
                {it.kill_switch_impact}
              </p>
            </div>
          )}

          {/* Inputs */}
          {it.inputs && it.inputs.length > 0 && (
            <div>
              <p className="text-[10px] uppercase font-semibold mb-1.5"
                style={{ color: t.colors.textMuted, letterSpacing: "0.06em", fontFamily: t.fonts.heading }}>
                Reads from
              </p>
              <div className="flex flex-wrap gap-1">
                {it.inputs.map((inp, i) => <Chip key={i} label={inp} mono />)}
              </div>
            </div>
          )}

          {/* Outputs */}
          {it.outputs && it.outputs.length > 0 && (
            <div>
              <p className="text-[10px] uppercase font-semibold mb-1.5"
                style={{ color: t.colors.textMuted, letterSpacing: "0.06em", fontFamily: t.fonts.heading }}>
                Writes to
              </p>
              <div className="flex flex-wrap gap-1">
                {it.outputs.map((out, i) => <Chip key={i} label={out} mono />)}
              </div>
            </div>
          )}

          {/* Source file */}
          {it.source_file && (
            <div>
              <p className="text-[10px] uppercase font-semibold mb-1"
                style={{ color: t.colors.textMuted, letterSpacing: "0.06em", fontFamily: t.fonts.heading }}>
                Source
              </p>
              <span
                className="text-[11px]"
                style={{ color: t.colors.textDim, fontFamily: t.fonts.mono }}
              >
                {it.source_file}
              </span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ─── IteratorGrid ─────────────────────────────────────────────────────────────
function IteratorGrid() {
  const { data, refresh } = usePolling(getIterators, 30000);

  // localStorage-persisted expanded set
  const [expandedSet, setExpandedSet] = useState<Set<string>>(() => {
    if (typeof window === "undefined") return new Set();
    try {
      const raw = localStorage.getItem(EXPANDED_STORAGE_KEY);
      return raw ? new Set(JSON.parse(raw) as string[]) : new Set();
    } catch {
      return new Set();
    }
  });

  // Sync to localStorage on change
  useEffect(() => {
    try {
      localStorage.setItem(EXPANDED_STORAGE_KEY, JSON.stringify([...expandedSet]));
    } catch {
      // localStorage unavailable — ignore
    }
  }, [expandedSet]);

  const [search, setSearch] = useState("");
  const [categoryFilter, setCategoryFilter] = useState<string>("all");

  const handleToggle = async (name: string, enabled: boolean) => {
    await toggleIterator(name, !enabled);
    refresh();
  };

  const handleToggleExpand = (name: string) => {
    setExpandedSet(prev => {
      const next = new Set(prev);
      if (next.has(name)) { next.delete(name); } else { next.add(name); }
      return next;
    });
  };

  // Filter and group
  const filtered = useMemo(() => {
    if (!data) return [];
    const q = search.trim().toLowerCase();
    return data.iterators.filter((it: Iterator) => {
      const matchCat = categoryFilter === "all" || it.category === categoryFilter;
      const matchSearch = !q
        || it.name.toLowerCase().includes(q)
        || (it.description ?? "").toLowerCase().includes(q)
        || (it.purpose ?? "").toLowerCase().includes(q);
      return matchCat && matchSearch;
    });
  }, [data, search, categoryFilter]);

  const grouped = useMemo(() => {
    const map = new Map<string, Iterator[]>();
    for (const cat of CATEGORY_ORDER) { map.set(cat, []); }
    for (const it of filtered) {
      const cat = it.category ?? "Operations";
      if (!map.has(cat)) map.set(cat, []);
      map.get(cat)!.push(it);
    }
    return map;
  }, [filtered]);

  if (!data) return <p className="text-[13px]" style={{ color: t.colors.textDim }}>Loading iterators...</p>;

  const totalCount = data.iterators.length;
  const filteredCount = filtered.length;

  return (
    <div>
      {/* ── Controls row ── */}
      <div className="flex flex-col sm:flex-row gap-2 mb-4">
        {/* Search */}
        <div className="relative flex-1">
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search by name or description…"
            className="w-full text-[13px] px-3 py-2 rounded-lg pr-8 focus:outline-none"
            style={{
              background: t.colors.surface,
              border: `1px solid ${search ? t.colors.primaryBorder : t.colors.border}`,
              color: t.colors.text,
              fontFamily: t.fonts.body,
            }}
          />
          {search && (
            <button
              onClick={() => setSearch("")}
              className="absolute right-2.5 top-1/2 -translate-y-1/2 text-[11px] opacity-50 hover:opacity-100"
              style={{ color: t.colors.textMuted }}
              aria-label="Clear search"
            >
              ✕
            </button>
          )}
        </div>

        {/* Category filter */}
        <div className="flex gap-1 flex-wrap">
          <button
            onClick={() => setCategoryFilter("all")}
            className="px-2.5 py-1.5 rounded-md text-[11px] font-medium transition-all"
            style={categoryFilter === "all"
              ? { background: t.colors.primaryLight, color: t.colors.primary, border: `1px solid ${t.colors.primaryBorder}` }
              : { color: t.colors.textMuted, border: `1px solid ${t.colors.border}` }}
          >
            All ({totalCount})
          </button>
          {CATEGORY_ORDER.map(cat => {
            const cs = CATEGORY_COLORS[cat];
            const count = data.iterators.filter((it: Iterator) => it.category === cat).length;
            return (
              <button
                key={cat}
                onClick={() => setCategoryFilter(categoryFilter === cat ? "all" : cat)}
                className="px-2.5 py-1.5 rounded-md text-[11px] font-medium transition-all"
                style={categoryFilter === cat
                  ? { background: cs.bg, color: cs.text, border: `1px solid ${cs.border}` }
                  : { color: t.colors.textMuted, border: `1px solid ${t.colors.border}` }}
              >
                {cat} ({count})
              </button>
            );
          })}
        </div>
      </div>

      {/* ── Result count ── */}
      {(search || categoryFilter !== "all") && (
        <p className="text-[11px] mb-3" style={{ color: t.colors.textDim }}>
          Showing {filteredCount} of {totalCount} iterators
        </p>
      )}

      {/* ── Grouped iterator cards ── */}
      {filteredCount === 0 ? (
        <p className="text-[13px]" style={{ color: t.colors.textDim }}>
          No iterators match your search.
        </p>
      ) : (
        <div className="space-y-6">
          {CATEGORY_ORDER.map(cat => {
            const items = grouped.get(cat) ?? [];
            if (items.length === 0) return null;
            const cs = CATEGORY_COLORS[cat];
            return (
              <div key={cat}>
                <div className="flex items-center gap-2 mb-2">
                  <span
                    className="text-[10px] uppercase px-2 py-0.5 rounded font-semibold"
                    style={{ background: cs.bg, color: cs.text, border: `1px solid ${cs.border}` }}
                  >
                    {cat}
                  </span>
                  <span className="text-[11px]" style={{ color: t.colors.textDim }}>
                    {items.length} iterator{items.length !== 1 ? "s" : ""}
                  </span>
                </div>
                <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-2">
                  {items.map((it: Iterator) => (
                    <IteratorCard
                      key={it.name}
                      it={it}
                      expanded={expandedSet.has(it.name)}
                      onToggleExpand={() => handleToggleExpand(it.name)}
                      onToggle={() => handleToggle(it.name, it.enabled)}
                    />
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ─── AuthorityPanel ───────────────────────────────────────────────────────────
function AuthorityPanel() {
  const { data, refresh } = usePolling(getAuthority as () => Promise<{ authority: Record<string, { authority: string; note?: string }> }>, 30000);
  if (!data) return null;

  const entries = Object.entries(data.authority);
  if (entries.length === 0) return null;

  const levelStyles: Record<string, { bg: string; text: string; border: string }> = {
    agent: { bg: t.colors.primaryLight, text: t.colors.primary, border: t.colors.primaryBorder },
    manual: { bg: t.colors.tertiaryLight, text: t.colors.tertiary, border: t.colors.tertiaryBorder },
    off: { bg: t.colors.dangerLight, text: t.colors.danger, border: t.colors.dangerBorder },
  };

  const handleCycle = async (asset: string, current: string) => {
    const next = current === "agent" ? "manual" : current === "manual" ? "off" : "agent";
    await setAuthority(asset, next);
    refresh();
  };

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-2">
      {entries.map(([asset, info]) => {
        const s = levelStyles[info.authority] || levelStyles.manual;
        return (
          <div key={asset} className="flex items-center justify-between px-4 py-3 rounded-lg"
            style={{ background: t.colors.surface, border: `1px solid ${t.colors.border}` }}>
            <span className="text-[13px] font-medium" style={{ color: t.colors.text, fontFamily: t.fonts.heading }}>{asset}</span>
            <button onClick={() => handleCycle(asset, info.authority)}
              className="px-3 py-1 rounded-md text-[11px] font-semibold uppercase tracking-wider transition-colors"
              style={{ background: s.bg, color: s.text, border: `1px solid ${s.border}` }}>
              {info.authority}
            </button>
          </div>
        );
      })}
    </div>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────
type TabId = "iterators" | "config" | "authority";

export default function ControlPage() {
  const [tab, setTab] = useState<TabId>("iterators");
  const router = useRouter();

  return (
    <div className="p-8 max-w-[1400px]">
      <div className="mb-6 flex items-start justify-between">
        <div>
          <h2 className="text-2xl font-semibold" style={{ color: t.colors.text, fontFamily: t.fonts.heading }}>
            Control Panel
          </h2>
          <p className="text-[13px] mt-1" style={{ color: t.colors.textMuted }}>
            Manage iterators, configs, and authority
          </p>
        </div>
        {/* Thesis Editor shortcut */}
        <button
          onClick={() => router.push("/control/thesis")}
          className="px-4 py-2 rounded-lg text-[13px] font-medium transition-all"
          style={{
            background: t.colors.tertiaryLight,
            color: t.colors.tertiary,
            border: `1px solid ${t.colors.tertiaryBorder}`,
          }}>
          Thesis Editor →
        </button>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 mb-6">
        {(["iterators", "config", "authority"] as const).map((tabId) => (
          <button key={tabId} onClick={() => setTab(tabId)}
            className="px-4 py-2 rounded-lg text-[13px] font-medium capitalize transition-all"
            style={tab === tabId ? {
              background: t.colors.primaryLight,
              color: t.colors.primary,
              border: `1px solid ${t.colors.primaryBorder}`,
            } : {
              color: t.colors.textMuted,
              border: "1px solid transparent",
            }}>
            {tabId}
          </button>
        ))}
      </div>

      {tab === "iterators" && (
        <div>
          <h3 className="text-[13px] font-medium mb-3"
            style={{ color: t.colors.textMuted, textTransform: "uppercase", letterSpacing: "0.05em", fontFamily: t.fonts.heading }}>
            Daemon Iterators
          </h3>
          <IteratorGrid />
        </div>
      )}
      {tab === "config" && (
        <div>
          <h3 className="text-[13px] font-medium mb-3"
            style={{ color: t.colors.textMuted, textTransform: "uppercase", letterSpacing: "0.05em", fontFamily: t.fonts.heading }}>
            Configuration Files
          </h3>
          <ConfigBrowser />
        </div>
      )}
      {tab === "authority" && (
        <div>
          <h3 className="text-[13px] font-medium mb-3"
            style={{ color: t.colors.textMuted, textTransform: "uppercase", letterSpacing: "0.05em", fontFamily: t.fonts.heading }}>
            Asset Authority
          </h3>
          <AuthorityPanel />
        </div>
      )}
    </div>
  );
}
