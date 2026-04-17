import { EquityLedger } from "@/components/dashboard/EquityLedger";
import { EquityCurve } from "@/components/dashboard/EquityCurve";
import { HealthBanner } from "@/components/dashboard/HealthPanel";
import { DetailedPositionCards } from "@/components/dashboard/DetailedPositionCards";
import { ThesisPanel } from "@/components/dashboard/ThesisPanel";
import { NewsFeed } from "@/components/dashboard/NewsFeed";
import { DaemonIteratorStatus } from "@/components/dashboard/DaemonIteratorStatus";
import { EntryCritiquePanel } from "@/components/dashboard/EntryCritiquePanel";

export default function DashboardPage() {
  return (
    <div className="p-8 space-y-6 max-w-[1400px]">
      {/* Header — includes the System Health status strip inline */}
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <div>
          <h2 className="text-2xl font-semibold"
            style={{ color: "#f3f4f6", fontFamily: "'Space Grotesk', system-ui, sans-serif" }}>
            Dashboard
          </h2>
          <p className="text-[13px] mt-1" style={{ color: "#7E756F" }}>
            Real-time trading system overview
          </p>
        </div>
        {/* System Health — collapsed to a thin status strip next to the title */}
        <HealthBanner />
      </div>

      {/* Row 1: Equity Ledger — now spans full width since Health moved to banner */}
      <EquityLedger />

      {/* Row 2: Equity curve */}
      <EquityCurve />

      {/* Row 3: Positions + Iterators */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div>
          <h3 className="text-[13px] font-medium mb-3"
            style={{ color: "#7E756F", textTransform: "uppercase", letterSpacing: "0.05em", fontFamily: "'Space Grotesk', system-ui" }}>
            Positions
          </h3>
          <DetailedPositionCards />
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

      {/* Row 5: Entry Critiques */}
      <EntryCritiquePanel />
    </div>
  );
}
