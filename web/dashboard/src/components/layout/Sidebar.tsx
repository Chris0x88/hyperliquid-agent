"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { theme as t } from "@/lib/theme";
import { getHealth } from "@/lib/api";

const NAV_ITEMS = [
  { href: "/", label: "Dashboard", icon: "M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6" },
  { href: "/charts", label: "Charts", icon: "M3 13.125C3 12.504 3.504 12 4.125 12h2.25c.621 0 1.125.504 1.125 1.125v6.75C7.5 20.496 6.996 21 6.375 21h-2.25A1.125 1.125 0 013 19.875v-6.75zM9.75 8.625c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125v11.25c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V8.625zM16.5 4.125c0-.621.504-1.125 1.125-1.125h2.25C20.496 3 21 3.504 21 4.125v15.75c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V4.125z" },
  { href: "/control", label: "Control", icon: "M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.066 2.573c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.573 1.066c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.066-2.573c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z M15 12a3 3 0 11-6 0 3 3 0 016 0z" },
  { href: "/logs", label: "Logs", icon: "M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" },
  { href: "/strategies", label: "Strategies", icon: "M13 7h8m0 0v8m0-8l-8 8-4-4-6 6" },
  { href: "/alerts", label: "Alerts", icon: "M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9" },
];

export function Sidebar() {
  const pathname = usePathname();
  const [systemOk, setSystemOk] = useState<boolean | null>(null);

  useEffect(() => {
    const check = () =>
      getHealth()
        .then((h) => setSystemOk(h.processes.daemon.running && h.processes.telegram_bot.running))
        .catch(() => setSystemOk(false));
    check();
    const id = setInterval(check, 30_000);
    return () => clearInterval(id);
  }, []);

  const statusColor = systemOk === null ? t.colors.textMuted : systemOk ? t.colors.success : "#ef4444";
  const statusLabel = systemOk === null ? "Checking..." : systemOk ? "System Online" : "System Degraded";

  return (
    <aside
      className="w-[220px] min-h-screen flex flex-col"
      style={{ background: t.colors.bg, borderRight: `1px solid ${t.colors.border}` }}
    >
      {/* Logo */}
      <div className="px-5 py-5" style={{ borderBottom: `1px solid ${t.colors.border}` }}>
        <div className="flex items-center gap-2.5">
          <div
            className="w-8 h-8 rounded-lg flex items-center justify-center"
            style={{ background: `linear-gradient(135deg, ${t.colors.primary}, ${t.colors.secondary})` }}
          >
            <span className="text-sm font-bold text-white">HL</span>
          </div>
          <div>
            <h1
              className="text-[15px] font-semibold"
              style={{ color: t.colors.text, fontFamily: t.fonts.heading }}
            >
              Mission Control
            </h1>
            <p className="text-[11px]" style={{ color: t.colors.textMuted }}>
              v0.1.0 &middot; Local
            </p>
          </div>
        </div>
      </div>

      {/* Navigation */}
      <nav className="flex-1 px-3 py-4 space-y-0.5">
        {NAV_ITEMS.map((item) => {
          const active =
            item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
          return (
            <Link
              key={item.href}
              href={item.href}
              className="flex items-center gap-2.5 px-3 py-2 rounded-lg text-[13px] font-medium transition-all duration-150"
              style={
                active
                  ? { background: t.colors.primaryLight, color: t.colors.primary }
                  : { color: t.colors.textMuted }
              }
              onMouseEnter={(e) => {
                if (!active) {
                  e.currentTarget.style.color = t.colors.text;
                  e.currentTarget.style.background = t.colors.surfaceHover;
                }
              }}
              onMouseLeave={(e) => {
                if (!active) {
                  e.currentTarget.style.color = t.colors.textMuted;
                  e.currentTarget.style.background = "transparent";
                }
              }}
            >
              <svg className="w-4 h-4 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={1.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d={item.icon} />
              </svg>
              {item.label}
            </Link>
          );
        })}
      </nav>

      {/* Docs link */}
      <div className="px-3 pb-2">
        <a
          href="http://127.0.0.1:4321"
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-center gap-2.5 px-3 py-2 rounded-lg text-[13px] font-medium transition-all"
          style={{ color: t.colors.textMuted }}
          onMouseEnter={(e) => { e.currentTarget.style.color = t.colors.tertiary; e.currentTarget.style.background = t.colors.surfaceHover; }}
          onMouseLeave={(e) => { e.currentTarget.style.color = t.colors.textMuted; e.currentTarget.style.background = "transparent"; }}
        >
          <svg className="w-4 h-4 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={1.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 6.042A8.967 8.967 0 006 3.75c-1.052 0-2.062.18-3 .512v14.25A8.987 8.987 0 016 18c2.305 0 4.408.867 6 2.292m0-14.25a8.966 8.966 0 016-2.292c1.052 0 2.062.18 3 .512v14.25A8.987 8.987 0 0018 18a8.967 8.967 0 00-6 2.292m0-14.25v14.25" />
          </svg>
          Docs
          <svg className="w-3 h-3 ml-auto opacity-40" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
          </svg>
        </a>
      </div>

      {/* Status footer */}
      <div className="px-5 py-3" style={{ borderTop: `1px solid ${t.colors.border}` }}>
        <div className="flex items-center gap-2">
          <div
            className="w-2 h-2 rounded-full"
            style={{ background: statusColor, boxShadow: `0 0 6px ${statusColor}` }}
          />
          <span className="text-[11px]" style={{ color: t.colors.textMuted }}>
            {statusLabel}
          </span>
        </div>
      </div>
    </aside>
  );
}
