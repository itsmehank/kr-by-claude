# D-4 데이터 완전성·신선도 보장 — 설계

## 문제

LLM 분석은 "최신 지표일"(`MAX(daily_indicators.date)`)을 기준으로 후보 선정·as_of를
정한다(`get_qualifying_tickers`, `resolve_as_of` 등 4곳). 그런데:

1. **부분 적재가 stray 날짜를 만든다.** 테스트용 `limit N` 실행이나 적재 실패로 *일부
   종목만* 있는 날짜가 생기면, 그게 `MAX(date)`로 잡혀 후보가 거의 0이 된다 → 파이프라인이
   **조용히 "할 일 없음"으로 1초 만에 성공** (에러 없음 = 가장 위험).
2. **소비 단계 방어는 투명성을 해친다.** "최신이 적으면 전날로 fallback" 식은 사용자가
   결과가 *언제 데이터*인지 모른 채 받게 한다.

→ **근본 해법: 적재에서 fail-fast(완전성 게이트) + LLM이 항상 최신만 보되 stale이면 명시
실패(신선도 가드).** 소비 단계 휴리스틱 없음.

## 구성

두 독립 메커니즘. ①은 네트워크 불필요(순수 DB), pykrx 의존은 ②에만 격리.

### ① 완전성 게이트 (적재 체인)

**위치: `kr_pipeline/indicators/modes.py` `run_daily` 의 시작부**(Phase A 전, 입력 ohlcv
완전성 검사). 체인(`chains.py`)이 아니라 **indicators 계산 함수 안**에 두는 이유: `run_daily`
는 `kr_pipeline/indicators/__main__.py` 로 **단독 실행도 가능**하다. 게이트를 체인에만 두면
단독 실행이 우회해 partial 지표일을 또 만든다. 계산 함수 안에 두면 **체인·단독 모든 경로가
보호**되고 "불완전 입력이면 후속 계산 금지"라는 의도에 정확히 맞는다. (`run_weekly` 는 범위 밖
— 아래 참조.)

```
# run_daily 시작부, mode=INCREMENTAL 이고 limit_tickers 없을 때만
active = SELECT count(*) FROM stocks WHERE delisted_at IS NULL   -- load_active_tickers_with_market 와 동일 정의
latest = SELECT MAX(date) FROM daily_prices
rows   = SELECT count(*) FROM daily_prices WHERE date = latest
coverage = rows / active
if limit_tickers is None and coverage < 0.90:
    raise IncompleteIngestionError(latest, rows, active, coverage)   # Phase A 진입 전
```

- **실패 효과:** `run_daily` 의 `run_tracking`(pipeline="indicators") 안에서 raise →
  **indicators run=failed + 지표 미계산 + 예외 전파.** 체인에서 호출된 경우 `r_ind =
  indicators.run_daily(...)` 에서 raise 가 다시 전파 → **data_daily 체인도 failed**(이중 알림).
  따라서 **불완전 indicators 날짜가 절대 안 생김** → "최신 지표일"은 *완전 적재된 날에만* 전진.
- **임계 0.90:** 정상일 2551~2552/2552 ≈ 99.96% 통과, partial(예: 2/2552=0.08%) 실패.
  대량 거래정지 같은 날도 통과(여유), partial 보다 ~1000× 위.
- **`limit_tickers` 설정 시 skip:** 의도적 부분 테스트 실행을 막지 않음. (FULL_REFRESH/BACKFILL
  모드는 end=어제라 무영향 — 게이트는 INCREMENTAL 에만 적용.)
- **캘린더 불필요:** `MAX(date)` 만 봄. 휴장일엔 새 날짜가 안 생겨 MAX=직전 거래일(꽉 참)→통과.

> **① 과 ② 의 분담 (오해 방지):** ① 은 **"최신 *존재* 날짜가 partial"**(오늘 일부만 적재)을
> 차단한다. **"오늘 통째 누락"**(ohlcv 완전 실패 → 새 행 0 → MAX 가 어제로 남음, 어제는 꽉 참)
> 은 ① 을 *통과*한다 — 이 경우는 **②(신선도 가드)가 잡는다**(as_of=어제 < ELTD=오늘 →
> `StaleDataError`). 즉 ① 단독으로 전체 실패를 잡지 못하며, ①(partial 차단)+②(stale/누락 차단)
> 가 합쳐 커버한다.

> **weekly 는 범위 밖:** `run_weekly_chain` 은 `weekly_prices`(week_end_date 컬럼, 다른 주기)
> 를 쓰고, LLM 트랩(resolve_as_of·get_qualifying_tickers)은 `daily_indicators` 만 본다. weekly
> stray 는 그 트랩을 일으키지 않으며, `weekly/modes.py` 에 이미 커버리지 카운트 쿼리가 있다.
> weekly 완전성 강화가 필요하면 별도 follow-up(테이블/주기 상이로 함께 묶으면 복잡).

### ② 신선도 가드 (LLM)

#### ②-a 거래 캘린더 모듈 — `kr_pipeline/common/trading_calendar.py`

```python
CLOSE_BUFFER = time(17, 0)   # KRX 마감 15:30 후 pykrx EOD 안정화 시점(KST)

def expected_latest_trading_day(now: datetime) -> date:
    """기대 최신 거래일(ELTD). 라이브 KRX 지수로 실제 거래일 판별 + 마감버퍼."""
    # fetch.fetch_index("1001", now.date()-14, now.date()) 로 실제 거래일 목록 취득
    # (지수 OHLCV 는 실제 거래일에만 행. 이미 prod 에서 동작하는 경로 재사용.)
    # 빈 결과/예외 → raise TradingCalendarUnavailable  (fail-closed)
    trading_days = sorted(set(fetched dates))
    today = now.date()
    if today in trading_days and now.time() >= CLOSE_BUFFER:
        return today
    return max(d for d in trading_days if d < today)   # 오늘 직전 거래일
```

- **장중/오전 실행(now < 17:00)** → ELTD = 직전 거래일. 오전 분석이 어제 데이터인 게
  *정상*으로 판정됨(거짓 stale 방지). pykrx 가 장중에도 오늘 provisional bar 를 주므로 버퍼 필수.
- **마감 후/저녁** → ELTD = 오늘. **휴장일** → 오늘 미포함 → ELTD = 직전 거래일.
- **fail-closed:** 라이브 조회 실패(타임아웃/KRX 장애) → `TradingCalendarUnavailable` raise.

#### ②-b 가드 — `kr_pipeline/llm_runner/__main__.py`

`as_of = resolve_as_of(conn, explicit)` 직후, `run_weekend`/`run_full_daily` 호출 전:

```python
if explicit is None:                       # 명시 --date 백필은 가드 skip(의도적 과거 실행)
    eltd = expected_latest_trading_day(datetime.now(KST))   # 실패 시 raise → LLM 중단(fail-closed)
    if as_of < eltd:
        raise StaleDataError(f"최신 거래일 {eltd} 데이터 미적재 (현재 최신 {as_of}) — 분석 중단")
```

- `as_of`(= `MAX(indicator date)`, ① 덕분에 항상 완전)가 ELTD 보다 뒤처지면 **명시 실패**
  → 사용자는 "최신 완전 데이터로만 분석된다"를 보장받음(조용한 전날 실행 없음).
- `as_of == eltd` → 진행. `as_of > eltd`(드묾, 버퍼 전 provisional 적재 등) → 통과(too-fresh 무해).
- weekend·weekday LLM 양쪽 공통 적용(둘 다 이 진입점 경유). `--dry-run` 도 적용(미리보기도 신선해야).

## 에러 타입

- `IncompleteIngestionError` (①) — `kr_pipeline/indicators/` (indicators 모듈 근처).
- `TradingCalendarUnavailable`, `StaleDataError` (②) — `trading_calendar.py` / llm_runner.
모두 명확한 메시지(날짜·커버리지·기대 거래일 포함)로 raise → run_tracking failed + 로그/알림.

## 데이터 흐름

```
[cron 저녁] data_daily 체인: drift → ohlcv → indicators.run_daily
                                              └ ①게이트(시작부): coverage<90%?→FAIL(indicators+체인 둘 다 failed)
                                                통과 시에만 지표 계산 → 최신 지표일은 완전일만 전진
            (indicators 단독 실행도 같은 게이트로 보호 — chains 우회 불가)
[cron LLM]  __main__: resolve_as_of → ②가드(ELTD 계산[pykrx], as_of<ELTD?→FAIL) → run_*_daily/weekend
```

## 테스트

**① 게이트 (순수 DB, 결정론):** `tests/test_indicators_completeness_gate.py` — `indicators.run_daily`
직접 호출(또는 게이트 헬퍼 단위). daily_prices/stocks 시드로:
1. 완전(active=N, latest 날짜 N행) → 통과(raise 없음, Phase A 진입).
2. partial(latest 날짜 소수 행, coverage<90%) → `IncompleteIngestionError` (지표 미계산).
3. `limit_tickers` 설정 → coverage 낮아도 skip(통과).
4. 경계: coverage 정확히 90% → 통과(>=0.90).

**②-a 캘린더 (pykrx mock):** `tests/test_trading_calendar.py`
1. 오늘=거래일 & now≥17:00 → ELTD=오늘.
2. 오늘=거래일 & now<17:00 → ELTD=직전 거래일.
3. 오늘=휴장일 → ELTD=직전 거래일.
4. fetch 빈 결과/예외 → `TradingCalendarUnavailable`.
(fetch_index 를 monkeypatch 로 거래일 목록 주입 — 네트워크 없이.)

**②-b 가드 (캘린더 mock):** `tests/test_freshness_guard.py`
1. as_of < ELTD → `StaleDataError`.
2. as_of == ELTD → 통과.
3. explicit date 지정 → 가드 skip.
4. 캘린더 raise(pykrx 실패) → 가드도 raise(fail-closed).

## 범위 밖

- 소비 단계 fallback 휴리스틱(폐기 — 완전성은 상류 보장).
- stray 날짜 사후 정리(cleanup): ①이 애초에 생성을 막으므로 불필요. 기존 stray 데이터가
  이미 있으면 별도 수동 정리(운영 1회).
- D-3(LLM 숫자 sanity)는 별도 작업.
