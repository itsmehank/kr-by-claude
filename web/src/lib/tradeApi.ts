// trade_api(:8001) 전용 클라이언트. 기존 lib/api.ts(:8000)와 분리. 에러 envelope 을 그대로 보존.
const BASE = "/trade-api";

export class TradeApiError extends Error {
  status: number; code: string; data: unknown; requestId: string | null;
  constructor(status: number, code: string, message: string, data: unknown, requestId: string | null) {
    super(message);
    this.status = status; this.code = code; this.data = data; this.requestId = requestId;
  }
}

export async function tradeApi<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!res.ok) {
    let env: { error?: { code?: string; message?: string; data?: unknown; requestId?: string | null } } = {};
    try { env = await res.json(); } catch { /* 본문 없음 */ }
    const e = env.error ?? {};
    throw new TradeApiError(res.status, e.code ?? "http-error", e.message ?? "", e.data ?? null, e.requestId ?? null);
  }
  return res.json();
}

export const postJson = <T,>(path: string, body: unknown) =>
  tradeApi<T>(path, { method: "POST", body: JSON.stringify(body) });
