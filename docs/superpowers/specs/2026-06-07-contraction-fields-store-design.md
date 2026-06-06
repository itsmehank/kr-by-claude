# contraction_* 출력 보존 (measurements 합쳐 저장) 설계

날짜: 2026-06-07
대상: `kr_pipeline/llm_runner/store.py` (insert_classification·insert_backfill_classification + 신규 헬퍼)
무변경: 프롬프트, DB 스키마(measurements JSONB 그대로), measurements 소비자

## 배경 / 문제

analyze_chart_v3 가 VCP 패턴일 때 최상위 출력으로 `contraction_count`(int 2-6)·`contraction_depths_pct`(% 배열)를 낸다(프롬프트 §323-324, §390-391; Minervini footprint "40W 31/3 4T" 검증용). 그러나 **코드 어디서도 읽거나 저장하지 않아 버려진다**(전수 grep: web 문서 텍스트 1곳 외 소비처 없음).

반면 `measurements`(nested object)는 `weekly_classification.measurements` JSONB 에 저장된다(store.py:117·191) — 읽는 곳은 없으나 감사용 보관. contraction_* 만 그 보관에서 빠진다.

## 목표

contraction_count·contraction_depths_pct 를 measurements JSONB 보관 블록에 **합쳐 저장**한다(버려지지 않게). 프롬프트·스키마 변경 없음.

## 핵심 결정 (브레인스토밍 합의)

- (가) 저장(measurements 에 병합) — 프롬프트/스키마 무변경, VCP footprint 보존. 채택.
- 비채택: (나) 프롬프트에서 제거(기능 손실 + LLM 재검증), (다) 그대로 방치.

## 비목표

- measurements 를 읽는 소비자 추가(여전히 감사용 보관).
- 별도 컬럼화·프롬프트 변경.

## 아키텍처

### store.py 신규 헬퍼 `_measurements_json(result) -> str | None`
```python
def _measurements_json(result: dict) -> str | None:
    """measurements 블록에 최상위 contraction_count/contraction_depths_pct 를 병합해 JSON 문자열로.

    VCP footprint(최상위 출력)가 버려지지 않게 measurements 감사 블록에 합친다.
    measurements·contraction 둘 다 없으면 None(기존 None 동작 보존).
    """
    m = result.get("measurements")
    cc = result.get("contraction_count")
    cd = result.get("contraction_depths_pct")
    if m is None and cc is None and cd is None:
        return None
    blob = dict(m) if isinstance(m, dict) else {}
    if cc is not None:
        blob["contraction_count"] = cc
    if cd is not None:
        blob["contraction_depths_pct"] = cd
    return json.dumps(blob)
```

### 적용
- `insert_classification`(store.py:117)·`insert_backfill_classification`(:191)의 measurements 저장 값
  `json.dumps(result.get("measurements")) if result.get("measurements") is not None else None`
  → `_measurements_json(result)`.

## 데이터 흐름 / 엣지

- gates(`apply_phase1_gates`)는 저장 전 result 를 in-place 일부 키만 수정하고 measurements/contraction 은 건드리지 않음(확인) → contraction_* 가 저장 시점까지 보존, fail-soft(원본 복귀) 경로에서도 유지.
- contraction_* 는 measurements 와 **별개 최상위 키**라 병합 시 키 충돌 없음.
- **비-VCP/contraction 없음**: blob == measurements → 기존 저장값과 동일(기존 테스트 무영향). measurements·contraction 둘 다 없음 → None(종전과 동일).
- measurements 가 dict 아님(이상치) → `{}` 기반에 contraction 만.

## 테스트

- `_measurements_json` 단위: ① measurements만 → 동일 키 JSON ② + contraction → 병합(contraction_count·depths 포함) ③ 둘 다 None → None ④ contraction만(measurements None) → contraction 포함 ⑤ measurements 비-dict → {} + contraction.
- 라운드트립(db): insert_classification 에 measurements + contraction_count/depths 주입 → 저장된 measurements JSONB 파싱 시 contraction_* 포함 확인. (기존 `test_measurements_column_exists_and_stores` 패턴 재사용.)
- 회귀: 기존 `test_measurements_column_exists_and_stores`(contraction 없음) 통과, base 대비 신규 0.

## 파일 변경 예상

- 변경: `store.py`(헬퍼 1 + 적용 2곳).
- 테스트: `tests/test_llm_runner_store.py`(헬퍼 단위 + 라운드트립).
