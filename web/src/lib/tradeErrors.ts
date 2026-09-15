// 토스 에러 코드(요약 문서 §7) + 자체 가드(guard/*) → 한국어. unknown 은 code 그대로(스펙 요구).
const MESSAGES: Record<string, string> = {
  // 인증·권한
  "invalid-token": "토큰이 유효하지 않습니다 (서버가 재발급합니다)",
  "expired-token": "토큰이 만료되었습니다 (서버가 재발급합니다)",
  "token-revoked": "다른 곳에서 토큰이 재발급되어 무효화됨 — 토스 호출 프로세스가 2개 이상인지 확인",
  "edge-blocked": "허용 IP 미등록 또는 인증 헤더 누락 — 토스 WTS 설정 > Open API > 허용 IP 확인",
  forbidden: "권한이 없습니다",
  // 요청 검증
  "invalid-request": "요청 값 오류 (호가 단위·수량·가격·필수값)",
  "confirm-high-value-required": "1억원 이상 주문은 고액 주문 확인이 필요합니다",
  "account-header-required": "계좌 정보가 누락되었습니다 (TOSS_ACCOUNT_SEQ)",
  "unsupported-content-type": "요청 형식 오류",
  // 상태 충돌
  "request-in-progress": "같은 주문이 처리 중입니다 — 잠시 후 상태를 확인하세요",
  "already-filled": "이미 체결된 주문입니다",
  "already-canceled": "이미 취소된 주문입니다",
  "already-modified": "이미 정정된 주문입니다",
  "already-rejected": "이미 거부된 주문입니다",
  "already-processing": "해당 주문에 정정/취소가 진행 중입니다",
  "opposite-pending-order-exists": "같은 종목에 반대 방향 대기 주문이 있습니다",
  // 주문 실행 불가
  "insufficient-buying-power": "매수 가능 금액이 부족합니다",
  "order-hours-closed": "현재는 주문 접수 불가 시간입니다",
  "stock-restricted": "거래가 제한된 종목입니다",
  "price-out-of-range": "상·하한가 범위를 벗어난 가격입니다",
  "order-type-not-allowed": "현재 사용할 수 없는 호가 유형입니다",
  "prerequisite-required": "약관 동의·교육 이수·위험 고지가 필요합니다 (토스 앱에서 진행)",
  "market-not-supported-for-stock": "해당 종목은 이 시장에서 거래할 수 없습니다",
  "investor-exchange-not-integrated": "투자자지시 거래소가 통합(SOR)이 아닙니다",
  "order-limit-exceeded": "주문 한도를 초과했습니다",
  "idempotency-key-conflict": "같은 주문 ID로 다른 내용이 요청되었습니다 — 미리보기를 다시 실행하세요",
  "account-restricted": "이 계좌 유형은 해당 주문을 할 수 없습니다",
  "max-order-amount-exceeded": "30억원 이상 주문은 접수할 수 없습니다",
  "stock-not-found": "종목을 찾을 수 없습니다",
  "account-not-found": "계좌를 찾을 수 없습니다",
  "order-not-found": "주문을 찾을 수 없습니다",
  "rate-limit-exceeded": "요청 한도 초과 — 잠시 후 다시 시도",
  "edge-rate-limit-exceeded": "요청 한도 초과 — 잠시 후 다시 시도",
  "internal-error": "토스 서버 오류",
  maintenance: "토스 서버 점검 중",
  // 자체 가드
  "guard/preview-required": "미리보기가 없거나 만료되었습니다 — 미리보기를 다시 실행하세요",
  "guard/preview-mismatch": "미리보기한 내용과 주문 내용이 다릅니다 — 미리보기를 다시 실행하세요",
  "guard/side-invalid": "주문 방향은 BUY 또는 SELL 이어야 합니다",
  "guard/order-type-invalid": "호가 유형은 LIMIT 또는 MARKET 이어야 합니다",
  "guard/price-required": "지정가 주문은 가격이 필요합니다",
  "guard/price-forbidden": "시장가 주문에는 가격을 넣지 않습니다",
  "guard/quantity-invalid": "수량은 1 이상의 정수여야 합니다",
  "guard/tick-size": "호가 단위에 맞지 않는 가격입니다",
  "guard/price-out-of-range": "상·하한가 범위를 벗어난 가격입니다",
  "guard/price-limit-unavailable": "상한가를 조회할 수 없어 시장가 금액을 계산할 수 없습니다",
  "guard/max-order-amount": "1건 주문 금액 상한을 초과했습니다",
  "guard/max-daily-amount": "1일 매수 누적 상한을 초과했습니다",
  "guard/sellable-exceeded": "판매 가능 수량을 초과했습니다",
  "guard/sellable-unavailable": "판매 가능 수량을 조회할 수 없어 매도를 막았습니다",
  "guard/symbol-unpriced": "시세를 조회할 수 없는 종목입니다(상장폐지·미거래)",
  "guard/confirm-high-value-required": "1억원 이상 주문은 고액 확인 체크가 필요합니다",
  "guard/max-order-amount-exceeded": "30억원 이상 주문은 접수할 수 없습니다",
  "guard/account-seq-missing": "TOSS_ACCOUNT_SEQ 가 설정되지 않았습니다 — 계좌 확인 후 .env 에 고정",
};

export function errorMessage(code: string, fallback: string): string {
  const known = MESSAGES[code];
  if (known) return known;
  return fallback ? `${code} · ${fallback}` : code;
}
