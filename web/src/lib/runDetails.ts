// 주말 LLM 분류(weekend) 실행 상세의 정규화 헬퍼.
//
// PipelinePage 의 확장 상세 렌더러는 chain(중첩 step) 구조를 가정한다. weekend 의 details 는
// 평면 구조라(실행중={weekend_progress,heartbeat_at} / 완료={processed,...,failed_tickers}),
// step 렌더러가 "(no data)"로 떨군다. 이 헬퍼는 weekend-shape 만 감지·정규화하고, 그 외에는
// null 을 돌려 PipelinePage 가 기존 step 렌더를 그대로 쓰게 한다(순수 함수, 백엔드 무변).

export interface FailedTicker {
  symbol: string;
  error: string;
  attempts: number;
}

export interface WeekendProgress {
  done: number;
  total: number;
  inFlight: number;
  failed: number;
}

export interface WeekendRunView {
  summary: { label: string; value: string }[];
  failedTickers: FailedTicker[];
  progress: WeekendProgress | null;
  stale: boolean;
}

const STALE_MS = 120_000; // heartbeat 2분 초과 + running → 중단(stale) 의심 (heartbeat 주기 30초)

function num(v: unknown): number | null {
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

/** weekend 실행 상세를 정규화. weekend-shape 가 아니면 null(→ 기존 step 렌더 사용). */
export function summarizeWeekendRun(
  details: Record<string, unknown> | null,
  status: string,
  nowMs: number,
): WeekendRunView | null {
  if (!details || typeof details !== "object") return null;
  // weekend·daily_delta 는 항상 failed_tickers 를 포함(weekend.py·daily_delta.py), 실행중은
  // weekend_progress. bare "processed" 는 entry_params({processed,failures}) 와도 겹쳐 false-positive
  // 이므로 감지에서 제외 — 정확히 weekend-shape(failed_tickers/weekend_progress)만 잡는다.
  const hasProgress = "weekend_progress" in details;
  const isDone = "failed_tickers" in details;
  if (!hasProgress && !isDone) return null; // chain/entry_params/기타 → 기존 step 렌더

  // 진행(실행중) — weekend_progress.{done,total,in_flight,failed}
  let progress: WeekendProgress | null = null;
  const wp = details["weekend_progress"];
  if (wp && typeof wp === "object") {
    const p = wp as Record<string, unknown>;
    progress = {
      done: num(p["done"]) ?? 0,
      total: num(p["total"]) ?? 0,
      inFlight: num(p["in_flight"]) ?? 0,
      failed: num(p["failed"]) ?? 0,
    };
  }

  // 실패 종목 — [{symbol,error,attempts}]
  const failedTickers: FailedTicker[] = [];
  const ft = details["failed_tickers"];
  if (Array.isArray(ft)) {
    for (const f of ft) {
      if (f && typeof f === "object") {
        const o = f as Record<string, unknown>;
        failedTickers.push({
          symbol: String(o["symbol"] ?? "?"),
          error: String(o["error"] ?? ""),
          attempts: num(o["attempts"]) ?? 0,
        });
      }
    }
  }

  // 완료 요약 — 평면 카운트 필드
  const summary: { label: string; value: string }[] = [];
  const SUMMARY_FIELDS: [string, string][] = [
    ["processed", "처리"],
    ["candidates", "후보"],
    ["failures", "실패"],
    ["skipped_existing", "이어하기 제외"],
  ];
  for (const [key, label] of SUMMARY_FIELDS) {
    const n = num(details[key]);
    if (n !== null) summary.push({ label, value: String(n) });
  }
  const integrity = details["integrity_skipped"];
  if (Array.isArray(integrity) && integrity.length > 0) {
    summary.push({ label: "무결성 skip", value: String(integrity.length) });
  }

  // stale — 실행중인데 heartbeat 가 2분 넘게 끊김
  let stale = false;
  if (status === "running") {
    const hb = details["heartbeat_at"];
    if (typeof hb === "string") {
      const hbMs = Date.parse(hb);
      if (Number.isFinite(hbMs) && nowMs - hbMs > STALE_MS) stale = true;
    }
  }

  return { summary, failedTickers, progress, stale };
}
