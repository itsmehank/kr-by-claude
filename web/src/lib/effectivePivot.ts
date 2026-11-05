/**
 * (#253) 래칫 안내 문구 — LLM 판독 pivot 과 트리거가 실제 쓰는 pivot(effective_pivot)이
 * 다를 때만 문구를 돌려준다. 같거나 어느 한쪽이 없으면 null (표시 없음).
 */
export function effectivePivotNote(
  pivot: number | null | undefined,
  effective: number | null | undefined,
): string | null {
  if (pivot == null || effective == null) return null;
  if (pivot === effective) return null;
  return `트리거 기준 ${effective.toLocaleString()}원 (래칫)`;
}
