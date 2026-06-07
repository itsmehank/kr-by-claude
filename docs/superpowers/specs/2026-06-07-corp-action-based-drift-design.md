# 공시기반 drift 감지 설계

날짜: 2026-06-07
대상: `kr_pipeline/pipeline/drift.py`(detect 후보 소스 변경), `kr_pipeline/pipeline/chains.py`(평일/토요일 단계), `kr_pipeline/pipeline/__main__.py`(`--no-sweep`), `kr_pipeline/llm_runner/pipeline_specs.py`(corporate-actions cron). 기존 `ohlcv`/`weekly`/`indicators`/`corporate_actions` 모듈 내부 로직은 **무수정**(호출/스케줄만).

## 관계: 2026-06-04 drift 스펙 개정

이 문서는 `docs/superpowers/specs/2026-06-04-pipeline-integration-drift-reload-design.md` 를 **개정**한다:

- **§2 (드리프트 감지)** 개정: detect 가 *전 종목*을 매 평일 KRX 재조회하던 것을 → 평일은 **corporate_actions 후보 종목만**, 토요일은 **전 종목 전체스윕**으로 분리.
- 해당 스펙의 **비목표 "corporate-actions 통합/스케줄 변경 안 함" 을 해제**한다(본 설계가 corporate-actions cron 을 평일 아침으로 변경).
- `is_drift`·`reload_ticker`·"detect 는 ohlcv 증분 전 실행" 원칙은 **그대로 유지**.

## 배경 / 문제

현재 `detect_drifted_tickers` 는 매 평일 **활성 전 종목(~2,552개)** 의 최근 30일 `adj_close` 를 KRX 에서 재조회해 DB 와 대조한다. 대부분 종목은 아무 변화가 없어 헛수고이고, 순차 단일스레드라 느리며(타임아웃 사고의 무대), KRX 호출량이 크다.

우리는 이미 `corporate_actions` 테이블(9,169행, 1,260종목)을 채웠다(증자·합병·분할 등). 수정주가를 바꾸는 사건은 **반드시 공시로 먼저 드러나므로**, "최근 공시가 있는 종목만" drift 를 확인하면 검사 대상을 ~수십 개로 줄일 수 있다.

## 목표

1. **평일 drift = 공시 후보로 한정**: corporate_actions 의 최근 영향 이벤트 종목만 검사(2,552 → 수십).
2. **안전망 = 토요일 전체스윕**: corporate_actions 가 *놓친* 사건(파서 빈틈, corp_code 매핑 없는 신규 종목, DART 지연)을 잡기 위해 주 1회 전 종목 검사.
3. **공시 신선도 = 평일 매일**: corporate-actions 수집을 평일 아침으로 옮겨 평일 후보 명단이 매일 갱신되게 함.

## 비목표 (Non-goals)

- `is_drift` 판정 로직·`rel_tol`·`reload_ticker` 변경 (그대로 재사용).
- `ohlcv`/`weekly`/`indicators`/`corporate_actions` 모듈 내부 로직 변경.
- 토요일 전체스윕의 병렬화(순차 유지, 필요 시 후속).
- corporate_actions 파서 커버리지 확대(주식배당 등 — 별도 후속).

## 핵심 결정 (브레인스토밍 합의)

1. **공시 = 후보 추리기, 판정은 가격 대조 그대로**(접근 1). "공시 있으면 무조건 재적재"(직접 트리거)는 채택 안 함 — `event_date` 가 **결정 공시일**이라 권리락 전 헛 재적재, [기재정정]/취소 공시 오작동 위험.
2. **평일=공시 후보 / 토요일=전체스윕** 2단 구조(속도+안전).
3. **비교창 비대칭**: 평일 30일 / 토요일 90일. 이유는 §데이터 흐름.
4. **공시 수집을 평일 아침(`0 8 * * 1-5`)으로** — 저녁 18:30 data-daily 와 시간대 분리(경합·overrun 회피), 하루 지연은 권리락 간격(수 주)이 흡수.

## 아키텍처

### 1. 후보 선정 — `drift.py` 신규 함수

```python
ADJ_AFFECTING_EVENT_TYPES = (
    "stock_split", "reverse_split", "bonus_issue", "rights_offering",
    "merger", "spinoff", "capital_reduction",
)  # 현금배당 제외(수정주가 무관). 목록은 넉넉해도 안전 — 판정은 is_drift.

def recent_corp_action_tickers(conn, *, as_of: date, lookback_days: int) -> list[str]:
    """corporate_actions 에 [as_of-lookback, as_of] 영향 이벤트가 있는 활성 종목(distinct)."""
```

- 쿼리: `corporate_actions` 를 `event_type IN ADJ_AFFECTING_EVENT_TYPES AND event_date >= as_of - lookback_days` 로 필터, `stocks`(delisted_at IS NULL) 와 INNER JOIN, `DISTINCT ticker ORDER BY ticker`. 인덱스 `idx_corp_actions_ticker_date` 활용.
- 결과가 빈 리스트면 그대로 `[]` 반환(전 종목 아님 — §빈 후보 처리).

### 2. detect 후보 인자 추가 — `drift.py` 수정

```python
def detect_drifted_tickers(
    conn, *, as_of, rel_tol=0.01, recent_days=30, wide_days=365,
    tickers: list[str] | None = None,   # 신규
    limit_tickers: int | None = None,
) -> list[str]:
```

- **`tickers is None`** → 기존대로 `_active_tickers(conn, limit_tickers)`(전 종목) = **전체스윕용**.
- **`tickers` 가 리스트(빈 리스트 포함)** → 그 목록만 순회. `limit_tickers` 가 있으면 앞에서 슬라이스.
- **⚠️ 빈 후보 처리**: `tickers=[]` 는 **"검사 0건"** 이어야 한다. `None` 만 전 종목. 호출부가 빈 리스트를 None 으로 흘리지 않도록 주의(미묘한 버그 — 명시).
- 루프 본문(recent → 겹침0 시 wide 확대 → is_drift)·종목별 `try/except` 로그+skip·`is_drift`·`_db_adj_close`·`_krx_adj_close`·`reload_ticker` **전부 그대로**.

### 3. 평일 체인 — `chains.py` `run_daily_chain`

drift 감지 호출만 교체(나머지 동일):

```python
if drift_check:
    candidates = drift.recent_corp_action_tickers(
        conn, as_of=as_of, lookback_days=CA_LOOKBACK_DAYS)   # 90
    drifted = drift.detect_drifted_tickers(
        conn, as_of=as_of, tickers=candidates, limit_tickers=limit_tickers)
```

- 순서 불변: **detect(증분 전)** → ohlcv 증분 → 감지 종목 `reload_ticker`(기존 try/except+rollback) → indicators 일봉 증분.
- `CA_LOOKBACK_DAYS = 90` 은 `drift.py` 모듈 상수(운영 튜닝값 → `thresholds.py` 무관 → threshold-change-checklist 불필요).

### 4. 토요일 전체스윕 — `chains.py` `run_weekly_chain`

```python
def run_weekly_chain(conn, *, limit_tickers=None, full_sweep=True):
    with run_tracking(...):
        as_of = date.today()
        swept, sweep_reloaded, sweep_failures = [], 0, 0
        if full_sweep:
            swept = drift.detect_drifted_tickers(
                conn, as_of=as_of, tickers=None,        # 전 종목
                recent_days=SWEEP_RECENT_DAYS,          # 90
                limit_tickers=limit_tickers)
            for t in swept:                              # 평일 체인과 동일한 격리
                try:
                    drift.reload_ticker(conn, t, as_of=as_of)
                    sweep_reloaded += 1
                except Exception as e:                   # noqa: BLE001
                    sweep_failures += 1
                    conn.rollback()
                    log.warning("weekly sweep reload failed %s: %s", t, e)
        # 이후 기존: weekly 증분 → indicators 주봉 증분
```

- `SWEEP_RECENT_DAYS = 90`(모듈 상수). **반드시 ohlcv `window_days`(현재 30)보다 커야** 함 — 증분이 덮어쓴 최근 구간은 KRX 와 일치해 split 이 안 보이고, 덮이지 않은 옛 구간(31~90일, ~40거래일)에서 드러나기 때문. *(ohlcv 증분창을 30→키우면 이 값도 같이 올려야 하는 커플링.)*
- 스윕은 corporate_actions 와 **독립**(전 종목) → 토요일 03:00 시점 CA 신선도와 무관.
- 결과 details 에 `sweep: {detected, reloaded, failures}` 집계.

### 5. 공시 수집 스케줄 변경 — `pipeline_specs.py`

- `corporate-actions`: `default_cron` `"30 4 * * 6"`(토 04:30) → **`"0 8 * * 1-5"`**(평일 08:00).
- `schedule_label` → "평일 매일"(또는 동등 표기), `long_description` 에 "data-daily 의 drift 후보를 공급" 역할 한 줄 반영.
- 증분 창 7일 유지(월요일이 주말 포함 커버, 멱등 upsert).
- 변경 후 **크론탭 재설치** 필요(운영 단계, `get_default_cron_lines` 재생성).

## 데이터 흐름 — 평일 vs 토요일 (비교창 비대칭)

**평일 (`run_daily_chain`, 18:30, 증분 *전* 실행):**
```
corporate_actions(최근 90일 영향 이벤트) → 후보 ~수십개
  → 각 후보: DB 최근30일 adj_close  vs  KRX 최근30일  (is_drift, rel_tol=1%)
  → 틀어진 종목만 reload_ticker
  → ohlcv 증분 → indicators 일봉
```
증분 전이라 DB 최근 30일은 아직 split-전 → KRX(split-후)와 차이 → 권리락 당일 잡힘. 권리락 전 미리 봐도 차이 없음 → 통과(무해). 매일 보므로 권리락 날 자연히 포착.

**토요일 (`run_weekly_chain`, 03:00, 백업 전체스윕):**
```
전 종목 2552개 → 각: DB 최근90일 vs KRX 최근90일 (is_drift) → reload
  → weekly 증분 → indicators 주봉
```
corporate_actions 가 *놓친* split 은 평일 후보에 없고, 그 사이 증분이 최근 30일을 split-후 값으로 덮어 최근 구간은 KRX 와 일치(치유)한다 → 30일 비교론 못 잡음. **31~90일 옛 구간은 안 덮여 split-전 값 잔존** → 거기서 차이가 드러남. 그래서 비교창을 증분창(30)보다 넓은 **90일**로 둔다.

**평일 30일이 충분한 이유**: detect 와 증분이 같은 체인이라, 파이프라인이 며칠 멈췄다 돌아도 detect 가 증분 *전*에 실행돼 최근 30일이 split-전 그대로 → 잡힘. 치유-누락은 "체인은 돌았는데 후보에서 빠진" 경우뿐 → 토요일 스윕이 담당.

## 파라미터 / 상수 (모두 `drift.py` 모듈 상수, 책 유래 임계 아님)

| 상수 | 값 | 의미 |
|---|---|---|
| `CA_LOOKBACK_DAYS` | 90 | 평일 후보 공시 조회 창 |
| 평일 `recent_days` | 30 | 평일 비교창(기존) |
| `SWEEP_RECENT_DAYS` | 90 | 토요일 스윕 비교창 (> ohlcv window_days=30 필수) |
| `wide_days` | 365 | 겹침0 시 확대(기존) |
| `rel_tol` | 0.01 | 드리프트 판정 임계(기존) |

→ `thresholds.py` 무관 → **threshold-change-checklist 불필요**.

## 에러 처리 & 비용

- **종목 단위 격리**(기존 패턴 그대로): detect 는 종목별 `try/except` 로그+skip, reload 는 `try/except`+`conn.rollback()`. 토요일 스윕 reload 루프도 **평일 체인과 동일하게** 격리.
- **비용**: 평일 2,552 → ~수십(90일 기준 데이터상 후보 ~263 상한, 실제 검사는 그중 영향 이벤트 보유분). 토요일 스윕이 hotspot(2,552 × 90일 순차 페치). 주 1회·03:00 off-hours 라 감내. 느리면 후속 병렬화(범위 밖).
- **공시·data-daily 시간대 분리**(08:00 vs 18:30) → DB 경합·overrun 없음.

## 운영 / 배포 고려

- **첫 토요일 스윕**은 그동안 안 고쳐진 진짜 drift 를 한꺼번에 치유해 평소보다 재적재가 많을 수 있음(버그 아님). 배포 전 1회 수동 full-refresh 로 미리 줄이거나, 첫 스윕이 처리하게 둬도 됨.
- corporate-actions cron 변경 후 **크론탭 재설치**.

## 알려진 한계 (의도/무해)

- **소규모 유상증자**: 보정폭이 `rel_tol`(1%) 미만이면 is_drift 미발화 → 재적재 안 함. 지표 영향 미미한 materiality floor(기존 동작과 동일).
- **초신생 종목**: 상장 30일 미만이라 모든 DB 행이 증분창 안(치유됨)이고 공시까지 누락된 경우, 토요일 스윕도 옛 구간이 없어 못 봄(극단 코너). 통상 신규 종목 split 은 평일 후보로 잡힘.
- **공시 테이블 비거나 stale**: 평일 후보 0 → 평일 drift 무동작 → 토요일 스윕이 책임(graceful degradation).
- **신규 종목 corp_code 매핑 없음**: corporate_actions 에 안 잡힘(매핑 갱신 수동) → 평일 후보 누락 → 토요일 스윕 backstop.

## 테스트

- `recent_corp_action_tickers`: 영향 이벤트만 포함 / 비영향(없음 확인) / 창 경계(lookback) / 비활성(delisted) 제외 / distinct.
- `detect_drifted_tickers(tickers=[...])`: 주어진 후보만 검사. `tickers=None` → 전 종목(기존 동작 회귀 없음). `tickers=[]` → 검사 0건(전 종목으로 새지 않음).
- `run_daily_chain`: detect 가 **CA 후보 리스트로** 호출되는지(mock `recent_corp_action_tickers`·`detect_drifted_tickers`), 순서(detect → ohlcv → reload → indicators) 유지, `drift_check=False` 시 미호출.
- `run_weekly_chain`: 전체스윕 detect(`tickers=None`, `recent_days=90`)+reload 가 weekly 단계 *전*에 호출되는지(mock), `full_sweep=False` 시 미호출, reload 실패 격리.
- `pipeline_specs`: corporate-actions `default_cron` = `"0 8 * * 1-5"`, `schedule_label` 갱신, `get_default_cron_lines` 정상 생성, depends_on 무결성.
- baseline 회귀 0(base↔HEAD 실패 수 비교).

## 파일 변경 예상

- 변경: `kr_pipeline/pipeline/drift.py`(상수 + `recent_corp_action_tickers` 추가, `detect_drifted_tickers` 에 `tickers` 인자), `kr_pipeline/pipeline/chains.py`(평일 후보 교체, 토요일 스윕 추가), `kr_pipeline/pipeline/__main__.py`(`--no-sweep`), `kr_pipeline/llm_runner/pipeline_specs.py`(corporate-actions cron/label/desc).
- 테스트: `tests/test_pipeline_drift.py`(갱신), `tests/test_pipeline_chains.py`(갱신), `tests/test_pipeline_specs.py`(갱신).
