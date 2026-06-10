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

`kr_pipeline/pipeline/chains.py` 의 `run_daily_chain`·`run_weekly_chain` 에서 **ohlcv 적재
직후, indicators 계산 직전** 검사:

```
active = SELECT count(*) FROM stocks WHERE delisted_at IS NULL   -- _load_active_tickers 와 동일 정의
latest = SELECT MAX(date) FROM daily_prices
rows   = SELECT count(*) FROM daily_prices WHERE date = latest
coverage = rows / active
if limit_tickers is None and coverage < 0.90:
    raise IncompleteIngestionError(latest, rows, active, coverage)
```

- **실패 효과:** `run_tracking` 컨텍스트 안에서 raise → **run=failed 자동 기록 +
  indicators 미실행 + cron 으로 예외 전파(알림).** 따라서 **불완전 indicators 날짜가 절대 안
  생김** → "최신 지표일"은 *완전 적재된 날에만* 전진.
- **임계 0.90:** 정상일 2551~2552/2552 ≈ 99.96% 통과, partial(예: 2/2552=0.08%) 실패.
  대량 거래정지 같은 날도 통과(여유), partial 보다 ~1000× 위.
- **`limit_tickers` 설정 시 skip:** 의도적 부분 테스트 실행을 막지 않음.
- **캘린더 불필요:** `MAX(date)` 만 봄. 휴장일엔 새 날짜가 안 생겨 MAX=직전 거래일(꽉 참)→통과.

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

- `IncompleteIngestionError` (①) — `kr_pipeline/pipeline/` (체인 근처).
- `TradingCalendarUnavailable`, `StaleDataError` (②) — `trading_calendar.py` / llm_runner.
모두 명확한 메시지(날짜·커버리지·기대 거래일 포함)로 raise → run_tracking failed + 로그/알림.

## 데이터 흐름

```
[cron 저녁] data_daily 체인: drift → ohlcv → ①게이트(coverage<90%?→FAIL,중단) → indicators
                                                   └ 통과 시에만 indicators 전진(완전일만)
[cron LLM]  __main__: resolve_as_of → ②가드(ELTD 계산[pykrx], as_of<ELTD?→FAIL) → run_*_daily/weekend
```

## 테스트

**① 게이트 (순수 DB, 결정론):** `tests/test_ingestion_completeness_gate.py`
1. 완전(active=N, latest 날짜 N행) → 통과(raise 없음).
2. partial(latest 날짜 소수 행, coverage<90%) → `IncompleteIngestionError`.
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
