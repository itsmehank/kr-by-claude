// (#207 회신 20) 시스템 표지 코드 → 사람이 읽는 문구. known_warnings 는 Signals 화면 "주의사항" 칩으로 그대로 노출되므로
// 내부 태그는 여기서 변환한다. 매핑이 없는 코드는 원문 그대로.
export const WARNING_LABELS: Record<string, string> = {
  "volume_regime_unverified_#207": "거래량 정의 미확정 — 2026-09-28 부터 KRX 일별 거래량에 애프터마켓 합산 추정(#207)",
};

export function warningLabel(code: string): string {
  return WARNING_LABELS[code] ?? code;
}
