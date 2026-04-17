"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { usePolling } from "@/lib/hooks";
import { getAllTheses, updateThesis, type ThesisData, type ThesisUpdate } from "@/lib/api";
import { theme as t } from "@/lib/theme";

// ─── Toast ────────────────────────────────────────────────────────────────────
interface ToastState { msg: string; kind: "success" | "error" }

function Toast({ toast, onDismiss }: { toast: ToastState; onDismiss: () => void }) {
  const bg = toast.kind === "success" ? t.colors.successLight : t.colors.dangerLight;
  const border = toast.kind === "success" ? t.colors.successBorder : t.colors.dangerBorder;
  const color = toast.kind === "success" ? t.colors.success : t.colors.danger;
  return (
    <div className="fixed bottom-6 right-6 px-4 py-3 rounded-lg text-[13px] font-medium z-50 flex items-center gap-3"
      style={{ background: bg, border: `1px solid ${border}`, color }}>
      {toast.msg}
      <button onClick={onDismiss} className="opacity-60 hover:opacity-100" style={{ color }}>✕</button>
    </div>
  );
}

// ─── Tag editor ───────────────────────────────────────────────────────────────
function TagEditor({ tags, onChange }: { tags: string[]; onChange: (next: string[]) => void }) {
  const [inputVal, setInputVal] = useState("");

  const addTag = () => {
    const v = inputVal.trim();
    if (v && !tags.includes(v)) onChange([...tags, v]);
    setInputVal("");
  };

  const removeTag = (idx: number) => onChange(tags.filter((_, i) => i !== idx));

  return (
    <div>
      <div className="flex flex-wrap gap-1.5 mb-2 min-h-[24px]">
        {tags.map((tag, idx) => (
          <span key={idx} className="flex items-center gap-1 text-[11px] px-2 py-0.5 rounded-full"
            style={{ background: t.colors.dangerLight, color: t.colors.danger, border: `1px solid ${t.colors.dangerBorder}` }}>
            {tag}
            <button onClick={() => removeTag(idx)}
              className="opacity-60 hover:opacity-100 text-[10px] leading-none"
              style={{ color: t.colors.danger }}>✕</button>
          </span>
        ))}
        {tags.length === 0 && (
          <span className="text-[11px]" style={{ color: t.colors.textDim }}>No conditions set</span>
        )}
      </div>
      <div className="flex gap-2">
        <input
          type="text"
          value={inputVal}
          onChange={(e) => setInputVal(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addTag(); } }}
          placeholder="Add condition… (Enter to add)"
          className="flex-1 px-3 py-1.5 rounded-lg text-[12px] focus:outline-none"
          style={{ background: t.colors.bg, color: t.colors.text, border: `1px solid ${t.colors.border}`, fontFamily: t.fonts.body }}
        />
        <button onClick={addTag}
          className="px-3 py-1.5 rounded-lg text-[12px] font-medium"
          style={{ background: t.colors.primaryLight, color: t.colors.primary, border: `1px solid ${t.colors.primaryBorder}` }}>
          Add
        </button>
      </div>
    </div>
  );
}

// ─── ThesisEditorCard ─────────────────────────────────────────────────────────
function ThesisEditorCard({
  market,
  thesis,
  onSave,
}: {
  market: string;
  thesis: ThesisData;
  onSave: (msg: string, kind: "success" | "error") => void;
}) {
  const [direction, setDirection] = useState(thesis.direction);
  const [conviction, setConviction] = useState(Math.round(thesis.conviction * 100));
  const [summary, setSummary] = useState(thesis.thesis_summary);
  const [fvNote, setFvNote] = useState(thesis.fair_value_note ?? "");
  const [notes, setNotes] = useState(thesis.tactical_notes);
  const [conditions, setConditions] = useState<string[]>(thesis.invalidation_conditions ?? []);
  const [saving, setSaving] = useState(false);

  // Dirty detection
  const isDirty =
    direction !== thesis.direction ||
    conviction !== Math.round(thesis.conviction * 100) ||
    summary !== thesis.thesis_summary ||
    fvNote !== (thesis.fair_value_note ?? "") ||
    notes !== thesis.tactical_notes ||
    JSON.stringify(conditions) !== JSON.stringify(thesis.invalidation_conditions ?? []);

  const dirColor =
    direction === "long" ? t.colors.success :
    direction === "short" ? t.colors.danger :
    t.colors.textMuted;

  const handleSave = async () => {
    setSaving(true);
    try {
      const payload: Partial<ThesisUpdate> = {
        direction,
        conviction: conviction / 100,
        thesis_summary: summary,
        fair_value_note: fvNote,
        invalidation_conditions: conditions,
        tactical_notes: notes,
      };
      await updateThesis(market, payload);
      onSave(`Saved ${market}`, "success");
    } catch (e) {
      onSave(e instanceof Error ? e.message : "Save failed", "error");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="rounded-xl p-5" style={{ background: t.colors.surface, border: `1px solid ${t.colors.border}` }}>
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <h3 className="text-[16px] font-semibold" style={{ color: t.colors.text, fontFamily: t.fonts.heading }}>{market}</h3>
          <span className="text-[10px] font-semibold uppercase px-2 py-0.5 rounded-full"
            style={{ background: `${dirColor}18`, color: dirColor, border: `1px solid ${dirColor}35` }}>
            {direction}
          </span>
        </div>
        <div className="flex items-center gap-2">
          {thesis.needs_review && (
            <span className="px-2 py-0.5 rounded text-[10px] font-semibold uppercase"
              style={{ background: t.colors.warningLight, color: t.colors.warning, border: `1px solid ${t.colors.warningBorder}` }}>
              review
            </span>
          )}
          {thesis.is_stale && (
            <span className="px-2 py-0.5 rounded text-[10px] font-semibold uppercase"
              style={{ background: t.colors.dangerLight, color: t.colors.danger, border: `1px solid ${t.colors.dangerBorder}` }}>
              stale
            </span>
          )}
          {isDirty && (
            <span className="px-2 py-0.5 rounded text-[10px]"
              style={{ background: t.colors.warningLight, color: t.colors.warning, border: `1px solid ${t.colors.warningBorder}` }}>
              unsaved
            </span>
          )}
          <button onClick={handleSave} disabled={!isDirty || saving}
            className="px-3 py-1.5 rounded-lg text-[12px] font-semibold transition-all"
            style={{
              background: (!isDirty || saving) ? t.colors.borderLight : t.colors.primaryLight,
              color: (!isDirty || saving) ? t.colors.textDim : t.colors.primary,
              border: `1px solid ${(!isDirty || saving) ? t.colors.border : t.colors.primaryBorder}`,
              opacity: (!isDirty || saving) ? 0.5 : 1,
              cursor: (!isDirty || saving) ? "not-allowed" : "pointer",
            }}>
            {saving ? "Saving…" : "Save"}
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        {/* Left: Controls */}
        <div className="space-y-4">
          {/* Direction */}
          <div>
            <label className="text-[11px] uppercase tracking-wider mb-1.5 block"
              style={{ color: t.colors.textMuted, fontFamily: t.fonts.heading }}>
              Direction
            </label>
            <div className="flex gap-1">
              {(["long", "short", "flat"] as const).map((d) => {
                const dc = d === "long" ? t.colors.success : d === "short" ? t.colors.danger : t.colors.textMuted;
                const active = direction === d;
                return (
                  <button key={d} onClick={() => setDirection(d)}
                    className="px-3 py-1.5 rounded-lg text-[12px] font-semibold uppercase transition-all flex-1"
                    style={active ? {
                      background: `${dc}18`, color: dc, border: `1px solid ${dc}35`,
                    } : {
                      background: "transparent", color: t.colors.textDim, border: `1px solid ${t.colors.border}`,
                    }}>
                    {d}
                  </button>
                );
              })}
            </div>
          </div>

          {/* Conviction slider */}
          <div>
            <label className="text-[11px] uppercase tracking-wider mb-1.5 flex justify-between items-center"
              style={{ color: t.colors.textMuted, fontFamily: t.fonts.heading }}>
              <span>Conviction</span>
              <span style={{ color: t.colors.text, fontFamily: t.fonts.mono }}>{conviction}%</span>
            </label>
            <input type="range" min={0} max={100} step={5} value={conviction}
              onChange={(e) => setConviction(parseInt(e.target.value))}
              className="w-full h-2 rounded-full appearance-none cursor-pointer"
              style={{ background: `linear-gradient(to right, ${t.colors.primary} ${conviction}%, ${t.colors.border} ${conviction}%)` }}
            />
            <div className="flex justify-between mt-1 text-[10px]" style={{ color: t.colors.textDim }}>
              <span>0%</span>
              <span>Effective: {thesis.effective_conviction ? `${(thesis.effective_conviction * 100).toFixed(0)}%` : "—"}</span>
              <span>100%</span>
            </div>
          </div>

          {/* Fair-value note (replaces Take Profit Price — 2026-04-17) */}
          <div>
            <label className="text-[11px] uppercase tracking-wider mb-1.5 block"
              style={{ color: t.colors.textMuted, fontFamily: t.fonts.heading }}>
              Fair-value Note
              <span className="ml-2 normal-case tracking-normal text-[10px]" style={{ color: t.colors.textDim }}>
                narrative only — TP comes from mechanical 5× ATR
              </span>
            </label>
            <textarea value={fvNote} onChange={(e) => setFvNote(e.target.value)}
              rows={2} spellCheck={false}
              placeholder="e.g. Gold $5–6k on debasement; don't trade the number, size off conviction."
              className="w-full px-3 py-2 rounded-lg text-[12px] leading-relaxed resize-y focus:outline-none"
              style={{ background: t.colors.bg, border: `1px solid ${t.colors.border}`, color: t.colors.textSecondary, fontFamily: t.fonts.body }}
            />
          </div>
        </div>

        {/* Right: Text fields */}
        <div className="space-y-4">
          {/* Summary */}
          <div>
            <label className="text-[11px] uppercase tracking-wider mb-1.5 block"
              style={{ color: t.colors.textMuted, fontFamily: t.fonts.heading }}>
              Thesis Summary
            </label>
            <textarea value={summary} onChange={(e) => setSummary(e.target.value)}
              rows={4} spellCheck={false}
              className="w-full px-3 py-2 rounded-lg text-[12px] leading-relaxed resize-y focus:outline-none"
              style={{ background: t.colors.bg, border: `1px solid ${t.colors.border}`, color: t.colors.textSecondary, scrollbarWidth: "thin", fontFamily: t.fonts.body }}
            />
          </div>

          {/* Tactical Notes */}
          <div>
            <label className="text-[11px] uppercase tracking-wider mb-1.5 block"
              style={{ color: t.colors.textMuted, fontFamily: t.fonts.heading }}>
              Tactical Notes
            </label>
            <textarea value={notes} onChange={(e) => setNotes(e.target.value)}
              rows={3} spellCheck={false}
              className="w-full px-3 py-2 rounded-lg text-[12px] leading-relaxed resize-y focus:outline-none"
              style={{ background: t.colors.bg, border: `1px solid ${t.colors.border}`, color: t.colors.textSecondary, scrollbarWidth: "thin", fontFamily: t.fonts.body }}
            />
          </div>
        </div>
      </div>

      {/* Invalidation conditions — full width */}
      <div className="mt-4 pt-4" style={{ borderTop: `1px solid ${t.colors.border}` }}>
        <label className="text-[11px] uppercase tracking-wider mb-2 block"
          style={{ color: t.colors.textMuted, fontFamily: t.fonts.heading }}>
          Invalidation Conditions
        </label>
        <TagEditor tags={conditions} onChange={setConditions} />
      </div>

      {/* Meta row */}
      <div className="mt-3 text-[11px]" style={{ color: t.colors.textDim }}>
        Last updated{" "}
        {thesis.age_hours > 336
          ? "STALE (>14d)"
          : thesis.age_hours < 24
            ? `${thesis.age_hours.toFixed(1)}h ago`
            : `${(thesis.age_hours / 24).toFixed(1)}d ago`}
      </div>
    </div>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────
export default function ThesisEditorPage() {
  const router = useRouter();
  const { data, refresh } = usePolling(getAllTheses, 30000);
  const [toast, setToast] = useState<ToastState | null>(null);

  const showToast = (msg: string, kind: "success" | "error") => {
    setToast({ msg, kind });
    setTimeout(() => { setToast(null); refresh(); }, 3000);
  };

  return (
    <div className="p-8 max-w-[1400px]">
      {toast && <Toast toast={toast} onDismiss={() => setToast(null)} />}

      {/* Header */}
      <div className="mb-6 flex items-center gap-4">
        <button
          onClick={() => router.push("/control")}
          className="text-[13px] px-3 py-1.5 rounded-lg transition-colors"
          style={{ background: t.colors.borderLight, color: t.colors.textMuted, border: `1px solid ${t.colors.border}` }}>
          ← Control
        </button>
        <div>
          <h2 className="text-2xl font-semibold" style={{ color: t.colors.text, fontFamily: t.fonts.heading }}>
            Thesis Editor
          </h2>
          <p className="text-[13px] mt-1" style={{ color: t.colors.textMuted }}>
            Edit conviction, direction, and parameters per market
          </p>
        </div>
      </div>

      {!data ? (
        <p className="text-[13px]" style={{ color: t.colors.textDim }}>Loading theses…</p>
      ) : Object.keys(data.theses).length === 0 ? (
        <div className="px-4 py-8 text-center rounded-lg"
          style={{ background: t.colors.surface, border: `1px solid ${t.colors.border}` }}>
          <p className="text-[13px]" style={{ color: t.colors.textDim }}>No thesis files found in data/thesis/</p>
        </div>
      ) : (
        <div className="space-y-4">
          {Object.entries(data.theses).map(([market, thesis]) => (
            <ThesisEditorCard key={market} market={market} thesis={thesis} onSave={showToast} />
          ))}
        </div>
      )}
    </div>
  );
}
