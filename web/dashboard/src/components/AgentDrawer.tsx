"use client";

/**
 * AgentDrawer — persistent floating panel that wraps AgentActivityPanel.
 *
 * Mounted once in app/layout.tsx so it persists across page navigation.
 * Overlays content — never pushes layout.
 *
 * Collapsed state: 56px badge in bottom-right corner.
 *   - Shows status dot + agent icon + mini token bar.
 *   - Click to expand.
 *   - If agent is running, badge pulses green.
 *
 * Expanded state: 400px panel slides in from right, full height.
 *   - No backdrop/modal — page remains fully interactive.
 *   - Close via X button, badge click, or pressing `a` (when no input focused).
 *
 * Keyboard shortcut: press `a` (lowercase) to toggle when no input is focused.
 * Persistence: open/closed state in localStorage key `agent.drawerOpen.v1`.
 */

import { useState, useEffect, useRef, useCallback } from "react";
import { usePolling } from "@/lib/hooks";
import {
  getAgentState,
  abortAgent,
  steerAgent,
  followUpAgent,
  type AgentState,
} from "@/lib/api";
import { theme as t } from "@/lib/theme";

// ── helpers ──────────────────────────────────────────────────────────────────

function elapsed(isoTs: string | null | undefined): string {
  if (!isoTs) return "";
  const diffS = Math.floor((Date.now() - new Date(isoTs).getTime()) / 1000);
  if (diffS < 60) return `${diffS}s`;
  if (diffS < 3600) return `${Math.floor(diffS / 60)}m ${diffS % 60}s`;
  return `${Math.floor(diffS / 3600)}h ${Math.floor((diffS % 3600) / 60)}m`;
}

function fmt(n: number): string {
  return n.toLocaleString();
}

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
        animation: "agentSpin 0.7s linear infinite",
        verticalAlign: "middle",
      }}
    />
  );
}

function LiveElapsed({ isoTs }: { isoTs: string | null | undefined }) {
  const [tick, setTick] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setTick((n) => n + 1), 1000);
    return () => clearInterval(id);
  }, []);
  void tick;
  return <>{elapsed(isoTs)}</>;
}

// ── Token mini-bar (used in collapsed badge) ──────────────────────────────────

function TokenMiniBar({
  used,
  budget,
}: {
  used: number | null;
  budget: number | null;
}) {
  if (used == null || budget == null || budget === 0) return null;
  const pct = Math.min(1, used / budget);
  const color =
    pct > 0.85 ? t.colors.danger : pct > 0.6 ? t.colors.warning : t.colors.success;
  return (
    <div
      title={`${fmt(used)} / ${fmt(budget)} tokens`}
      style={{
        width: 36,
        height: 4,
        background: t.colors.borderLight,
        borderRadius: 2,
        overflow: "hidden",
      }}
    >
      <div
        style={{
          width: `${Math.round(pct * 100)}%`,
          height: "100%",
          background: color,
          borderRadius: 2,
          transition: "width 0.4s ease",
        }}
      />
    </div>
  );
}

// ── AgentIcon ─────────────────────────────────────────────────────────────────

function AgentIcon({ color }: { color: string }) {
  return (
    <svg
      width="18"
      height="18"
      viewBox="0 0 24 24"
      fill="none"
      stroke={color}
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M12 2a4 4 0 0 1 4 4v2H8V6a4 4 0 0 1 4-4z" />
      <rect x="4" y="8" width="16" height="12" rx="2" />
      <path d="M9 14h.01M15 14h.01" />
    </svg>
  );
}

// ── Main component ─────────────────────────────────────────────────────────────

const LS_KEY = "agent.drawerOpen.v1";

function readLsOpen(): boolean {
  try {
    const raw = localStorage.getItem(LS_KEY);
    return raw === null ? false : JSON.parse(raw) === true;
  } catch {
    return false;
  }
}

export function AgentDrawer() {
  // Drawer open/closed
  const [open, setOpen] = useState(false);

  // Hydrate from localStorage after mount (avoids SSR mismatch)
  useEffect(() => {
    setOpen(readLsOpen());
  }, []);

  // Persist on every change
  const toggle = useCallback(() => {
    setOpen((prev) => {
      const next = !prev;
      try {
        localStorage.setItem(LS_KEY, JSON.stringify(next));
      } catch {/* ignore */}
      return next;
    });
  }, []);

  // Keyboard shortcut: `a` when no input focused
  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (e.key !== "a" && e.key !== "A") return;
      // Skip if modifier keys held (cmd+a = select-all etc.)
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      const active = document.activeElement;
      if (
        active &&
        (active.tagName === "INPUT" ||
          active.tagName === "TEXTAREA" ||
          (active as HTMLElement).isContentEditable)
      ) {
        return;
      }
      e.preventDefault();
      toggle();
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [toggle]);

  // Inject spin animation once
  const styleInjectedRef = useRef(false);
  useEffect(() => {
    if (styleInjectedRef.current) return;
    styleInjectedRef.current = true;
    const s = document.createElement("style");
    s.textContent = `@keyframes agentSpin { to { transform: rotate(360deg); } }
@keyframes agentPulse { 0%,100% { opacity:1; } 50% { opacity:0.45; } }`;
    document.head.appendChild(s);
  }, []);

  // Polling — runs regardless of drawer open/closed state
  const { data: state } = usePolling(getAgentState, 2000);

  // Interaction state
  const [steerText, setSteerText] = useState("");
  const [followUpText, setFollowUpText] = useState("");
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [jsonExpanded, setJsonExpanded] = useState(false);

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

  // Derived state
  const status: PillStatus = state ? statusFromState(state) : "idle";
  const isRunning = state?.is_running ?? false;
  const isAborting = state?.abort_flag ?? false;
  const steeringDepth = state?.steering_queue?.length ?? 0;
  const followUpDepth = state?.follow_up_queue?.length ?? 0;
  const tokensUsed = state?.tokens_used_session ?? null;
  const tokensBudget = state?.tokens_budget_session ?? null;

  // Status dot color
  const dotColor =
    status === "running"
      ? t.colors.success
      : status === "aborting"
      ? t.colors.warning
      : t.colors.textDim;

  // ── Collapsed badge ──────────────────────────────────────────────────────────
  const badge = (
    <button
      onClick={toggle}
      title="Open Agent panel (press A)"
      style={{
        position: "fixed",
        bottom: 24,
        right: 24,
        zIndex: 50,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        gap: 5,
        width: 56,
        padding: "10px 0",
        background: t.colors.surface,
        border: `1px solid ${status === "running" ? t.colors.successBorder : t.colors.border}`,
        borderRadius: "12px",
        cursor: "pointer",
        boxShadow: status === "running"
          ? `0 0 0 2px ${t.colors.successLight}`
          : "0 4px 20px rgba(0,0,0,0.4)",
        transition: "border-color 0.2s, box-shadow 0.2s",
      }}
    >
      {/* Pulsing dot */}
      <span
        style={{
          width: 8,
          height: 8,
          borderRadius: "50%",
          background: dotColor,
          animation: status === "running" ? "agentPulse 1.4s ease-in-out infinite" : "none",
        }}
      />
      {/* Agent icon */}
      <AgentIcon color={t.colors.textMuted} />
      {/* Mini token bar */}
      <TokenMiniBar used={tokensUsed} budget={tokensBudget} />
    </button>
  );

  // ── Expanded panel ───────────────────────────────────────────────────────────
  const panel = (
    <div
      style={{
        position: "fixed",
        top: 0,
        right: 0,
        bottom: 0,
        width: 400,
        zIndex: 50,
        display: "flex",
        flexDirection: "column",
        background: t.colors.surface,
        borderLeft: `1px solid ${t.colors.border}`,
        boxShadow: "-4px 0 32px rgba(0,0,0,0.5)",
        transform: open ? "translateX(0)" : "translateX(100%)",
        transition: "transform 150ms ease-out",
        // pointer-events off when hidden so the page is fully clickable
        pointerEvents: open ? "auto" : "none",
      }}
      aria-label="Agent panel"
      role="complementary"
    >
      {/* Header */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "14px 16px",
          borderBottom: `1px solid ${t.colors.border}`,
          flexShrink: 0,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <AgentIcon color={t.colors.textMuted} />
          <span
            style={{
              fontSize: 13,
              fontWeight: 500,
              color: t.colors.textMuted,
              textTransform: "uppercase",
              letterSpacing: "0.05em",
              fontFamily: t.fonts.heading,
            }}
          >
            Agent
          </span>
          <StatusPill status={status} />
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          {/* STOP button */}
          <button
            onClick={handleAbort}
            disabled={!isRunning || isAborting || busy}
            style={{
              background: isRunning && !isAborting ? t.colors.danger : t.colors.neutralLight,
              color: isRunning && !isAborting ? "#fff" : t.colors.textDim,
              border: `1px solid ${isRunning && !isAborting ? t.colors.dangerBorder : t.colors.border}`,
              borderRadius: "6px",
              padding: "4px 12px",
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

          {/* Close button */}
          <button
            onClick={toggle}
            title="Close (press A)"
            style={{
              background: "transparent",
              border: `1px solid ${t.colors.border}`,
              borderRadius: "6px",
              padding: "4px 8px",
              fontSize: 14,
              color: t.colors.textMuted,
              cursor: "pointer",
              lineHeight: 1,
            }}
          >
            ✕
          </button>
        </div>
      </div>

      {/* Scrollable body */}
      <div
        style={{
          flex: 1,
          overflowY: "auto",
          padding: "16px",
          display: "flex",
          flexDirection: "column",
          gap: 12,
        }}
      >
        {/* Live status row */}
        {isRunning && (
          <div
            style={{
              display: "flex",
              flexWrap: "wrap",
              alignItems: "center",
              gap: 8,
              fontFamily: t.fonts.mono,
              fontSize: 12,
              padding: "8px 12px",
              background: t.colors.bg,
              borderRadius: "6px",
              border: `1px solid ${t.colors.successBorder}`,
            }}
          >
            {state?.current_turn != null && (
              <span style={{ color: t.colors.textSecondary }}>
                Turn {state.current_turn}
              </span>
            )}
            {state?.current_tool ? (
              <span style={{ color: t.colors.text }}>
                <Spinner />{" "}
                <span style={{ marginLeft: 5 }}>{state.current_tool.name}</span>
                {state.current_tool.started_at && (
                  <span style={{ color: t.colors.textMuted, marginLeft: 5 }}>
                    (<LiveElapsed isoTs={state.current_tool.started_at} />)
                  </span>
                )}
              </span>
            ) : (
              <span style={{ color: t.colors.textMuted }}>running…</span>
            )}
          </div>
        )}

        {/* Token + queue metrics */}
        <div
          style={{
            display: "flex",
            flexWrap: "wrap",
            gap: 12,
            fontFamily: t.fonts.mono,
            fontSize: 11,
          }}
        >
          {tokensUsed != null && tokensBudget != null && (
            <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              <span style={{ color: t.colors.textMuted }}>
                Tokens:{" "}
                <span style={{ color: t.colors.textSecondary }}>
                  {fmt(tokensUsed)} / {fmt(tokensBudget)}
                </span>
              </span>
              {/* Token progress bar */}
              <div
                style={{
                  width: 160,
                  height: 4,
                  background: t.colors.borderLight,
                  borderRadius: 2,
                  overflow: "hidden",
                }}
              >
                <div
                  style={{
                    width: `${Math.min(100, Math.round((tokensUsed / tokensBudget) * 100))}%`,
                    height: "100%",
                    background:
                      tokensUsed / tokensBudget > 0.85
                        ? t.colors.danger
                        : tokensUsed / tokensBudget > 0.6
                        ? t.colors.warning
                        : t.colors.success,
                    borderRadius: 2,
                    transition: "width 0.4s ease",
                  }}
                />
              </div>
            </div>
          )}

          {(steeringDepth > 0 || followUpDepth > 0) && (
            <span style={{ color: t.colors.textMuted }}>
              Queue:{" "}
              <span
                style={{
                  color:
                    steeringDepth > 0 ? t.colors.warning : t.colors.textSecondary,
                }}
              >
                {steeringDepth} steering
              </span>{" "}
              ·{" "}
              <span
                style={{
                  color:
                    followUpDepth > 0 ? t.colors.tertiary : t.colors.textSecondary,
                }}
              >
                {followUpDepth} follow-up
              </span>
            </span>
          )}

          {!isRunning &&
            steeringDepth === 0 &&
            followUpDepth === 0 &&
            tokensUsed == null && (
              <span style={{ color: t.colors.textDim }}>No active agent run</span>
            )}
        </div>

        {/* Error */}
        {actionError && (
          <p
            style={{
              color: t.colors.danger,
              fontSize: 11,
              fontFamily: t.fonts.mono,
              margin: 0,
            }}
          >
            {actionError}
          </p>
        )}

        {/* Input — steer when running, follow-up when idle */}
        {isRunning ? (
          <form
            onSubmit={handleSteer}
            style={{ display: "flex", gap: 6 }}
          >
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
                padding: "6px 10px",
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
                padding: "6px 14px",
                fontSize: 12,
                color: t.colors.primary,
                fontFamily: t.fonts.heading,
                cursor: busy || !steerText.trim() ? "not-allowed" : "pointer",
                opacity: busy ? 0.6 : 1,
                whiteSpace: "nowrap",
              }}
            >
              Send
            </button>
          </form>
        ) : (
          <form
            onSubmit={handleFollowUp}
            style={{ display: "flex", gap: 6 }}
          >
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
                padding: "6px 10px",
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
                padding: "6px 14px",
                fontSize: 12,
                color: t.colors.tertiary,
                fontFamily: t.fonts.heading,
                cursor: busy || !followUpText.trim() ? "not-allowed" : "pointer",
                opacity: busy ? 0.6 : 1,
                whiteSpace: "nowrap",
              }}
            >
              Queue
            </button>
          </form>
        )}

        {/* Divider */}
        <hr style={{ border: "none", borderTop: `1px solid ${t.colors.borderLight}` }} />

        {/* Raw state toggle */}
        <button
          onClick={() => setJsonExpanded((v) => !v)}
          style={{
            background: "transparent",
            border: `1px solid ${t.colors.border}`,
            borderRadius: "6px",
            padding: "4px 10px",
            fontSize: 11,
            color: t.colors.textMuted,
            cursor: "pointer",
            fontFamily: t.fonts.mono,
            textAlign: "left",
          }}
        >
          {jsonExpanded ? "▲ Hide raw state" : "▼ Show raw state"}
        </button>

        {jsonExpanded && state && (
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
              maxHeight: 300,
              overflowY: "auto",
              margin: 0,
            }}
          >
            {JSON.stringify(state, null, 2)}
          </pre>
        )}
      </div>

      {/* Footer hint */}
      <div
        style={{
          padding: "8px 16px",
          borderTop: `1px solid ${t.colors.borderLight}`,
          fontSize: 10,
          color: t.colors.textDim,
          fontFamily: t.fonts.mono,
          flexShrink: 0,
        }}
      >
        Press <kbd>A</kbd> to toggle · <kbd>Cmd+K</kbd> for commands
      </div>
    </div>
  );

  return (
    <>
      {/* Collapsed badge — hidden when panel is open */}
      {!open && badge}

      {/* Expanded panel — always in DOM, animated via transform */}
      {panel}
    </>
  );
}
