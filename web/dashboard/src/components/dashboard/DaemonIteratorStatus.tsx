"use client";

import { usePolling } from "@/lib/hooks";
import { getIterators, type Iterator } from "@/lib/api";
import { theme as t } from "@/lib/theme";

export function DaemonIteratorStatus() {
  const { data } = usePolling(getIterators, 30000);

  if (!data) return null;

  const enabled = data.iterators.filter((it: Iterator) => it.enabled);
  const disabled = data.iterators.filter((it: Iterator) => !it.enabled);

  return (
    <div className="rounded-lg p-5" style={{ background: t.colors.surface, border: `1px solid ${t.colors.border}` }}>
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-[13px] font-medium"
          style={{ color: t.colors.textMuted, textTransform: "uppercase", letterSpacing: "0.05em", fontFamily: t.fonts.heading }}>
          Daemon Iterators
        </h3>
        <div className="flex gap-3 text-[11px]">
          <span style={{ color: t.colors.success }}>{enabled.length} active</span>
          <span style={{ color: t.colors.textDim }}>{disabled.length} off</span>
        </div>
      </div>

      <div className="flex flex-wrap gap-1.5">
        {data.iterators.map((it: Iterator) => (
          <span
            key={it.name}
            className="px-2 py-1 rounded text-[10px] font-medium"
            style={it.enabled ? {
              background: t.colors.primaryLight,
              color: t.colors.primary,
              border: `1px solid ${t.colors.primaryBorder}`,
            } : {
              background: t.colors.neutralLight,
              color: t.colors.textDim,
              border: `1px solid ${t.colors.border}`,
            }}
            title={`Tiers: ${it.tiers.join(", ")}`}
          >
            {it.name.replace(/_/g, " ")}
          </span>
        ))}
      </div>
    </div>
  );
}
