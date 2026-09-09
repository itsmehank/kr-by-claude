> **[기록 문서]** 본 문서의 규약 문장은 작성 시점 기록이며, 현행 규칙은 `docs/superpowers/governance.md` 절 ID를 따른다 (#155, 2026-09-09).

# #132 백필 실행 명령서 — 6~7월 주말 분류 결손 6개 앵커

> **문서일 뿐 자동 실행 금지.** 이 명령서는 #132 코드 파트(merge 후)와 별도로,
> 사용자가 주말 슬롯에 수동 실행한다. 실행 주체는 반드시 아래 체크를 먼저 통과할 것.

## 0. 무엇을 채우나

주말 LLM 분류가 실행되지 않은 6개 주(금요일 기준일 06-19·06-26·07-03·07-17·07-24·07-31)를
기존 백필 도구(`kr_pipeline/llm_runner/backfill.py`)로 `classification_backfill` 에 적재한다.
라이브 `weekly_classification` 에는 쓰지 않는다(격리 설계 — `get_active_monitoring`·7일 가드 무영향).

**CLI 사실관계** (`kr_pipeline/llm_runner/__main__.py` 실측 — `--date` 아님에 주의):

- backfill 모드는 `--start`/`--end` 가 **필수**이고 `--date` 는 앵커 지정에 쓰이지 않는다
  (`--date` 는 as_of resolve 용 공용 인자일 뿐, backfill 의 주 열거와 무관).
- `backfill.run()` 은 `--start`~`--end` 범위의 **토요일**(weekday=5)만 열거한다
  (`_enumerate_saturdays`). 각 토요일 as_of 에 대해 `get_qualifying_tickers` 가
  `MAX(daily_indicators.date) <= as_of` — 즉 **직전 거래일(금요일) 지표**로 후보를 뽑는다.
- 적재 행의 `analyzed_for_date` = **토요일 as_of** (금요일 아님). /review 의 라이브
  우선 dedup 은 **주 단위**다(같은 ISO 주에 라이브 행이 있으면 백필 억제 —
  PR #138 리뷰로 격상, `review_builder.MERGED_ROWS_CTES` 단일 정의). 라이브가
  없는 주의 앵커만 날짜순으로 결손 구간 사이에 삽입된다.
- 멱등: PK `(symbol, analyzed_for_date)` + 실행 시 기적재 종목 자동 제외
  (`_already_backfilled`) — 같은 명령 재실행 = 이어하기.
- 병렬: `--concurrency N` (기본 `BACKFILL_CONCURRENCY` env 또는 4).
- `--limit N` 은 **토요일(앵커)별** 후보 상한(`candidates[:limit]`)이지 전체 총량이 아니다.
- `--tickers A,B` 는 backfill 전용 종목 한정. `--force` 는 파서가 받긴 하나
  backfill 모드에선 **무시**된다(`backfill.run()` 미소비) — 쓰지 말 것.
- freeze 미저장, 트리거 이력 미생성(이슈 §5 — 범위 밖). **따라서 백필 행은 /review
  에서 상태가 항상 "미발동"** — 발동률 통계는 유형 필터로 실전만 분리해 읽을 것.

**앵커 변환표** (금요일 기준일 → 실행할 토요일 as_of):

| 이슈 앵커(금) | 실행 토요일 as_of | 후보 지표일 | 예상 표본* |
|---|---|---|---|
| 2026-06-19 | 2026-06-20 | 06-19 | 43 (기적재 1 스킵 → 실제 42)‡ |
| 2026-06-26 | 2026-06-27 | 06-26 | 23 |
| 2026-07-03 | 2026-07-04 | 07-03 | 22 |
| 2026-07-17 | 2026-07-18 | 07-16† | 21 |
| 2026-07-24 | 2026-07-25 | 07-24 | 11 |
| 2026-07-31 | 2026-08-01 | 07-31 | 19 |

*2026-08-27 production 실측(§3 쿼리). 이슈 본문 추정(90/78/44)보다 작다 — 현재
`daily_indicators` 기준 minervini_pass ∧ rs_line_not_declining_7m ∧ 미정지 ∧ 미상폐
조건의 실측값이며, **실행 직전 §3 쿼리로 재확인**할 것. 합계 139(기적재 1 스킵 →
실제 약 138콜)+실패 재시도 여유.
†07-17(금) 지표 행이 없어 07-16 로 폴백된다(`MAX(date) <= as_of`) — 도구가 자동 처리.

**제외**: 07-11(토)은 라이브 weekend 실행(analyzed_for_date=07-10)이 존재 — 백필하지
않는다. 이 제외는 이제 산문 규칙이 아니라 **코드 가드**다: /review 의 주 단위
라이브 우선 dedup(`review_builder.MERGED_ROWS_CTES`)이 같은 ISO 주에 라이브가 있는
백필 행을 표시에서 억제하므로, 실수로 07-11 을 백필하거나 한 방
`--start 06-20 --end 08-01` 로 돌려도 이중 행은 생기지 않는다(표시 안전).
그래도 아래는 **토요일별 6개 명령**을 유지한다 — 억제될 주(07-11)에 LLM 호출
~수십 건을 낭비하지 않고, 앵커별 표본 재확인 흐름을 지키기 위해서다.

‡06-20 앵커는 2026-08-27 21:39/21:41 에 `--tickers 000660` 단일 종목 시운전이 이미
실행돼(pipeline_runs llm_backfill success 2건) `000660/2026-06-20/watch` 1행이 적재돼
있다 — 멱등 스킵되므로 본 실행은 무해하나, 이 행을 현행대로 둘지/지우고 재생성할지는
실행 전 사용자 판단(§1 ⑤).

## 1. 실행 전 체크 (전부 통과해야 시작)

```bash
# ① 주말 슬롯인지 — LLM 사용량 한도 공유 잡들과의 충돌 회피.
#    토요일 주말 분류(weekend launchd, 토 06:00)와 겹치지 않는 시간대(예: 토 오후~일)를 쓸 것.
date

# ② 표본 C 루프·다른 LLM 러너 동시 실행 금지(한도 공유). 아무것도 안 잡혀야 한다.
pgrep -fl "llm_runner" ; pgrep -fl "backfill" ; pgrep -fl "claude -p"

# ③ 사용량 한도 여유 확인 — 직전 실행 로그에 UsageLimitError 흔적이 없는지.
#    한도 소진 상태로 시작하면 첫 콜에서 abort 된다(§4 재개 절차로 이어하면 됨).

# ④ 작업 디렉토리 = 리포 main(코드 파트 머지 반영본), .env 의 DATABASE_URL = production.
cd /Users/hank.es/git/personal/kr-by-claude && git pull --ff-only && git log --oneline -1

# ⑤ 하한(2026-05-18) 이상 기존 백필 행 확인 — 기대 5행:
#    000660 05-23 ignore / 298040 05-23 watch / 000660 05-30 ignore /
#    298040 05-30 watch / 000660 06-20 watch(08-27 시운전, 위 ‡).
#    05-23·05-30 4행은 계획 앵커 밖 날짜에서 LEAD 경계로 작동한다(라이브 구간을 끊음)
#    — 지울지 둘지 사용자 판단 후 진행(지운다면 아래 DELETE 를 날짜·심볼 명시로).
psql "$DATABASE_URL" -c "
  SELECT symbol, analyzed_for_date, classification
    FROM classification_backfill
   WHERE analyzed_for_date >= '2026-05-18' ORDER BY analyzed_for_date, symbol;"
```

원하면 최소 비용 리허설(LLM 미호출 dry-run — 후보 수 로그만 확인):

```bash
uv run python -m kr_pipeline.llm_runner --mode=backfill \
  --start 2026-06-20 --end 2026-06-20 --dry-run
```

## 2. 본 실행 — 토요일별 순차 6개 명령

한 앵커가 끝나고 로그의 `DONE backfill: {...}` 요약(processed/failures)을 확인한 뒤
다음 앵커로 넘어간다(순차 — 사용량 한도 관리와 중단 지점 파악이 쉬움).

```bash
uv run python -m kr_pipeline.llm_runner --mode=backfill --start 2026-06-20 --end 2026-06-20
uv run python -m kr_pipeline.llm_runner --mode=backfill --start 2026-06-27 --end 2026-06-27
uv run python -m kr_pipeline.llm_runner --mode=backfill --start 2026-07-04 --end 2026-07-04
uv run python -m kr_pipeline.llm_runner --mode=backfill --start 2026-07-18 --end 2026-07-18
uv run python -m kr_pipeline.llm_runner --mode=backfill --start 2026-07-25 --end 2026-07-25
uv run python -m kr_pipeline.llm_runner --mode=backfill --start 2026-08-01 --end 2026-08-01
```

선택 인자: `--concurrency 4`(기본값), `--limit N`(부분 실행 리허설),
`--tickers 005930,000660`(특정 종목 한정 재시도).

## 3. 실행 후 검증

```bash
# ① 앵커별 적재 행 수 — 예상 표본(±실패분)과 대조
psql "$DATABASE_URL" -c "
  SELECT analyzed_for_date, COUNT(*),
         COUNT(*) FILTER (WHERE classification IN ('entry','watch')) AS entry_watch
    FROM classification_backfill
   WHERE analyzed_for_date IN ('2026-06-20','2026-06-27','2026-07-04',
                               '2026-07-18','2026-07-25','2026-08-01')
   GROUP BY 1 ORDER BY 1;"

# ② 실행 전 예상 표본 재확인용(앵커 지표일 f 를 바꿔가며):
#   WITH t AS (SELECT MAX(date) AS d FROM daily_indicators WHERE date <= '<토요일>')
#   SELECT COUNT(*) FROM daily_indicators i JOIN stocks s ON s.ticker=i.ticker, t
#    WHERE i.date=t.d AND i.minervini_pass AND i.rs_line_not_declining_7m
#      AND s.delisted_at IS NULL
#      AND NOT EXISTS (SELECT 1 FROM daily_prices p
#                       WHERE p.ticker=i.ticker AND p.date=i.date AND p.adj_low IS NULL);

# ③ pipeline_runs 기록 — 각 실행 completed 인지
psql "$DATABASE_URL" -c "
  SELECT started_at, status, rows_affected, params->>'start' AS anchor
    FROM pipeline_runs WHERE pipeline='llm_backfill'
   ORDER BY started_at DESC LIMIT 8;"
```

**의도된 사후 변화(놀라지 말 것)**: 백필 적재 후 인접 **라이브** 행의 성과 구간(t′)이
백필 key_date 에서 끊긴다 — 예: 06-16 라이브 watch 의 창이 07-10까지(24일)에서
06-20까지(4일)로 줄어 `max_reach_pct`·스파크라인이 **하향 변경**될 수 있다. 이는 #132
설계 의도(결손 구간을 실제 분석 밀도로 복원)이며, 되돌리려면 해당 앵커 DELETE(§4).
검증 시 06-16·07-10·08-07 라이브 행의 도달률 변화를 눈으로 확인해 둘 것.

**/review 화면 확인**: `/review?view=analysis&from=2026-06-15&to=2026-08-05` 에서
결손 구간(06-16~08-07 사이)에 `backfill` source + **백필** 배지 행이 채워졌는지,
유형 필터 `backfill(백필)` 로 백필만 분리 조회되는지, 종목 행(streak) 뷰에서 06~07월
묶음의 공백(>10일 has_gap)이 줄었는지 확인. 라이브 파이프라인 무영향 확인:
저녁 체인·주말 배치 정상 + `uv run pytest tests/` 실패 0.

## 4. 중단·재개

- **사용량 한도**: `UsageLimitError` 발생 시 전체 abort 되고 그때까지의 processed 는
  이미 커밋돼 있다(종목 단위 insert). → 한도 회복 후 **같은 명령 재실행** = 기적재 종목
  자동 스킵(`skipped_existing`)하고 남은 종목만 이어서 처리.
- **수동 중단**(Ctrl-C): 동일 — 같은 명령 재실행으로 이어하기. `run_tracking` 이
  해당 run 을 failed 로 마감하므로 pipeline_runs 잔여 running 걱정 없음.
- **개별 실패 종목**: `DONE backfill` 요약의 `failed` 목록 확인 →
  `--tickers <실패종목들>` 로 그 앵커만 재시도.
- **롤백**(필요시): 특정 앵커 삭제는
  `DELETE FROM classification_backfill WHERE analyzed_for_date='<토요일>' AND source='backfill';`
  — 라이브 테이블 무접촉이므로 안전. (2024~2026-05 기존 백테스트 유래 행은 건드리지 말 것.)
