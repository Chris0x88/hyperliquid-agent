"use client";

import { useState } from "react";
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

// ─── IteratorGrid ─────────────────────────────────────────────────────────────
function IteratorGrid() {
  const { data, refresh } = usePolling(getIterators, 30000);
  if (!data) return <p className="text-[13px]" style={{ color: t.colors.textDim }}>Loading iterators...</p>;

  const handleToggle = async (name: string, enabled: boolean) => {
    await toggleIterator(name, !enabled);
    refresh();
  };

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-2">
      {data.iterators.map((it: Iterator) => (
        <div key={it.name} className="flex items-center justify-between px-3 py-2.5 rounded-lg"
          style={{ background: t.colors.surface, border: `1px solid ${t.colors.border}` }}>
          <div className="flex-1 min-w-0">
            <p className="text-[13px] font-medium truncate" style={{ color: t.colors.text }}>{it.name}</p>
            <div className="flex gap-1 mt-0.5">
              {it.tiers.map(tier => (
                <span key={tier} className="text-[9px] uppercase px-1.5 py-0.5 rounded"
                  style={{ background: t.colors.borderLight, color: t.colors.textDim }}>
                  {tier}
                </span>
              ))}
            </div>
          </div>
          <button
            onClick={() => handleToggle(it.name, it.enabled)}
            className="w-10 h-5 rounded-full relative transition-colors flex-shrink-0 ml-3"
            style={{ background: it.enabled ? t.colors.primary : t.colors.border }}
          >
            <div className="w-4 h-4 rounded-full bg-white absolute top-0.5 transition-all"
              style={{ left: it.enabled ? "22px" : "2px" }} />
          </button>
        </div>
      ))}
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
