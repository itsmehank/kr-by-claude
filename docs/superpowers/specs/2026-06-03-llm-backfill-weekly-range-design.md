# LLM backfill 주(weekly) 단위 기간 분류 — 설계

날짜: 2026-06-03
대상: `kr_pipeline/llm_runner` backfill 모드

## 배경 / 문제

현재 `--mode=backfill`은 **단일 시점**(`--date`)의 minervini 통과 전 종목을 분류해
`classification_backfill`에 적재한다. 백테스트 목적상 다음이 필요하다:

1. **특정 종목(들)만** 과거 분류 (현재 단일 종목 필터 없음 — 항상 전 종목 배치)
2. **기간 × 매주 토요일**(weekly basis) 반복 분류 (현재 날짜 범위 순회 없음 — 단일 as_of만)
3. 운영(주말 토요일 1회 분류) 원칙과 동일한 cadence

예: SK하이닉스(000660)를 2024-05-01 ~ 2026-05-30 매주 토요일 기준으로 분류.

## 목표

`backfill` 모드를 **"기간 × 주(토요일) 단위 분류기"**로 확장한다.
지정 종목(들) 또는 전 종목을, 주어진 기간의 매주 토요일 기준으로 분류한다.

## 비목표 (Non-goals)

- 주중/주말/evaluate/entry/full-daily/disqualify 등 **다른 모드의 로직·입력·스케줄 변경**.
  이 작업은 backfill 경로에 국소적이다.
- `weekend` 모드의 `on_date` 미배선 버그 수정(별도 사안 — 이번 범위 아님).
- LLM backfill의 cron/UI 등록(현재도, 변경 후에도 순수 수동 모드).

## 핵심 결정 (브레인스토밍 합의)

1. **minervini 게이트**: 지정 종목이 그 토요일에 minervini 미통과면 **그 주는 건너뜀**
   (= 운영과 100% 일치, 결과 표에 빈 주가 생기는 것이 사실 그대로의 의미).
2. **루프 위치**: 토요일 반복을 backfill 모드 **내부에 내장**(별도 래퍼 스크립트 아님).
   단일 run_tracking row로 범위 전체 추적, 멱등 로직 재사용.
3. **단일 시점 처리**: backfill은 `--start`/`--end`로 통일. 하루만 돌리려면 `--start == --end`.
   - `--date` argparse 옵션 자체는 **유지**(다른 모드가 as_of 계산에 공유). backfill만 의존을 끊는다.
4. **종목 입력**: `--tickers=000660,005930` 쉼표 리스트. **생략 시 = 그 주 minervini 통과 전 종목**(현 동작).
5. **멱등/중복 방지(요구사항)**: 기존 `_already_backfilled` + PK `(symbol, analyzed_for_date)` +
   `ON CONFLICT DO NOTHING`를 주 단위로 그대로 활용. 이미 분류된 (종목,날짜)는 LLM 호출 자체를 건너뜀.

## 영향 범위 검증 (기존 로직 무영향 근거)

- `--date`(`__main__.py:40,67-73`)는 weekend/daily-delta/evaluate/entry/full-daily/disqualify가
  공유 → argparse 옵션 **불변**. backfill 분기만 `--start/--end` 사용.
- LLM backfill은 `pipeline_specs.py` 미등록(테스트 `test_llm_runner_main.py:186`이 명시) →
  UI 버튼·cron 스케줄 중 깨지는 것 없음. pipeline_specs의 backfill 항목은 ohlcv·corporate-actions용.
- 신규 `--start/--end/--tickers`는 기존 `--ticker` 가드(`__main__.py:46-51`)와 동일하게
  **backfill 외 모드와 함께 쓰면 에러** → 다른 모드로 새어들 여지 없음.
- 갱신되는 기존 테스트: `tests/test_llm_backfill.py:137 test_backfill_mode_requires_date`
  → `requires_start_end`로. 그 외 기존 테스트 무영향.

## CLI 표면

| 인자 | 변경 | 의미 |
|---|---|---|
| `--start YYYY-MM-DD` | 신규(backfill 필수) | 범위 시작일 |
| `--end YYYY-MM-DD` | 신규(backfill 필수) | 범위 종료일 |
| `--tickers 000660,005930` | 신규(backfill 선택) | 생략 시 = 그 주 minervini 통과 전 종목 |
| `--limit N` | 의미 변경 | **주당** 후보 종목 수 상한 (범위 전체 아님) |
| `--dry-run` | 유지 | LLM 호출하되 DB insert 생략 |
| `--date` | backfill에서만 미사용 | 옵션 자체는 다른 모드용으로 유지 |

가드: `--start/--end/--tickers`를 `--mode=backfill` 외와 쓰면 `parser.error`.
backfill에 `--start` 또는 `--end` 없으면 `parser.error`.

실행 예:
```bash
# 단일 종목, 2년치 매주 토요일
uv run python -m kr_pipeline.llm_runner --mode=backfill \
  --tickers=000660 --start=2024-05-01 --end=2026-05-30

# 여러 종목
--tickers=000660,005930,035720 --start=... --end=...

# 한 주만
--tickers=000660 --start=2024-05-04 --end=2024-05-04

# 전 종목 (주의: 범위가 길면 LLM 호출 폭증 — dry-run/limit 권장)
--start=2024-05-01 --end=2024-05-31
```

## 동작 흐름

```
backfill.run(conn, *, start, end, tickers=None, dry_run=False, limit=None):
    saturdays = enumerate_saturdays(start, end)   # 범위 내 토요일, 경계 포함, 오름차순
    agg = {weeks:0, processed:0, skipped_existing:0, failures:0, failed:[]}
    for sat in saturdays:
        as_of = sat                                # 토요일 기준
                                                   #  → get_qualifying_tickers가 date<=as_of
                                                   #    최근 거래일(직전 금요일) 데이터 사용
        candidates = _select(conn, as_of, tickers)
        done = _already_backfilled(conn, as_of)
        skipped = [c for c in candidates if c.symbol in done]
        candidates = [c for c in candidates if c.symbol not in done]
        if limit: candidates = candidates[:limit]
        for c in candidates:
            try: _process_one(conn, c.symbol, c.market, dry_run=dry_run, as_of=as_of)  # 기존 로직
                 conn.commit(); agg.processed += 1
            except: conn.rollback(); agg.failures += 1; agg.failed.append((symbol, str(as_of), err))
        agg.skipped_existing += len(skipped); agg.weeks += 1
        log("backfill week=%s: %d candidates (done %d)", as_of, len(candidates), len(done))
    return agg
```

### 후보 선정 `_select(conn, as_of, tickers)`

- `tickers` 지정 → 그 종목 중 **그 주 minervini 통과분만**
  (`get_qualifying_tickers`에 ticker 필터 추가, 또는 그 위에 교집합).
- `tickers` 생략 → 그 주 minervini 통과 전 종목(= 현 `get_qualifying_tickers(as_of)`).

토요일 자체는 비거래일이므로 별도 처리 불필요 — 기존 `date <= as_of` 컷오프가
직전 금요일 종가 데이터를 자동 사용. 운영의 토요일 cron과 동일 의미.

## 멱등성 / 재실행

- 주별 `_already_backfilled`로 이미 된 (종목,날짜) 제외 → LLM 비용 0.
- 종목별 commit → 중단되어도 끝난 (종목,주)는 보존. 재실행 = resume(끝난 것 skip, 남은 것 진행).
- PK `(symbol, analyzed_for_date)` + `ON CONFLICT DO NOTHING` → 중복 적재 물리 차단.

## 출력 / 추적

- 단일 `pipeline='llm_backfill'` run row. params에 `{start, end, tickers, limit}`.
- 반환: `{weeks, processed, skipped_existing, failures, failed, start, end}`.
- Slack digest 호출 안 함(weekend 전용).

## 테스트 (TDD)

| 테스트 | 검증 |
|---|---|
| `enumerate_saturdays` | start~end 토요일만, 경계 포함, 오름차순 |
| ticker 필터 + 게이트 | 지정 종목 중 통과분만; 미통과 주는 빈 결과(건너뜀) |
| ticker 생략 = 전 종목 | 기존 `get_qualifying_tickers` 동작 유지 |
| 주별 멱등/resume | 이미 백필된 (종목,주) 재실행 시 skip, processed 0 |
| on_date 배선 | 각 토요일 `build_analysis_zip(on_date=그 주)` — lookahead 없음 |
| CLI 가드(회귀) | 신규 인자 non-backfill 모드와 쓰면 에러; backfill에 start/end 없으면 에러; 다른 모드 `--date` 불변 |
| 기존 테스트 갱신 | `test_backfill_mode_requires_date` → `requires_start_end` |

baseline: 기존 isolation fail ~25개 수를 늘리지 않는다(CLAUDE.md).

## 파일 변경 예상

- `kr_pipeline/llm_runner/backfill.py` — `run` 시그니처/루프, `enumerate_saturdays`, `_select`.
- `kr_pipeline/llm_runner/load.py` — `get_qualifying_tickers`에 ticker 필터(또는 신규 헬퍼).
- `kr_pipeline/llm_runner/__main__.py` — `--start/--end/--tickers` 인자, 가드, backfill 분기.
- `tests/test_llm_backfill.py` — 신규 테스트 + 기존 1개 갱신.
