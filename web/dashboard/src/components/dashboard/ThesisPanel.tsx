"use client";

import { usePolling } from "@/lib/hooks";
import { getAllTheses, type ThesisData } from "@/lib/api";
import { theme as t } from "@/lib/theme";

function ConvictionBar({ conviction, effective }: { conviction: number; effective: number }) {
  const barColor = effective > 0.6 ? t.colors.success : effective > 0.3 ? t.colors.primary : t.colors.danger;
  return (
    <div className="space-y-1.5">
      <div className="flex justify-between text-[11px]">
        <span style={{ color: t.colors.textMuted }}>Conviction</span>
        <span style={{ color: t.colors.text, fontFamily: t.fonts.mono }}>{(effective * 100).toFixed(0)}%</span>
      </div>
      <div className="h-1.5 rounded-full overflow-hidden" style={{ background: t.colors.border }}>
        <div className="h-full rounded-full transition-all duration-500" style={{ width: `${effective * 100}%`, background: barColor }} />
      </div>
      {conviction !== effective && (
        <p className="text-[10px]" style={{ color: t.colors.textDim }}>Raw: {(conviction * 100).toFixed(0)}% (staleness-adjusted)</p>
      )}
    </div>
  );
}

function ThesisCard({ market, thesis }: { market: string; thesis: ThesisData }) {
  // Cap the display at "STALE (>14d)" when age is implausibly large — the stored
  // last_evaluation_ts can be a wrong-year value if the thesis was seeded before
  // the clock was correct, making the raw day count misleading (e.g. "372d ago"
  // when the file was touched 7 days ago).  Once a thesis is past the stale
  // threshold the exact count has no operational value.
  const ageDisplay =
    thesis.age_hours > 336  // > 14 days — well past stale; cap the number
      ? "STALE (>14d)"
      : thesis.age_hours < 24
        ? `${thesis.age_hours.toFixed(1)}h ago`
        : `${(thesis.age_hours / 24).toFixed(1)}d ago`;
  const dirColor = thesis.direction === "long" ? t.colors.success : thesis.direction === "short" ? t.colors.danger : t.colors.textMuted;

  return (
    <div className="rounded-lg p-4" style={{ background: t.colors.surface, border: `1px solid ${t.colors.border}` }}>
      <div className="flex items-center justify-between mb-3">
        <span className="text-[14px] font-semibold" style={{ color: t.colors.text, fontFamily: t.fonts.heading }}>{market}</span>
        <div className="flex gap-1.5">
          <span className="px-2 py-0.5 rounded text-[10px] font-semibold uppercase"
            style={{ background: `${dirColor}18`, color: dirColor, border: `1px solid ${dirColor}35` }}>
            {thesis.direction}
          </span>
          {thesis.is_stale && (
            <span className="px-2 py-0.5 rounded text-[10px] font-semibold uppercase"
              style={{ background: t.colors.dangerLight, color: t.colors.danger, border: `1px solid ${t.colors.dangerBorder}` }}>
              STALE
            </span>
          )}
          {thesis.needs_review && !thesis.is_stale && (
            <span className="px-2 py-0.5 rounded text-[10px] font-semibold uppercase"
              style={{ background: t.colors.warningLight, color: t.colors.warning, border: `1px solid ${t.colors.warningBorder}` }}>
              REVIEW
            </span>
          )}
        </div>
      </div>
      <ConvictionBar conviction={thesis.conviction} effective={thesis.effective_conviction} />
      {thesis.thesis_summary && (
        <p className="text-[12px] mt-3 leading-relaxed line-clamp-2" style={{ color: t.colors.textSecondary }}>{thesis.thesis_summary}</p>
      )}
      <div className="flex justify-between mt-3 text-[11px]" style={{ color: t.colors.textDim }}>
        <span>Updated {ageDisplay}</span>
        {thesis.take_profit_price && <span>TP ${thesis.take_profit_price}</span>}
      </div>
    </div>
  );
}

export function ThesisPanel() {
  const { data, loading } = usePolling(getAllTheses, 30000);
  if (loading || !data) return null;
  const entries = Object.entries(data.theses);
  if (entries.length === 0) {
    return (
      <div className="rounded-lg p-6 text-center" style={{ background: t.colors.surface, border: `1px solid ${t.colors.border}` }}>
        <p className="text-[13px]" style={{ color: t.colors.textMuted }}>No active theses</p>
      </div>
    );
  }
  return (
    <div className="space-y-3">
      {entries.map(([market, thesis]) => <ThesisCard key={market} market={market} thesis={thesis} />)}
    </div>
  );
}
