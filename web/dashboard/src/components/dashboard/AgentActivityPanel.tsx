"use client";

import { useState, useEffect, useRef } from "react";
import { usePolling } from "@/lib/hooks";
import {
  getAgentState,
  abortAgent,
  steerAgent,
  followUpAgent,
  type AgentState,
} from "@/lib/api";
import { theme as t } from "@/lib/theme";

// ── Helpers ────────────────────────────────────────────────────────────────────

function elapsed(isoTs: string | null | undefined): string {
  if (!isoTs) return "";
  const startMs = new Date(isoTs).getTime();
  const diffS = Math.floor((Date.now() - startMs) / 1000);
  if (diffS < 60) return `${diffS}s`;
  if (diffS < 3600) return `${Math.floor(diffS / 60)}m ${diffS % 60}s`;
  return `${Math.floor(diffS / 3600)}h ${Math.floor((diffS % 3600) / 60)}m`;
}

function fmt(n: number): string {
  return n.toLocaleString();
}

// ── Status pill ────────────────────────────────────────────────────────────────

type PillStatus = "idle" | "running" | "aborting";

function statusFromState(s: AgentState): PillStatus {
  if (!s.is_running) return "idle";
  if (s.abort_flag) return "aborting";
  return "running";
}

const PILL_STYLES: Record<PillStatus, React.CSSProperties> = {
  idle: {
    background: t.colors.neutralLight,
    color: t.colors.textMuted,
    border: `1px solid ${t.colors.border}`,
  },
  running: {
    background: t.colors.successLight,
    color: t.colors.success,
    border: `1px solid ${t.colors.successBorder}`,
  },
  aborting: {
    background: t.colors.warningLight,
    color: t.colors.warning,
    border: `1px solid ${t.colors.warningBorder}`,
  },
};

function StatusPill({ status }: { status: PillStatus }) {
  return (
    <span
      className="px-2 py-0.5 rounded text-[11px] font-medium"
      style={PILL_STYLES[status]}
    >
      {status === "running" && <span className="mr-1">&#9679;</span>}
      {status}
    </span>
  );
}

// ── Spinner ────────────────────────────────────────────────────────────────────

function Spinner() {
  return (
    <span
      style={{
        display: "inline-block",
        width: 10,
        height: 10,
        border: `2px solid ${t.colors.success}`,
        borderTopColor: "transparent",
        borderRadius: "50%",
        animation: "spin 0.7s linear infinite",
        verticalAlign: "middle",
      }}
    />
  );
}

// ── Elapsed ticker — refreshes every second independently ─────────────────────

function LiveElapsed({ isoTs }: { isoTs: string | null | undefined }) {
  const [tick, setTick] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setTick((t) => t + 1), 1000);
    return () => clearInterval(id);
  }, []);
  // tick is just to force re-render
  void tick;
  return <>{elapsed(isoTs)}</>;
}

// ── Main component ─────────────────────────────────────────────────────────────

export function AgentActivityPanel() {
  const { data: state } = usePolling(getAgentState, 2000);

  const [expanded, setExpanded] = useState(false);
  const [steerText, setSteerText] = useState("");
  const [followUpText, setFollowUpText] = useState("");
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  // Spinner animation keyframe injected once
  const styleInjectedRef = useRef(false);
  useEffect(() => {
    if (styleInjectedRef.current) return;
    styleInjectedRef.current = true;
    const s = document.createElement("style");
    s.textContent = `@keyframes spin { to { transform: rotate(360deg); } }`;
    document.head.appendChild(s);
  }, []);

  // ── Action helpers ──────────────────────────────────────────────────────────

  async function runAction(fn: () => Promise<unknown>) {
    setBusy(true);
    setActionError(null);
    try {
      await fn();
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "Request failed");
    } finally {
      setBusy(false);
    }
  }

  function handleAbort() {
    runAction(() => abortAgent("user_requested via dashboard"));
  }

  function handleSteer(e: React.FormEvent) {
    e.preventDefault();
    const msg = steerText.trim();
    if (!msg) return;
    runAction(async () => {
      await steerAgent(msg);
      setSteerText("");
    });
  }

  function handleFollowUp(e: React.FormEvent) {
    e.preventDefault();
    const msg = followUpText.trim();
    if (!msg) return;
    runAction(async () => {
      await followUpAgent(msg);
      setFollowUpText("");
    });
  }

  // ── Render ──────────────────────────────────────────────────────────────────

  const status: PillStatus = state ? statusFromState(state) : "idle";
  const isRunning = state?.is_running ?? false;
  const isAborting = state?.abort_flag ?? false;
  const steeringDepth = state?.steering_queue?.length ?? 0;
  const followUpDepth = state?.follow_up_queue?.length ?? 0;
  const tokensUsed = state?.tokens_used_session ?? null;
  const tokensBudget = state?.tokens_budget_session ?? null;

  const cardStyle: React.CSSProperties = {
    background: t.colors.surface,
    border: `1px solid ${t.colors.border}`,
    borderRadius: t.radius,
    padding: "16px 20px",
  };

  return (
    <div style={cardStyle}>
      {/* ── Header row ─────────────────────────────────────────────────────── */}
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-2">
          <h3
            className="text-[13px] font-medium"
            style={{
              color: t.colors.textMuted,
              textTransform: "uppercase",
              letterSpacing: "0.05em",
              fontFamily: t.fonts.heading,
            }}
          >
            Agent
          </h3>
          <StatusPill status={status} />
        </div>

        <div className="flex items-center gap-2">
          {/* STOP button — visible always, disabled when not running */}
          <button
            onClick={handleAbort}
            disabled={!isRunning || isAborting || busy}
            style={{
              background: isRunning && !isAborting ? t.colors.danger : t.colors.neutralLight,
              color: isRunning && !isAborting ? "#fff" : t.colors.textDim,
              border: `1px solid ${isRunning && !isAborting ? t.colors.dangerBorder : t.colors.border}`,
              borderRadius: "6px",
              padding: "4px 14px",
              fontSize: 12,
              fontWeight: 700,
              fontFamily: t.fonts.heading,
              cursor: isRunning && !isAborting ? "pointer" : "not-allowed",
              opacity: busy ? 0.6 : 1,
              letterSpacing: "0.04em",
            }}
          >
            {isAborting ? "ABORTING…" : "STOP"}
          </button>

          {/* Expand toggle */}
          <button
            onClick={() => setExpanded((v) => !v)}
            style={{
              background: "transparent",
              border: `1px solid ${t.colors.border}`,
              borderRadius: "6px",
              padding: "4px 10px",
              fontSize: 11,
              color: t.colors.textMuted,
              cursor: "pointer",
              fontFamily: t.fonts.mono,
            }}
          >
            {expanded ? "▲" : "▼"}
          </button>
        </div>
      </div>

      {/* ── Live status row (when running) ───────────────────────────────────── */}
      {isRunning && (
        <div
          className="mt-3 flex flex-wrap items-center gap-3"
          style={{ fontFamily: t.fonts.mono, fontSize: 12 }}
        >
          <span style={{ color: t.colors.textSecondary }}>
            {state?.current_turn != null && (
              <span>Turn {state.current_turn}&nbsp;·&nbsp;</span>
            )}
            {state?.current_tool ? (
              <>
                <Spinner />
                <span style={{ color: t.colors.text, marginLeft: 5 }}>
                  {state.current_tool.name}
                </span>
                {state.current_tool.started_at && (
                  <span style={{ color: t.colors.textMuted, marginLeft: 5 }}>
                    (<LiveElapsed isoTs={state.current_tool.started_at} />)
                  </span>
                )}
              </>
            ) : (
              <span style={{ color: t.colors.textMuted }}>running</span>
            )}
          </span>
        </div>
      )}

      {/* ── Metrics row ──────────────────────────────────────────────────────── */}
      <div
        className="mt-2 flex flex-wrap gap-4"
        style={{ fontFamily: t.fonts.mono, fontSize: 11 }}
      >
        {tokensUsed != null && tokensBudget != null && (
          <span style={{ color: t.colors.textMuted }}>
            Tokens:{" "}
            <span style={{ color: t.colors.textSecondary }}>
              {fmt(tokensUsed)} / {fmt(tokensBudget)}
            </span>
          </span>
        )}
        {(steeringDepth > 0 || followUpDepth > 0) && (
          <span style={{ color: t.colors.textMuted }}>
            Queue:{" "}
            <span
              style={{
                color: steeringDepth > 0 ? t.colors.warning : t.colors.textSecondary,
              }}
            >
              {steeringDepth} steering
            </span>{" "}
            ·{" "}
            <span
              style={{
                color: followUpDepth > 0 ? t.colors.tertiary : t.colors.textSecondary,
              }}
            >
              {followUpDepth} follow-up
            </span>
          </span>
        )}
        {!isRunning && steeringDepth === 0 && followUpDepth === 0 && tokensUsed == null && (
          <span style={{ color: t.colors.textDim }}>No active agent run</span>
        )}
      </div>

      {/* ── Action inputs ─────────────────────────────────────────────────────── */}
      <div className="mt-3 space-y-2">
        {actionError && (
          <p style={{ color: t.colors.danger, fontSize: 11, fontFamily: t.fonts.mono }}>
            {actionError}
          </p>
        )}

        {isRunning ? (
          /* When running: steer input */
          <form onSubmit={handleSteer} className="flex gap-2">
            <input
              value={steerText}
              onChange={(e) => setSteerText(e.target.value)}
              placeholder="Steer agent…"
              disabled={busy}
              style={{
                flex: 1,
                background: t.colors.bg,
                border: `1px solid ${t.colors.border}`,
                borderRadius: "6px",
                padding: "5px 10px",
                fontSize: 12,
                color: t.colors.text,
                fontFamily: t.fonts.mono,
                outline: "none",
              }}
            />
            <button
              type="submit"
              disabled={busy || !steerText.trim()}
              style={{
                background: t.colors.primaryLight,
                border: `1px solid ${t.colors.primaryBorder}`,
                borderRadius: "6px",
                padding: "5px 12px",
                fontSize: 12,
                color: t.colors.primary,
                fontFamily: t.fonts.heading,
                cursor: busy || !steerText.trim() ? "not-allowed" : "pointer",
                opacity: busy ? 0.6 : 1,
              }}
            >
              Send
            </button>
          </form>
        ) : (
          /* When idle: queue follow-up input */
          <form onSubmit={handleFollowUp} className="flex gap-2">
            <input
              value={followUpText}
              onChange={(e) => setFollowUpText(e.target.value)}
              placeholder="Queue follow-up…"
              disabled={busy}
              style={{
                flex: 1,
                background: t.colors.bg,
                border: `1px solid ${t.colors.border}`,
                borderRadius: "6px",
                padding: "5px 10px",
                fontSize: 12,
                color: t.colors.text,
                fontFamily: t.fonts.mono,
                outline: "none",
              }}
            />
            <button
              type="submit"
              disabled={busy || !followUpText.trim()}
              style={{
                background: t.colors.tertiaryLight,
                border: `1px solid ${t.colors.tertiaryBorder}`,
                borderRadius: "6px",
                padding: "5px 12px",
                fontSize: 12,
                color: t.colors.tertiary,
                fontFamily: t.fonts.heading,
                cursor: busy || !followUpText.trim() ? "not-allowed" : "pointer",
                opacity: busy ? 0.6 : 1,
              }}
            >
              Queue
            </button>
          </form>
        )}
      </div>

      {/* ── Expanded: raw state JSON ──────────────────────────────────────────── */}
      {expanded && state && (
        <div className="mt-3">
          <pre
            style={{
              background: t.colors.bg,
              border: `1px solid ${t.colors.borderLight}`,
              borderRadius: "6px",
              padding: "10px 12px",
              fontSize: 10,
              color: t.colors.textSecondary,
              fontFamily: t.fonts.mono,
              overflowX: "auto",
              maxHeight: 260,
              overflowY: "auto",
            }}
          >
            {JSON.stringify(state, null, 2)}
          </pre>
        </div>
      )}
    </div>
  );
}
