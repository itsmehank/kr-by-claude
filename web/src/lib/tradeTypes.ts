// trade_api(:8001) 응답 타입. 금액·수량은 전부 string(Decimal) — 절대 Number()로 계산하지 않는다.
export interface Health { dryRun: boolean; maxOrderKrw: string; maxDailyKrw: string; accountSeq: number | null }
export interface AccountOut { accountNo: string; accountSeq: number; accountType: string }
export interface Money { krw: string; usd: string | null }
export interface HoldingsItem {
  symbol: string; name: string; marketCountry: string; currency: string;
  quantity: string; lastPrice: string; averagePurchasePrice: string;
  marketValue: Money; profitLoss: Money; dailyProfitLoss: Money; cost: Money;
}
export interface HoldingsOverview {
  totalPurchaseAmount: Money; marketValue: Money; profitLoss: Money; dailyProfitLoss: Money; items: HoldingsItem[];
}
export interface MismatchOut { symbol: string; name: string; tossQty: string; positionQty: string | null; kind: "missing" | "qty_diff" | string }
export interface HoldingsOut { overview: HoldingsOverview; mismatch: MismatchOut[] }
export interface SearchHit { ticker: string; name: string; market: string }
export interface OrderbookEntry { price: string; volume: string }
export interface QuoteOut {
  symbol: string; name: string | null;
  price: { symbol: string; timestamp: string | null; lastPrice: string; currency: string };
  orderbook: { timestamp: string | null; currency: string; asks: OrderbookEntry[]; bids: OrderbookEntry[] };
  limits: { timestamp: string; currency: string; upperLimitPrice: string | null; lowerLimitPrice: string | null };
  warnings: { warningType: string; exchange: string | null; startDate: string | null; endDate: string | null }[];
}
export interface BuyingPower { currency: string; cashBuyingPower: string }
export interface Sellable { sellableQuantity: string }
export interface EstimateOut { amount: string; amountBasis: string; commission: string | null; total: string }
export interface PreviewOut {
  previewToken: string; clientOrderId: string | null; request: Record<string, unknown>;
  estimate: EstimateOut; warnings: string[]; dryRun: boolean; expiresInSec: number;
}
export interface OrderSubmitOut { dryRun: boolean; orderId: string | null; clientOrderId: string | null; auditId: number; request: Record<string, unknown> }
export interface OperationOut { dryRun: boolean; orderId: string | null; auditId: number }
export interface OrderExecution {
  filledQuantity: string; averageFilledPrice: string | null; filledAmount: string | null;
  commission: string | null; tax: string | null; filledAt: string | null; settlementDate: string | null;
}
export interface Order {
  orderId: string; symbol: string; side: string; orderType: string; timeInForce: string; status: string;
  price: string | null; quantity: string; orderAmount: string | null; currency: string;
  orderedAt: string; canceledAt: string | null; execution: OrderExecution;
}
export interface PaginatedOrders { orders: Order[]; nextCursor: string | null; hasNext: boolean }
