# ⑧ abort 자가리셋 skip — 설계

## 문제

토요일 weekend 분류가 종목에 `entry`/`watch` 딱지를 붙이고, 평일마다 evaluate_pivot이
그 종목들을 결정론 게이트→LLM으로 점검해 `go_now`/`wait`/`abort`를 판정한다.

분류 딱지는 **weekend(또는 daily_delta)에서만** 바뀐다. 따라서 어떤 종목이 평일에
`abort`(base가 명백히 무효화 — 가망 없음) 판정을 받아도, 다음 토요일 재분류 전까지는
여전히 "활성 종목"으로 남아 **매 평일 다시 비싼 LLM으로 재평가**된다. 거의 매번 또
`abort`가 나온다 → LLM 호출 비용 낭비 + 의미 없는 반복.

## 해결

**"현재 분류 딱지를 받은 뒤에 한 번이라도 `abort` 난 종목은, 다음 재분류 때까지
evaluate_pivot 재평가에서 skip한다."** 분류 자체는 바꾸지 않는다(weekend 전용 철학 유지).

### 판단 — 새 필드 없음, `prior_classification_at` 정확 매칭

이미 저장된 값의 매칭만으로 판단한다(새 컬럼/플래그/저장값 불필요). abort 기록 시
`store.insert_trigger_log`가 **`prior_classification_at = active_row["classified_at"]`**
(그 abort가 *어느 분류에 대해* 내려졌는지)를 함께 저장한다:

- `trigger_evaluation_log`: `decision='abort'` 행의 `prior_classification_at` (그 abort가 평가 대상으로 삼은 분류 시각)
- 활성 종목 행의 `classified_at` (현재 분류 시각, `get_active_with_current`이 이미 실어옴)

**판정:** 그 종목의 abort 행 중 `prior_classification_at == 현재 classified_at` 인 것이
있으면 → skip. ("현재 분류에 대해 내려진 abort가 있다.")

> **왜 시각 비교(`evaluated_at > classified_at`)가 아니라 정확 매칭인가:**
> `prior_classification_at`은 abort가 *실제로 평가 대상으로 삼은 분류*의 ground truth라
> 시간 추론(평가 시각이 분류 시각보다 항상 나중이라는 가정)이 불필요하다. 재실행/백필로
> 과거 as_of를 재평가해도 그때의 분류가 그대로 기록되므로 정확하다. (운영 DB 검증:
> abort 12/12·wait 18/18 행 모두 `prior_classification_at` 채워짐.)

### 자가리셋

weekend/daily_delta가 재분류하면 `classified_at`이 새로 찍힌다 → 옛 abort 행의
`prior_classification_at`(옛 분류 시각)이 현재 `classified_at`(새 분류 시각)과 불일치 →
**자동 skip 해제, 재평가 재개**. 재분류 후 또 abort면 새 분류 시각으로 다시 기록되어 다시
skip. 별도 초기화 작업 없음. (intraday 재분류에도 견고 — 순서 무관하게 매칭으로 동작.)

## 구현

### 헬퍼: `_aborted_since_classification(conn, active)`

`evaluate_pivot.py`에 추가. active 종목 중 "분류 이후 abort" 집합을 반환.

```python
def _aborted_since_classification(conn: Connection, active: list[dict]) -> set[str]:
    symbols = [a["symbol"] for a in active]
    if not symbols:
        return set()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT symbol, prior_classification_at "
            "FROM trigger_evaluation_log "
            "WHERE decision = 'abort' AND symbol = ANY(%s)",
            (symbols,),
        )
        abort_pairs = {(r[0], r[1]) for r in cur.fetchall()}
    result: set[str] = set()
    for a in active:
        cls_at = a.get("classified_at")
        # 보완 1: None 방어 — classified_at 이 None 이면 매칭 시도 안 함(안전한 기본값).
        # abort 행의 prior 가 NULL 이면 (symbol, NULL) 쌍이 어떤 timestamp 와도 불일치 → 자연 skip-안함.
        if cls_at is not None and (a["symbol"], cls_at) in abort_pairs:
            result.add(a["symbol"])
    return result
```

`(symbol, prior_classification_at)` 쌍 집합을 만들어 `(symbol, 현재 classified_at)` 정확
매칭. active 심볼만 1회 쿼리 → 효율적. 두 timestamptz 는 동일 `weekly_classification.classified_at`
값이 round-trip 된 것이라 정확히 일치(같은 DB 값).

### 필터 적용 — `run()`의 `elif not force:` 블록

기존 멱등 skip(`_already_evaluated_symbols`)과 **합집합**으로 `triggered`에서 제외:

```python
    elif not force:
        done = _already_evaluated_symbols(conn, as_of)
        aborted = _aborted_since_classification(conn, active)
        skip = done | aborted
        triggered = [(a, t) for (a, t) in triggered if a["symbol"] not in skip]
```

`force`(replace)일 때는 abort skip **미적용**(강제 재분석이 목적).

### 보완 2: 관측성 — `abort_skipped` 카운트

`run()` 결과 dict(`{evaluated, failures, active, triggered}`)에 `abort_skipped` 키 추가.
이 값이 비정상적으로 크면 "weekend 재분류가 밀려 깨진 종목이 쌓인다"는 신호 — 별개
이슈(weekend 신뢰성)를 공짜로 가시화. ⑥의 surface 철학과 동일.

카운트는 **필터 전 `triggered`에서 abort로 인해 제거된 종목 수**로 정의:
`abort_skipped = len([a for (a, t) in triggered if a["symbol"] in aborted])`
(필터 적용 전에 계산. `done`과 겹치는 종목이 있어도 "트리거됐으나 abort-class였던 수"로서
의미 있음. `triggered`/`evaluated`는 종전 의미 유지.)

## 불변 / 범위

- **분류 변경 없음** (철학 유지). `force`·rerun-멱등 skip과 합성.
- `wait`(일시적 약세)는 abort 아님 → skip 대상 아님 → 매일 재평가(회복 가능). 정상.
- 범위 밖: weekend 실행 신뢰성/알림(별개 이슈, abort_skipped로 가시화만), 자동 ignore 강등(철학상 제외).

## 보완 3: 숨은 이득 2가지 (근거 보존)

이 작업은 비용 절감 외 두 효과가 더 있다 — 향후 "왜 이렇게?" 혼란 방지를 위해 명시:

1. **정합성 안전장치.** abort(=base 무효화) 후, stale pivot로 결정론 게이트가 breakout을
   다시 쏘더라도 skip되므로 **무효화된 base에서 매수 신호(go_now→entry_params)가 나가는 것을
   차단**. 단순 비용 절감이 아니라 방법론적으로도 옳다(무효화된 base는 weekend가 새 base/pivot을
   부여해야 함).
2. **weekend 실패 복원력 개선.** weekend가 실패해 재분류가 안 돼도, 깨진 종목은
   dormant(비용 0·거짓신호 0). 현재(매일 재평가로 비용 출혈)보다 나음.

## 테스트 (결정론, LLM 없음 — 헬퍼 단위)

`tests/test_abort_skip.py`:

1. **현재 분류에 대한 abort** — abort 행의 `prior_classification_at == active classified_at` → skip 집합에 포함.
2. **옛 분류에 대한 abort (재분류됨)** — abort `prior_classification_at` ≠ 현재 classified_at → 미포함(자가리셋).
3. **abort 없음 / `wait`만** — abort 행 없음 또는 decision='wait' → 미포함.
4. **classified_at None 방어 / abort prior NULL** — None/불일치 → 미포함(크래시 없음).

run() 통합 필터는 단순 집합 차집합이라 기존 evaluate_pivot 테스트가 회귀 커버.
