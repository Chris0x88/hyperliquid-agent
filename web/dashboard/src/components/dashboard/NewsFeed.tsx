"use client";

import { usePolling } from "@/lib/hooks";
import { getCatalysts } from "@/lib/api";
import { theme as t } from "@/lib/theme";

interface Catalyst {
  title?: string;
  summary?: string;
  source?: string;
  severity?: string;
  timestamp?: number;
  timestamp_ms?: number;
  [key: string]: unknown;
}

function CatalystItem({ item }: { item: Catalyst }) {
  const ts = item.timestamp_ms || item.timestamp || 0;
  const date = ts > 0 ? new Date(ts > 1e12 ? ts : ts * 1000) : null;
  const sevStyles: Record<string, { bg: string; text: string; border: string }> = {
    critical: { bg: t.colors.dangerLight, text: t.colors.danger, border: t.colors.dangerBorder },
    high: { bg: t.colors.warningLight, text: t.colors.warning, border: t.colors.warningBorder },
    medium: { bg: t.colors.tertiaryLight, text: t.colors.tertiary, border: t.colors.tertiaryBorder },
    low: { bg: t.colors.neutralLight, text: t.colors.neutral, border: "rgba(126,117,111,0.2)" },
  };

  return (
    <div className="py-3" style={{ borderBottom: `1px solid ${t.colors.borderLight}` }}>
      <p className="text-[13px] leading-relaxed line-clamp-2" style={{ color: t.colors.text }}>
        {item.title || item.summary || JSON.stringify(item).slice(0, 100)}
      </p>
      <div className="flex items-center gap-2 mt-1.5">
        {item.severity && (() => {
          const s = sevStyles[item.severity] || sevStyles.low;
          return (
            <span className="px-2 py-0.5 rounded text-[10px] font-medium"
              style={{ background: s.bg, color: s.text, border: `1px solid ${s.border}` }}>
              {item.severity}
            </span>
          );
        })()}
        {item.source && <span className="text-[11px]" style={{ color: t.colors.textDim }}>{item.source}</span>}
        {date && <span className="text-[11px]" style={{ color: t.colors.textDim }}>{date.toLocaleDateString()}</span>}
      </div>
    </div>
  );
}

export function NewsFeed() {
  const { data, loading } = usePolling(() => getCatalysts(15) as Promise<{ catalysts: Catalyst[] }>, 60000);
  return (
    <div className="rounded-lg p-5" style={{ background: t.colors.surface, border: `1px solid ${t.colors.border}` }}>
      <h3 className="text-[13px] font-medium mb-3"
        style={{ color: t.colors.textMuted, textTransform: "uppercase", letterSpacing: "0.05em", fontFamily: t.fonts.heading }}>
        Catalysts
      </h3>
      <div className="max-h-72 overflow-y-auto" style={{ scrollbarWidth: "thin", scrollbarColor: `${t.colors.border} transparent` }}>
        {loading || !data ? (
          <p className="text-[13px]" style={{ color: t.colors.textDim }}>Connecting...</p>
        ) : data.catalysts.length === 0 ? (
          <p className="text-[13px]" style={{ color: t.colors.textDim }}>No catalysts ingested yet</p>
        ) : (
          data.catalysts.map((item, i) => <CatalystItem key={i} item={item} />)
        )}
      </div>
    </div>
  );
}
