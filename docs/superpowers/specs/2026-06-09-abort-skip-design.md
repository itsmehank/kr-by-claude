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

### 판단 — 새 필드 없음

이미 저장된 두 시각의 비교만으로 판단한다(새 컬럼/플래그/저장값 불필요):

- `trigger_evaluation_log`: `decision='abort'` 행의 `evaluated_at` (abort 시각)
- 활성 종목 행의 `classified_at` (현재 분류 시각, `get_active_with_current`이 이미 실어옴)

**판정:** 그 종목의 최신 abort `evaluated_at` > 현재 `classified_at` → skip.

### 자가리셋

weekend/daily_delta가 재분류하면 `classified_at`이 새로 찍혀 앞서간다 → 옛 abort가
"분류 이전"이 되어 비교만으로 **자동 skip 해제, 재평가 재개**. 재분류 후 또 abort면
다시 skip. 별도 초기화 작업 없음. (intraday 재분류에도 견고 — 순서 무관하게 시각 비교로 동작.)

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
            "SELECT symbol, MAX(evaluated_at) FROM trigger_evaluation_log "
            "WHERE decision = 'abort' AND symbol = ANY(%s) GROUP BY symbol",
            (symbols,),
        )
        latest_abort = {r[0]: r[1] for r in cur.fetchall()}
    result: set[str] = set()
    for a in active:
        ab = latest_abort.get(a["symbol"])
        cls_at = a.get("classified_at")
        # 보완 1: None 방어 — 둘 중 하나라도 None이면 skip 안 함(안전한 기본값)
        if ab is not None and cls_at is not None and ab > cls_at:
            result.add(a["symbol"])
    return result
```

`MAX(evaluated_at)`는 최신 abort. `MAX > classified_at` ⟺ classified_at 이후 abort가
적어도 하나 존재. active 심볼만 1회 쿼리 → 효율적.

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

`run()` 결과 dict에 abort로 skip된 수를 추가. 이 값이 비정상적으로 크면 "weekend 재분류가
밀려 깨진 종목이 쌓인다"는 신호 — 별개 이슈(weekend 신뢰성)를 공짜로 가시화. ⑥의 surface
철학과 동일. 카운트는 `triggered`에서 실제로 제거된 abort 종목 수(`aborted ∩ pre-filter triggered`).

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

1. **분류 이후 abort** — classified_at 이후 `evaluated_at`의 abort 행 → skip 집합에 포함.
2. **분류 이전 abort만 (재분류됨)** — abort `evaluated_at` < classified_at → 미포함(자가리셋).
3. **abort 없음 / `wait`만** — abort 행 없음 또는 decision='wait' → 미포함.
4. **classified_at None 방어** — classified_at None → 미포함(크래시 없음).

run() 통합 필터는 단순 집합 차집합이라 기존 evaluate_pivot 테스트가 회귀 커버.
