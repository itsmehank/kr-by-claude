import ModeBanner from "../components/trading/ModeBanner";
import OrderPanel from "../components/trading/OrderPanel";
import OrdersTable from "../components/trading/OrdersTable";
import HoldingsTable from "../components/trading/HoldingsTable";

// 토스증권 Open API 매매 — 별도 프로세스 trade_api(:8001). spec docs/superpowers/specs/2026-09-14-toss-trading-page-design.md
export default function TradingPage() {
  return (
    <div className="space-y-3">
      <ModeBanner />
      <div className="grid gap-3 lg:grid-cols-[380px_1fr]">
        <OrderPanel />
        <div className="space-y-3"><OrdersTable /><HoldingsTable /></div>
      </div>
    </div>
  );
}
