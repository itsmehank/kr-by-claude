# LLM 출력 store 견고성 (검증) 설계

날짜: 2026-06-07
대상(변경): `kr_pipeline/llm_runner/store.py`(insert_classification·insert_trigger_log + 검증 헬퍼), 신규 `kr_pipeline/llm_runner/risk_flags.py`
대상(무변경·검증만): `kr_pipeline/llm_runner/daily_delta.py`·`evaluate_pivot.py`(호출부 try/except 그대로 활용), `prompts/analyze_chart_v3.md`(taxonomy 설명 SSOT — 코드 상수와 수동 동기화)

## 배경 / 문제

LLM 결과(JSON)를 DB 저장 시 검증이 없어, AI 가 항목을 빠뜨리거나 잘못된 값을 내도 그대로 흘러간다.
- **classification (1a)**: `insert_classification`(`store.py:70`)이 `result["classification"]` 하드인덱싱. 누락 → KeyError(종목별 try/except 에 삼켜짐, 원인 불명확). **잘못된 enum 값(예 "buy")은 무검증으로 저장**(컬럼 VARCHAR(20)).
- **decision (1a)**: `insert_trigger_log`(`store.py:227`)이 `result["decision"]` 하드인덱싱 — 동일 문제.
- **risk_flags (1c)**: 프롬프트 §taxonomy 가 **정확히 14종**만 허용하는데 코드 검증이 없어, 목록 밖 값/오타도 `json.dumps(result.get("risk_flags", []))` 로 그대로 저장.

영향: 큰 사고보다는 "조용히 잘못 저장/실패"하는 신뢰도 문제. 명확한 거부/경고로 바꾼다.

## 목표

저장 직전 검증을 추가한다: classification·decision 은 유효 enum 아니면 **거부(ValueError, 종목별 로그)**, risk_flags 는 14종 화이트리스트 밖을 **drop+경고(분류는 저장)**.

## 핵심 결정 (브레인스토밍 합의)

1. classification/decision = 필수값 → **거부**(가짜 보정 안 함).
2. risk_flags = 부가정보 → **목록 밖만 버리고 경고**, 레코드 유지.
3. 숫자 sanity 는 **비목표**(기준 모호 → 별도/후속).
4. risk_flags 14종은 **코드 상수(SSOT)** + 프롬프트 수동 동기화. thresholds.py 는 피함(enum 이라 의존성맵 체크리스트 트리거 회피).

## 비목표 (Non-goals)

- 숫자 sanity(pivot/base/stop/target 정합) — 별도.
- 프롬프트 내용 변경(taxonomy 는 이미 프롬프트에 존재; 코드 상수만 신설).
- classification 자동 보정(거부지 보정 아님).
- 다른 LLM 단계(C/D 후속).

## 아키텍처

### 1. risk_flags 화이트리스트 — 신규 `kr_pipeline/llm_runner/risk_flags.py`
```python
# analyze_chart_v3.md §taxonomy 와 수동 동기화 (추가/삭제 시 양쪽).
RISK_FLAGS_TAXONOMY = frozenset({
    "climax_run", "late_stage_base", "extended_from_ma", "faulty_pivot",
    "low_volume_breakout", "narrow_base", "wide_and_loose", "thin_liquidity_us_only",
    "prior_uptrend_insufficient", "volume_contraction_on_advance",
    "reverse_split_distortion", "unfavorable_market_context",
    "etf_methodology_mismatch", "handle_quality",
})  # 14종
```

### 2. 검증 헬퍼 — `store.py`
```python
_VALID_CLASSIFICATIONS = frozenset({"entry", "watch", "ignore"})
_VALID_DECISIONS = frozenset({"go_now", "wait", "abort"})

def _validate_classification(result: dict) -> str:
    c = result.get("classification")
    if c not in _VALID_CLASSIFICATIONS:
        raise ValueError(f"invalid classification: {c!r} (expected entry/watch/ignore)")
    return c

def _validate_decision(result: dict) -> str:
    d = result.get("decision")
    if d not in _VALID_DECISIONS:
        raise ValueError(f"invalid decision: {d!r} (expected go_now/wait/abort)")
    return d

def _clean_risk_flags(flags) -> list[str]:
    """RISK_FLAGS_TAXONOMY 밖 값은 drop + log.warning. None/비list 는 []."""
    if not isinstance(flags, list):
        return []
    cleaned, dropped = [], []
    for f in flags:
        (cleaned if f in RISK_FLAGS_TAXONOMY else dropped).append(f)
    if dropped:
        log.warning("dropped unknown risk_flags: %s", dropped)
    return cleaned
```

### 3. 적용
- `insert_classification`: 함수 시작에서 `classification = _validate_classification(result)`(하드인덱싱 제거, 거부 시 ValueError). risk_flags 저장을 `json.dumps(_clean_risk_flags(result.get("risk_flags", [])))` 로.
- `insert_backfill_classification`(`store.py:91`): **동일 처리** — backfill 도 같은 analyze_chart_v3 출력을 `classification_backfill` 에 저장하며 `result["classification"]` 하드인덱싱 + risk_flags 무검증이라 같은 문제. `_validate_classification` + `_clean_risk_flags` 적용.
- `insert_trigger_log`: 함수 시작에서 `decision = _validate_decision(result)`. INSERT 의 `result["decision"]` → `decision`.

## 데이터 흐름 / 에러 처리

- 잘못된 classification/decision → ValueError → 호출부 종목별 try/except 가 잡아 **로그 + rollback** → 조용한 실패 대신 원인 명확. 확인된 호출부: `daily_delta.py`(:94 try)·`weekend.py`(:139 try)→insert_classification, `backfill.py`(배치 루프 :75 try/except)→insert_backfill_classification, `evaluate_pivot.py`(:66 try)→insert_trigger_log. (backfill·entry_params 와 마찬가지로 dry-run 은 insert 자체를 skip 하므로 검증도 미실행 — 단 본 검증 헬퍼는 순수 함수라 단위 테스트로 직접 커버.)
- 정상: 검증 통과 → 종전대로 저장. risk_flags 의 무효값만 제거(유효 flag·분류는 보존).

## 테스트

- `_validate_classification`: entry/watch/ignore 통과(반환값 일치); 누락(None)·"buy" → ValueError(match="invalid classification").
- `_validate_decision`: go_now/wait/abort 통과; 누락·"maybe" → ValueError.
- `_clean_risk_flags`: ["climax_run","bogus","narrow_base"] → ["climax_run","narrow_base"](bogus drop); None/문자열 입력 → []; 전부 유효 → 그대로.
- `insert_classification` 라운드트립(db): 유효 classification + risk_flags=["narrow_base","bogus"] → 저장된 risk_flags JSON 에 narrow_base 만, bogus 없음. 잘못된 classification → ValueError(저장 안 됨).
- `insert_trigger_log` 라운드트립/단위: 잘못된 decision → ValueError.
- 회귀: 기존 store/daily_delta/evaluate_pivot 테스트 통과(유효값 사용), base 대비 0.

## 파일 변경 예상

- 신규: `kr_pipeline/llm_runner/risk_flags.py`.
- 변경: `store.py`(헬퍼 3 + insert_classification·**insert_backfill_classification**·insert_trigger_log 적용).
- 테스트: `tests/test_llm_runner_store.py`(또는 신규)에 검증 단위 + 라운드트립.

## 후속 (별도 후보)

- 숫자 sanity(pivot/base/stop/target 정합).
- measurements/contraction_* dead 출력 정리(C).
- entry_params 5컬럼 signals/web 노출(D).
