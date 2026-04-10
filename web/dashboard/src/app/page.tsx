import { AccountSummary } from "@/components/dashboard/AccountSummary";
import { EquityCurve } from "@/components/dashboard/EquityCurve";
import { HealthPanel } from "@/components/dashboard/HealthPanel";
import { PositionCards } from "@/components/dashboard/PositionCards";
import { ThesisPanel } from "@/components/dashboard/ThesisPanel";
import { NewsFeed } from "@/components/dashboard/NewsFeed";
import { DaemonIteratorStatus } from "@/components/dashboard/DaemonIteratorStatus";

export default function DashboardPage() {
  return (
    <div className="p-8 space-y-6 max-w-[1400px]">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-semibold"
            style={{ color: "#f3f4f6", fontFamily: "'Space Grotesk', system-ui, sans-serif" }}>
            Dashboard
          </h2>
          <p className="text-[13px] mt-1" style={{ color: "#7E756F" }}>
            Real-time trading system overview
          </p>
        </div>
        <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg text-[12px]"
          style={{ background: "#1e1f26", color: "#7E756F", border: "1px solid #353849" }}>
          <div className="w-1.5 h-1.5 rounded-full" style={{ background: "#22c55e", boxShadow: "0 0 4px #22c55e" }} />
          Auto-refreshing
        </div>
      </div>

      {/* Row 1: Account + Health */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 items-start">
        <div className="lg:col-span-2">
          <AccountSummary />
        </div>
        <HealthPanel />
      </div>

      {/* Row 2: Equity curve */}
      <EquityCurve />

      {/* Row 3: Positions + Iterators */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div>
          <h3 className="text-[13px] font-medium mb-3"
            style={{ color: "#7E756F", textTransform: "uppercase", letterSpacing: "0.05em", fontFamily: "'Space Grotesk', system-ui" }}>
            Positions
          </h3>
          <PositionCards />
        </div>
        <DaemonIteratorStatus />
      </div>

      {/* Row 4: Thesis + News */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div>
          <h3 className="text-[13px] font-medium mb-3"
            style={{ color: "#7E756F", textTransform: "uppercase", letterSpacing: "0.05em", fontFamily: "'Space Grotesk', system-ui" }}>
            Thesis
          </h3>
          <ThesisPanel />
        </div>
        <NewsFeed />
      </div>
    </div>
  );
}
