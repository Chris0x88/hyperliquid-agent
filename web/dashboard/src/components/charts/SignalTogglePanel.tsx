"use client";

// Phase 4 — Signal toggle panel for the charts page.
// Compact left sidebar that lists registered signals grouped by category.
// Operator toggles a signal on → parent fetches compute() and adds a series
// to the chart. Toggling off removes the series. Per-market localStorage
// persistence so BTC toggles don't leak into GOLD.

import { useCallback, useEffect, useMemo, useState } from "react";
import { theme as t } from "@/lib/theme";
import {
  getChartSignalsByCategory,
  type SignalCard,
  type ChartSpec,
  type SignalCategory,
} from "@/lib/api";

// ── localStorage helpers ─────────────────────────────────────────────────────
// Key is versioned + per-coin so BTC toggles don't leak into GOLD. The v1
// suffix lets us bust the format if the SignalResult schema changes later.

const LS_PREFIX = "charts.signals.v1.";

function lsKey(coin: string): string {
  return `${LS_PREFIX}${coin.toUpperCase()}`;
}

function loadActiveSlugs(coin: string): Set<string> {
  if (typeof window === "undefined") return new Set();
  try {
    const raw = localStorage.getItem(lsKey(coin));
    if (!raw) return new Set();
    const parsed = JSON.parse(raw);
    if (Array.isArray(parsed)) return new Set(parsed.map(String));
    return new Set();
  } catch {
    return new Set();
  }
}

function saveActiveSlugs(coin: string, slugs: Set<string>): void {
  if (typeof window === "undefined") return;
  try {
    localStorage.setItem(lsKey(coin), JSON.stringify([...slugs]));
  } catch {
    /* private browsing, quota, etc. — silent */
  }
}

// ── Category metadata ────────────────────────────────────────────────────────

const CATEGORY_ORDER: SignalCategory[] = [
  "volume",
  "structure",
  "momentum",
  "regime",
  "trend",
  "accumulation",
];

const CATEGORY_LABELS: Record<SignalCategory, string> = {
  volume: "Volume",
  structure: "Structure",
  momentum: "Momentum",
  regime: "Regime",
  trend: "Trend",
  accumulation: "Accumulation",
};

// ── Theme-token resolver ─────────────────────────────────────────────────────
// ChartSpec.color may be a token ("primary", "tertiary", "success") or a hex
// ("#aabbcc"). Used here for the colored dot next to each signal row; the
// chart page also uses this logic when creating series.

export function resolveSignalColor(color: string): string {
  if (!color) return t.colors.textDim;
  if (color.startsWith("#") || color.startsWith("rgb") || color.startsWith("hsl")) {
    return color;
  }
  const pal = t.colors as unknown as Record<string, string>;
  return pal[color] ?? color; // fall through to raw string (lightweight-charts accepts named colors)
}

// ── Signal row ────────────────────────────────────────────────────────────────

function CardDetail({ card }: { card: SignalCard }) {
  const block = (title: string, body: string) => (
    <div className="mb-2">
      <div
        className="text-[9px] font-semibold uppercase tracking-wider mb-0.5"
        style={{ color: t.colors.textDim }}
      >
        {title}
      </div>
      <div
        className="text-[11px] whitespace-pre-wrap leading-snug"
        style={{ color: t.colors.textMuted }}
      >
        {body || "—"}
      </div>
    </div>
  );
  return (
    <div
      className="mt-1.5 p-2 rounded"
      style={{
        background: t.colors.bg,
        border: `1px solid ${t.colors.borderLight}`,
      }}
    >
      {block("What", card.what)}
      {block("Basis", card.basis)}
      {block("How to read", card.how_to_read)}
      {block("Failure modes", card.failure_modes)}
      <div
        className="text-[10px] mt-1 pt-1.5"
        style={{ color: t.colors.textDim, borderTop: `1px solid ${t.colors.borderLight}` }}
      >
        Inputs: <span style={{ fontFamily: t.fonts.mono }}>{card.inputs || "—"}</span>
      </div>
    </div>
  );
}

function SignalRow({
  card,
  chartSpec,
  active,
  onToggle,
}: {
  card: SignalCard;
  chartSpec: ChartSpec;
  active: boolean;
  onToggle: () => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const dotColor = resolveSignalColor(chartSpec.color);

  return (
    <div
      className="px-2 py-1.5"
      style={{ borderTop: `1px solid ${t.colors.borderLight}` }}
    >
      <div className="flex items-center gap-2">
        {/* Toggle switch */}
        <button
          onClick={onToggle}
          aria-pressed={active}
          className="flex-shrink-0 relative rounded-full transition-colors"
          style={{
            width: 26,
            height: 14,
            background: active ? dotColor : t.colors.border,
            cursor: "pointer",
            border: "none",
            padding: 0,
          }}
        >
          <span
            className="absolute rounded-full"
            style={{
              width: 10,
              height: 10,
              top: 2,
              left: active ? 14 : 2,
              background: t.colors.text,
              transition: "left 120ms ease-out",
            }}
          />
        </button>

        {/* Color dot + name */}
        <span
          className="w-1.5 h-1.5 rounded-full flex-shrink-0"
          style={{ background: dotColor }}
        />
        <span
          className="text-[11px] flex-1 truncate"
          style={{
            color: active ? t.colors.text : t.colors.textMuted,
            fontWeight: active ? 500 : 400,
          }}
          title={card.name}
        >
          {card.name}
        </span>

        {/* Placement badge */}
        <span
          className="text-[9px] px-1 py-0.5 rounded uppercase tracking-wider"
          style={{
            color: t.colors.textDim,
            background: t.colors.surfaceHover,
            fontFamily: t.fonts.mono,
          }}
          title={`${chartSpec.placement} · ${chartSpec.series_type}`}
        >
          {chartSpec.placement === "overlay" ? "ovr" : "sub"}
        </span>

        {/* Info button */}
        <button
          onClick={() => setExpanded((v) => !v)}
          className="flex-shrink-0 w-4 h-4 rounded-full text-[9px] font-semibold"
          style={{
            background: expanded ? t.colors.primaryLight : "transparent",
            color: expanded ? t.colors.primary : t.colors.textDim,
            border: `1px solid ${expanded ? t.colors.primaryBorder : t.colors.border}`,
            cursor: "pointer",
            lineHeight: "12px",
          }}
          title="Signal details"
          aria-label={`Details for ${card.name}`}
        >
          i
        </button>
      </div>
      {expanded && <CardDetail card={card} />}
    </div>
  );
}

// ── Main component ───────────────────────────────────────────────────────────

export interface SignalToggleState {
  card: SignalCard;
  chartSpec: ChartSpec;
}

export default function SignalTogglePanel({
  coin: _coin,
  activeSlugs,
  onToggle,
  onRegistryLoaded,
}: {
  /** Current market symbol — the scope for per-market localStorage. The
   *  parent owns LS read/write and the toggle-set state; this prop is
   *  documented here so callers know the panel is market-aware. */
  coin: string;
  /** Set of currently-active slugs (controlled by parent). */
  activeSlugs: Set<string>;
  /** Fired when a toggle is flipped. Parent is responsible for fetching
   *  compute() and drawing/removing the series. */
  onToggle: (slug: string, enabled: boolean) => void;
  /** Optional — fires once after the registry loads, with the full list
   *  of {slug: {card, chartSpec}}. Lets the parent look up card/spec for
   *  any slug hydrated from localStorage on mount. */
  onRegistryLoaded?: (registry: Map<string, SignalToggleState>) => void;
}) {
  const [groups, setGroups] = useState<Record<string, SignalToggleState[]>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});

  // Fetch the registry once. It's deterministic — doesn't change per market.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await getChartSignalsByCategory();
        if (cancelled) return;
        const next: Record<string, SignalToggleState[]> = {};
        const registry = new Map<string, SignalToggleState>();
        for (const [cat, items] of Object.entries(res.categories ?? {})) {
          next[cat] = items.map((x) => ({ card: x.card, chartSpec: x.chart_spec }));
          for (const x of items) {
            registry.set(x.card.slug, { card: x.card, chartSpec: x.chart_spec });
          }
        }
        setGroups(next);
        setLoading(false);
        onRegistryLoaded?.(registry);
      } catch (e) {
        if (cancelled) return;
        setError(e instanceof Error ? e.message : String(e));
        setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const totalRegistered = useMemo(
    () => Object.values(groups).reduce((n, arr) => n + arr.length, 0),
    [groups],
  );

  const toggleCategory = useCallback((cat: string) => {
    setCollapsed((prev) => ({ ...prev, [cat]: !prev[cat] }));
  }, []);

  return (
    <div
      className="rounded-xl overflow-hidden flex flex-col"
      style={{
        width: 240,
        flexShrink: 0,
        border: `1px solid ${t.colors.border}`,
        background: t.colors.surface,
      }}
    >
      {/* Header */}
      <div
        className="px-3 py-2.5 flex items-center justify-between"
        style={{
          borderBottom: `1px solid ${t.colors.border}`,
        }}
      >
        <span
          className="text-[11px] font-semibold uppercase tracking-wider"
          style={{ color: t.colors.textMuted, fontFamily: t.fonts.heading }}
        >
          Signals
        </span>
        <span
          className="text-[10px]"
          style={{ color: t.colors.textDim, fontFamily: t.fonts.mono }}
          title={`${activeSlugs.size} active · ${totalRegistered} available`}
        >
          {activeSlugs.size}/{totalRegistered}
        </span>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto" style={{ maxHeight: 640 }}>
        {loading && (
          <div className="p-3 text-[11px]" style={{ color: t.colors.textDim }}>
            Loading registry…
          </div>
        )}
        {error && (
          <div
            className="m-2 p-2 rounded text-[11px]"
            style={{
              background: t.colors.dangerLight,
              color: t.colors.danger,
              border: `1px solid ${t.colors.dangerBorder}`,
            }}
          >
            {error}
          </div>
        )}
        {!loading && !error && totalRegistered === 0 && (
          <div className="p-3 text-[11px]" style={{ color: t.colors.textMuted }}>
            No signals registered.
          </div>
        )}
        {!loading &&
          !error &&
          CATEGORY_ORDER.filter((cat) => (groups[cat]?.length ?? 0) > 0).map((cat) => {
            const items = groups[cat] ?? [];
            const isCollapsed = collapsed[cat];
            const activeInCat = items.filter((i) => activeSlugs.has(i.card.slug)).length;
            return (
              <div key={cat}>
                <button
                  onClick={() => toggleCategory(cat)}
                  className="w-full px-2 py-1.5 flex items-center justify-between"
                  style={{
                    background: t.colors.surfaceHover,
                    borderBottom: `1px solid ${t.colors.borderLight}`,
                    borderTop: `1px solid ${t.colors.borderLight}`,
                    cursor: "pointer",
                  }}
                >
                  <span
                    className="text-[10px] font-semibold uppercase tracking-wider"
                    style={{ color: t.colors.textSecondary }}
                  >
                    {isCollapsed ? "▸" : "▾"} {CATEGORY_LABELS[cat as SignalCategory] ?? cat}
                  </span>
                  <span
                    className="text-[9px]"
                    style={{ color: t.colors.textDim, fontFamily: t.fonts.mono }}
                  >
                    {activeInCat}/{items.length}
                  </span>
                </button>
                {!isCollapsed &&
                  items.map((s) => (
                    <SignalRow
                      key={s.card.slug}
                      card={s.card}
                      chartSpec={s.chartSpec}
                      active={activeSlugs.has(s.card.slug)}
                      onToggle={() =>
                        onToggle(s.card.slug, !activeSlugs.has(s.card.slug))
                      }
                    />
                  ))}
              </div>
            );
          })}
      </div>
    </div>
  );
}

// ── Helpers re-exported for the charts page ─────────────────────────────────

export { loadActiveSlugs, saveActiveSlugs };
