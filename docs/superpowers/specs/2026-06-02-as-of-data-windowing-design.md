# as-of 시계열 정합화 — 차트·CSV 빌더 `on_date` 결선

설계일: 2026-06-02
범위: sub-project ② (3분해 중 두 번째). ①(최신판정 축, 완료) · ③(백필/백테스트 별도 테이블, 대기)은 별도 스펙.

## 배경 / 문제

`build_analysis_zip(conn, ticker, on_date=None)` 은 `on_date`(분석 기준 데이터 날짜)를 받아 일부 입력(payload/minervini/market_context/corporate_actions)에는 넘기지만, **정작 LLM이 보는 가격 시계열 — 차트 2개 + CSV 3개 — 에는 안 넘긴다.** 그래서 과거 시점(`on_date=과거`)으로 호출해도 차트·CSV는 항상 **현재 최신 데이터**를 담는다.

결과: 백테스트/백필(③)이 의미를 가지려면 차트·CSV가 `on_date` 시점까지로 잘려야 하는데, 현재는 "과거 메타 + 현재 차트"가 섞인 부정합 ZIP이 생성된다. ②는 이 누락을 메운다.

## 대상 함수 (현재 모두 동일 패턴: 최신 N개)

| 함수 | 파일 | 현재 쿼리 패턴 |
|------|------|----------------|
| `build_daily_csv(conn, ticker, days=60)` | `api/services/csv_builder.py` | `WHERE p.ticker=%s ORDER BY p.date DESC LIMIT %s` |
| `build_weekly_csv(conn, ticker, weeks=104)` | `api/services/csv_builder.py` | `WHERE ticker=%s ORDER BY week_end_date DESC LIMIT %s` |
| `build_index_csv(conn, index_code, timeframe, lookback=60)` | `api/services/csv_builder.py` | `WHERE index_code=%s ORDER BY date DESC LIMIT %s` (weekly는 week_end_date) |
| `render_daily_chart(conn, ticker, range_days=365)` | `api/services/chart_render.py` | `WHERE p.ticker=%s ORDER BY p.date DESC LIMIT %s` |
| `render_weekly_chart(conn, ticker, range_weeks=104)` | `api/services/chart_render.py` | `WHERE p.ticker=%s ORDER BY p.week_end_date DESC LIMIT %s` |

## 핵심 규칙 (윈도잉 의미 — A안)

각 함수에 `on_date: date | None = None` 파라미터 추가:

- `on_date` 제공 시: 날짜 컬럼에 `AND <date_col> <= %(on_date)s` 추가 → "on_date(또는 직전 거래일)로 끝나는 최근 N개". 이력이 N개 미만이면 LIMIT가 자연 처리 → **있는 만큼 반환(에러·패딩 없음)**.
- `on_date=None` 시: 필터 미적용 → **기존 동작과 100% 동일**(최신 N개). 라이브 경로 무변경 보장.

날짜 컬럼: 일봉/인덱스일봉 = `date`, 주봉/인덱스주봉 = `week_end_date`.

## build_analysis_zip 결선

`build_analysis_zip` 은 이미 `on_date`(기본 `date.today()`)를 갖고 payload/minervini/market_context/corporate_actions 에 넘긴다. ②는 **같은 `on_date` 를 5개 빌더 호출에도 전달**한다:
```python
daily_csv = build_daily_csv(conn, ticker, on_date=on_date)
weekly_csv = build_weekly_csv(conn, ticker, on_date=on_date)
market_index_daily_csv = build_index_csv(conn, index_code, "daily", on_date=on_date)
market_index_weekly_csv = build_index_csv(conn, index_code, "weekly", on_date=on_date)
daily_chart_png = render_daily_chart(conn, ticker, on_date=on_date)
weekly_chart_png = render_weekly_chart(conn, ticker, on_date=on_date)
```
(N 파라미터 days/weeks/range_days/range_weeks/lookback 기본값은 유지.)

라이브 효과: 라이브 러너는 `build_analysis_zip` 을 `on_date` 없이 호출 → `on_date=date.today()` → `date <= today` → 미래 데이터가 없으므로 = 최신 N개. **동작 불변.**

## 비범위 (Out of scope)

- 라이브 러너(weekend/daily_delta `_process_one`)가 `build_analysis_zip` 에 `on_date=as_of` 를 넘기도록 하는 **배선** → sub-project ③ (백필 경로). ②는 빌더가 `on_date` 를 *존중*하게만 만든다.
- 백필/백테스트 별도 테이블 → ③
- `on_date` 가 비거래일일 때의 특수 처리: `<=` 가 자연히 직전 거래일로 귀결 → 별도 처리 불필요.
- 이력 부족 시 에러/경고 (B안 기각).

## 구현 방식

5개 함수에 동일한 `AND <date_col> <= on_date` 절을 **인라인** 추가 (함수마다 테이블·컬럼이 달라 공유 헬퍼보다 인라인이 명확, 기존 인라인-SQL 스타일과 일치).

## 테스트 전략

**함수별 단위 테스트 (5개):** 각 빌더에 대해 — on_date 이전/이후 양쪽에 행을 시드하고, `on_date` 지정 호출 결과가 (a) on_date 이후 행을 **포함하지 않고** (b) on_date 이하 최신 N개를 담는지 확인. + `on_date=None` 호출이 기존과 동일(최신 포함)한지 회귀.
- 차트(PNG)는 픽셀 검증이 어려우므로, 렌더 직전 데이터 조회를 검증하는 방식(예: 반환 PNG가 비어있지 않음 + 조회 행수/경계 단언). 가능하면 내부 조회를 호출해 경계 행만 단언. 구현 시 chart_render 구조를 보고 최소 침습적 단언 채택.

**통합 테스트 (1개, ②의 핵심 보증):** 한 종목에 on_date 이후의 가격/지표/인덱스 행을 심어두고, `build_analysis_zip(conn, ticker, on_date=과거)` 로 ZIP 생성 → ZIP 안의 `daily.csv`/`weekly.csv`/`market_index_*.csv` 에 **on_date 이후 날짜가 한 줄도 없음**을 단언 (= 누수 없음).

**회귀:** `uv run pytest tests/` baseline(~26 isolation fail) 수 불변 (CLAUDE.md 기준). 특히 `tests/test_api_csv_builder.py`, `tests/test_api_chart_render.py`, `tests/test_api_zip_builder.py` 의 기존 테스트가 `on_date=None` 기본 경로에서 그대로 통과.

## 영향받는 파일 요약

- `api/services/csv_builder.py` (3개 함수)
- `api/services/chart_render.py` (2개 함수)
- `api/services/zip_builder.py` (`build_analysis_zip` 의 5개 호출에 on_date 전달)
- 테스트: `tests/test_api_csv_builder.py`, `tests/test_api_chart_render.py`, `tests/test_api_zip_builder.py`
