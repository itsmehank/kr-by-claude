# KRX 접촉 패턴 구조 수리 Implementation Plan

> **소유 이슈: [#92](https://github.com/itsmehank/kr-by-claude/issues/92)** — #88(launchd 이전, 완료)에서 분리, #91(Open API 전환 검토)과 병행.
> 계획 검토 2회 완료(정정 27건) + 결정 4건 확정(2026-08-03).

## 구현 완료 (2026-08-03~04, 브랜치 `issue-92-krx-contact-hardening`)

Task 1~4 전부 구현. 순서는 승인된 조정안대로 **Task 1 의 conftest 자격증명 공백화를 최우선**
적용해 "작업 중 KRX 접촉 0" 제약 구간을 5분으로 줄였다.

**실증된 성과**: 감시 스크립트(`watch_pipelines.sh`)를 실제 1회 실행해 **KRX 접촉 0건** 확인
(이전엔 실행당 약 6요청 = 로그인 3 + 지수 1 + 마스터 일부). 체인이 쓴 캐시를 감시가 읽는
경로도 프로덕션 코드로 완결 검증(`2026-08-04:pre|2026-07-31` → bash `2026-07-31 0`).

**구현 후 검토 2회에서 발견·수정한 5건** (계획서에 없던 실제 결함):

| # | 문제 | 수정 |
|---|---|---|
| 1 | **계획서가 커밋되지 않았다** — `README.md:60` 이 참조하는데 미추적(`docs/superpowers/plans/` 에 81개가 추적되는 관례 위반) | 이 커밋에 포함 |
| 2 | **HOME 미설정 시 bash 와 Python 의 캐시 경로가 갈렸다** — bash `${HOME:-/tmp}` vs Python `expanduser`(passwd 폴백). 갈리면 영구 캐시 미스로 결측 감시가 조용히 죽는다 | bash 를 `cd ~ && pwd -P` 폴백으로 통일(Python 과 동일 동작 실측) |
| 3 | `test_lib_guards_survives_unset_home` 이 `source` 생존만 단정해 #2 를 통과시켰다(거짓 안심) | `test_bash_and_python_cache_paths_agree` 신설(home-set/home-unset 2케이스). 구 방식 주입 시 실패하는 것 확인 |
| 4 | `attempt_allowed` 가 비숫자 인자에서 **fail-open** — `[ x -ge y ]` 가 오류로 false 가 되어 상한이 조용히 무력화 | 인자 검증 후 fail-closed 차단 + 테스트 |
| 5 | `CLAUDE.md` 테스트 규율이 `krx` 마커 기본 제외·`KR_ALLOW_KRX=1` 탈출구를 안 적어 1 deselected 의 이유를 알 수 없었다 | CLAUDE.md 갱신 |

**수정하지 않고 기록만 남긴 것 2건**(실제 위험 낮음):
- `evening_chain.sh` 의 시도 상한 게이트가 `acquire_lock data 3600` **뒤**에 있어, 차단될
  발화도 최대 1시간 락 대기 후 `exit 1` 한다. 다른 체인이 1시간 넘게 data 락을 보유할 때만
  발생하므로 드물다. 옮기려면 `NIND` 조회도 락 앞으로 함께 가야 한다.
- `weekly/modes.py:157` 은 naive `datetime.now()`, 체인·`llm_runner` 는 `Asia/Seoul` aware 를
  쓴다. 시스템 TZ 가 KST 라 캐시 키가 일치함을 실측했으나(`2026-08-03:post` 동일), TZ 가
  바뀌면 갈린다.

**검토 중 실제로 막은 사고 1건**: 검증 명령으로 `KR_ALLOW_KRX=1 uv run pytest -m krx
--collect-only` 를 실행하려 했는데, `--collect-only` 라도 `test_integration.py` 를 import 해
살아있는 자격증명으로 **KRX 로그인 POST 가 나간다**. 사용자가 거부해 차단 대기 중 접촉을 막았다.
→ 검증·조사 목적이라도 `KR_ALLOW_KRX=1` 은 붙이지 말 것.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** KRX 차단 재발을 막기 위해 자동화의 KRX 접촉을 구조적으로 제한한다 — 감시의 시간당 조회를 **0회**로, 전 종목 스윕을 하루 상한으로, pytest 의 import-time 로그인을 차단한다.

**Architecture:** 접촉원은 3개다. ①`watch_pipelines.sh` 가 매시간 부르는 ELTD 라이브 조회(실측 15회/일) ②`RunAtLoad`/catch-up 이 하루 여러 번 발화시키는 전 종목 스윕(2,549종목 × 2호출) ③`pytest` 의 pykrx import-time 로그인. 해법은 **역할 분리**다 — ELTD 는 하루 1회 도는 체인만 라이브 조회하고 파일 캐시에 쓰며, 시간당 도는 감시는 **캐시만 읽는다**(미갱신 자체가 결측 신호). 스윕은 `pipeline_runs` 이력 기반 시도 상한으로 묶는다. plist 는 수정하지 않으므로 `install.sh` 재실행이 불필요하고 재개는 `launchctl bootstrap` 4회로 끝난다.

**Tech Stack:** Python 3.14 (`kr_pipeline/common/trading_calendar.py`), bash (launchd 래퍼), pytest, PostgreSQL (`pipeline_runs`), pykrx (차단 대상 — 이 계획 실행 중 호출 금지)

## 1회차 검토에서 바뀐 것 (초안 대비)

| # | 초안 | 판정 | 개정 |
|---|---|---|---|
| 1 | `os.environ.pop("KRX_ID")` | ❌ **되살아난다** | `kr_pipeline/common/config.py:5` 가 import 시 `load_dotenv()` 를 재실행한다. dotenv 는 `if k in os.environ and not override: continue`(`dotenv/main.py:105`)이므로 **pop 하면 복원**된다. → **빈 문자열 대입**(키는 남기고 값만 비움). `build_krx_session` 은 `if not (login_id and login_pw)` 라 `""` 도 falsy |
| 2 | `addopts = "-m 'not integration'"` | ❌ **과도** | integration 마커 파일 5개·테스트 14개 중 KRX 접촉은 `test_integration.py` 1개뿐. 나머지 13개는 Postgres 전용. → **`krx` 마커 신설**, `-m "not krx"` |
| 3 | 캐시를 셸 `eltd()` 에 구현 | ❌ **커버리지 부족 + 무효** | Python 호출부 2곳(`llm_runner/__main__.py:96`, `weekly/modes.py:157`)을 못 막는다. 게다가 셸 `eltd()` 는 매번 새 프로세스라 in-memory 캐시가 무의미 → **파일 캐시를 `trading_calendar.py` 에 구현** |
| 4 | 실패를 6시간 negative 캐시 | ❌ **체인을 마비시킨다** | `llm_runner` 는 fail-closed. 14:00 일시 오류가 FAIL 캐시되면 18:30 체인이 그날 통째 skip → **negative 캐시 폐기.** 체인=항상 라이브, 감시=캐시 read-only |
| 5 | 감시가 캐시 미스 시 판정 보류 | ❌ **결측 감시를 죽인다** | Mac 수면 시 체인 미실행 → 캐시 미갱신 → 알림 없음(= #88 이 잡으려던 시나리오). → **캐시 미갱신 자체를 `eltd_stale` 알림으로.** DB 기반 대체 임계는 부적합(2026년 거래일 간격 실측 1일 108·3일 25·4일 4·6일 1 → 3일 임계는 5회 오탐, 6일은 탐지 6일 지연) |
| 6 | Task 1 red 단계에 `pytest <파일>` | ❌ **자기 제약 위반** | 그 실행이 KRX 로그인을 낸다. → `-k` 로 pykrx 를 import 하지 않는 테스트 2개만 red 확인 |
| 7 | `data_attempt_allowed` 가 data_daily 전용 | ⚠️ 누락 | `monthly_chain.sh:17` 의 `universe` 도 KRX 를 부르고 **실패 시 백오프가 없다**(08-01 06:36 실제 실패). → 파이프라인 인자를 받게 일반화 |
| 8 | `db_query` 만 `KR_DB` 변수화 | ⚠️ 누락 | `watch_pipelines.sh:33` 의 별도 `q()` 가 `psql -d kr_pipeline` 을 따로 하드코딩 → 같이 변수화 |
| 9 | DB 실패를 상한 도달과 동일 취급 | ⚠️ 위험 | `return 1` → 호출부 `exit 0` 이라 DB 장애가 은폐된다. 기존 `has_success_since`(`lib_guards.sh:78`)는 `exit 1` fail-closed → **관례 일치시킴** |

### 1회차 독립 검토 2건에서 추가로 바뀐 것

| # | 지적 | 판정 | 개정 |
|---|---|---|---|
| 10 | `eltd_cached()` 가 Python 을 타면 **매시간 KRX 로그인** | ❌ 치명 | `trading_calendar.py:10` → `ohlcv/fetch.py:9` → pykrx → `webio.py:12`. 실측: `KRX_ID= uv run python -c "import kr_pipeline.common.trading_calendar"` 가 `build_krx_session` 실행 확인 → **순수 bash 로 캐시 읽기** |
| 11 | `set -u` 하 `$HOME` 무방비 참조 | ❌ 치명 | plist 에 `HOME` 이 없으면 `source` 자체가 무음 사망 → `${HOME:-/tmp}` |
| 12 | `probe_krx.sh` 가 KRX 계정 ID 를 로그에 평문 기록 | ❌ 치명(보안) | pykrx `auth.py:189` 가 `print(f"  로그인 ID: {login_id}")` → `grep -v '로그인 ID'` 필터 |
| 13 | 시도 상한 테스트가 시각 의존 flaky | ❌ 치명 | 게이트 창은 당일 00시 기준인데 시드가 `now() - N hours` → 자정 근처 실패(상한 테스트는 00~10시). **당일 앵커 시드**로 교체 |
| 14 | ELTD 1회 = **6 요청** (계획은 1로 가정) | ⚠️ 규모 오산 | `name_display=True` 기본이라 `IndexTicker()` 가 마스터 4종 추가 fetch. **`name_display=False` 한 줄로 6→2** (Step 5c 신설) |
| 15 | `data_weekly` 게이트 누락 | ⚠️ 누락 | 성공 기준 멱등이라 실패 시 발화마다 전량 재스윕 → `attempt_allowed data_weekly 1 43200` (Step 5b 신설) |
| 16 | `KR_ALLOW_KRX=1` 세션에서 격리 테스트가 로그인 발생 | ⚠️ | `get_auth_session()` 이 호출 시점에 `os.getenv` 재확인 → 파일 전체 `skipif` |
| 17 | bash/Python 캐시 키 desync 위험 | ⚠️ | 어긋나면 영구 미스 → 키 일치 단정 테스트 추가 + `TZ=Asia/Seoul` 고정 |

**독립 검토의 주장 중 실측으로 반박한 것 2건** (계획에 반영하지 않음):

- ❌ "`--chain=weekly` 는 KRX 전용, Naver 는 이 리포에 없다" → **틀렸다.** `naver` 문자열이
  우리 리포에 없는 건 맞지만 분기는 **pykrx 안**에 있다(`stock_api.py:236-237`).
  `fetch_adj_only` → `_fetch_one(adjusted=True)` → Naver. 실측 증거: run 1219 가
  KRX 86% 차단 중에도 2,549종목 `failures:0, unverified:0`.
- ❌ "`get_stock_name` 이 `StockTicker()` 를 매번 생성 → 종목당 2요청 ≈ 5,100" → **틀렸다.**
  `comm/util.py:26-34` 의 `singleton` 이 `_instance` 에 캐시 → 프로세스당 1회.
  실측 증거: universe full 실행 8~48초(id 1105=16s, 1032=8s) — 5,100 직렬 HTTP 불가능.

**확인되어 유지되는 전제**: `data_daily` 행은 스윕 **시작 전**에 기록된다(`db/runs.py:55-56` 의 `run_tracking` 이 `start_run`+`commit` 을 yield 앞에서 수행) → 시도 상한 게이트가 진행 중 실행도 본다.

### 2회차 검토에서 바뀐 것

| # | 지적 | 판정 | 개정 |
|---|---|---|---|
| 18 | **정확일치 캐시 키가 하루 17시간의 결측 감시를 삭제한다** | ❌ 치명 | 캐시를 쓰는 주체는 저녁 체인(`D:post`)뿐이라 D+1 00:00~16:59 의 조회 키 `D+1:pre` 는 항상 미스. 그 구간이 바로 "어제 저녁 통째 수면" 탐지 구간(= #88 의 존재 이유). → **`eltd_cached_latest`(최신 1건 + 파일 나이 30h)** 로 교체, `test_cached_eltd_miss_on_different_key` 삭제 |
| 19 | **비-UTF8 손상 캐시가 자기치유되지 않는다** | ❌ 치명 | `_write_cache` 의 `read_text()` 가 `UnicodeDecodeError` → 바깥 except → **쓰기 자체가 미실행** → 감시 결측 판정 영구 사망. → 읽기를 **안쪽 try** 로 감싸고 tmp→`replace()` 원자 교체 |
| 20 | 재개 3단계 검증이 **구조적으로 항상 통과**(거짓 안심) | ❌ 높음 | `grep "KRX 로그인" 로그` 는 항상 0 — 로그인 문구가 stdout 이고 함수가 `grep`+`2>/dev/null` 로 버린다. → `declare -f` 로 함수 본문 검사 + 수동 1회 실행 관찰로 교체 |
| 21 | `watch_pipelines.sh:29` 도 DB 이름 하드코딩 | ⚠️ 누락 | 33행만 바꾸면 Step 7 의 "리터럴 0건" 기대가 실패 → 29·30행 함께 수정 |
| 22 | `eltd_stale` 이 bootout 기간에 매일 소음 | ⚠️ | "감시만 먼저 재개" 하는 재개 3단계에서 평일마다 무의미하게 울린다 → `launchctl list com.krbyclaude.evening-chain` 로드 여부로 게이트 |
| 23 | 간격 4h 로는 08-01 폭주를 못 막는다 | ⚠️ 실측 | 08-01 두 스윕 간격 **5h57m** → 4h 통과. **6h(21600)** 로 올리면 08-01·08-02 둘째 스윕이 모두 차단 |
| 24 | `weekend_chain` 에 `has_running_recent` 부재 | ⚠️ 실측 | `08-01 16:30 data_weekly running`(좌초) → `08-03 07:06` 월 catch-up 이 전량 재스윕. LLM 단계엔 있는 가드가 주봉 단계엔 없다 → 추가 |
| 25 | `monkeypatch.setattr(Path,"mkdir")` 는 같은 테스트 내 모든 mkdir 을 깨뜨린다 | ⚠️ | 교차 누수는 없지만 지뢰 → `chmod 0o500` 실제 디렉터리로 교체 |
| 26 | Task 1 Step 2 기대 문장 자기모순(4 FAIL 이라 쓰고 하나는 PASS 라 설명) | ⚠️ 경미 | 실제 red = **3 FAIL / 2 PASS** 로 정정 |
| 27 | `_isolate_eltd_cache` docstring 근거가 사실과 다름 | ⚠️ 경미 | `expected_latest_trading_day` 는 캐시를 읽지 않으므로 기존 8개 테스트 간 오염은 발생 불가. 실제 이유는 ① 신규 `test_failure_is_not_cached` 가 `test_expected_latest_writes_cache` 와 같은 키를 공유 ② 운영 캐시 오염 방지 |

**2회차의 주장 중 실측으로 반박한 것** (1회차와 동일한 오독이 반복됨):

- ❌ "주말 `--chain=weekly` 전 종목 스윕은 KRX 경로다" → **틀렸다.** 두 검토가 모두 pykrx 의
  **krx 분기만** 따라갔다. 실제 분기는 `stock_api.py:12`(`from pykrx.website import krx, naver`)와
  `:236-239`:
  ```python
  if adjusted:  df = naver.get_market_ohlcv_by_date(fromdate, todate, ticker)
  else:         df = krx.get_market_ohlcv_by_date(fromdate, todate, ticker, False)
  ```
  `fetch_adj_only` → `_fetch_one(adjusted=True)` → **naver**. 실측 증거: run 1219(08-03)가
  KRX 86% 차단 중에 2,549종목 `failures:0, unverified:0` 로 완주.
  → 그래도 `has_running_recent`·`attempt_allowed` 게이트는 유효(ELTD 는 KRX, 반복 스윕 자체가 낭비).

**2회차가 제기한 인과 가설(추정, 채택)**: 전 종목 스윕은 06-01~07-31 에 하루 1~3회(06-09 는 3회)
돌았는데 차단이 없었고, 차단은 **시간당 감시 도입 직후**에 나타났다. 즉 1차 용의자는 스윕 횟수가
아니라 **동일 계정의 반복 로그인 빈도**일 수 있다. ELTD 1회 = 로그인 3요청(`auth.py:117-118` warmup
GET×2 + `:152` POST)이므로 07-31 하루에만 로그인이 평소의 3~5배로 뛰었다.
→ **Task 2(ELTD)를 Task 3(스윕 상한)보다 우선순위 높게 취급한다.**

## Global Constraints

- **작업 기간 중 KRX 접촉 0.** `pykrx` 실행, `data.krx.co.kr` 요청, `-m krx` 테스트 금지. **Task 1 이 적용되기 전에는 `uv run pytest tests/` 를 한 번도 돌리지 않는다** — 전체 수집이 모듈 레벨 pykrx import 를 태워 로그인 요청을 낸다. 유일한 예외는 `probe_krx.sh` 이며 **08-06 이후에만** 실행한다.
- **재개 목표일: 2026-08-06(목).**
- `uv run pytest tests/` **기대 실패 0**. 기준선: Task 1 적용 후 `-m "not krx"` 로 deselect 되는 것은 **`test_integration.py` 1개뿐**이어야 한다(13개 DB 통합 테스트는 계속 실행).
- 테스트 DB 는 `kr_test`. **동시 pytest 금지** — 실행 전 `pgrep -f pytest` 확인.
- 스테이징은 **항상 명시 경로**. `git add -A` 금지. 커밋에 `Co-Authored-By: Claude` 트레일러 금지.
- `kr_pipeline/common/thresholds.py` 미변경 — 본 계획의 상수는 전부 운영 파라미터이며 책-유래 임계가 아니다(2축 판정 대상 아님).
- launchd plist 미수정. `scripts/launchd/install.sh` **재실행 금지**(crontab 재변경 + RunAtLoad 즉발 발생).
- 캐시 읽기·쓰기 실패가 호출부를 깨뜨리지 않아야 한다(`trading_calendar` 는 fail-closed 경로다 — 캐시 I/O 는 try/except 로 감싸 라이브 조회로 degrade).

## 현재 상태 (실측, 2026-08-03)

- launchd 4잡(`evening-chain`·`weekend-chain`·`monthly-chain`·`pipeline-watch`) **bootout 완료**. `morning-corp`(DART 전용)·`bt-c-watchdog`(로그인 0건) 유지.
- 접촉 실측: 감시 ELTD 08-02 15회, 전 종목 스윕 08-02 2회·08-03 1회(`empty_fetch` 86~88%).
- `daily_prices` 최신 = 2026-07-31 **1,197/2,549행(47%)**. 주봉·주간지표가 그 위에서 재계산되어 오염됨(별건, 재개 후 처리).

## 목표 달성 검증 — KRX 요청 수 (평일 1일 기준)

ELTD 1회는 로그인 1 + 지수 OHLCV 1 + (`name_display=True` 일 때) 마스터 4 = **6 요청**이다.
Step 5c 의 `name_display=False` 적용 후에는 **2 요청**.

| 경로 | 차단 전(안전했던 2개월) | 차단 후 실측(08-02) | 계획 적용 후 |
|---|---|---|---|
| 감시 ELTD (시간당) | 0 (감시 잡 자체가 없었음) | 15회 × 6 = **90** | **0** (순수 bash 캐시 읽기) |
| 저녁 체인 ELTD | 1회 × 6 = 6 | 발화마다 | 1회 × 2 = **2** |
| 전 종목 raw 스윕 | 1회 × 2,549 = 2,549 | **2~3회** = 5,098~7,647 | 1회 × 2,549 = **2,549** (상한) |
| `llm_runner` ELTD | 1회 × 6 = 6 | — | 1회 × 2 = **2** |
| `morning-corp` | 0 (DART) | 0 | 0 |
| **합계** | **~2,561** | **~5,200~7,700+** | **~2,553** |

핵심: **불가피한 부하(전 종목 raw 2,549)는 그대로 두고, 그 위에 얹혀 있던 초과분을 제거**한다.
차단 전 2개월간 안전했던 수준(~2,561)으로 되돌리면서 감시 잡이 새로 추가한 90 요청까지 없앤다.

주봉 체인(주 1회)의 대량 조회 2,549건은 **Naver 경로**라 이 표에 포함되지 않는다
(`fetch_adj_only` → `adjusted=True` → pykrx `stock_api.py:236-237`). 다만 그쪽 ELTD 2 요청은 KRX 다.

## File Structure

| 파일 | 책임 | 변경 |
|---|---|---|
| `tests/conftest.py` | 테스트 부트스트랩 | KRX 자격증명 무력화(빈 문자열) + ELTD 캐시 경로 격리 autouse 픽스처 (Task 1·2) |
| `pyproject.toml` | pytest 설정 | `krx` 마커 추가, `addopts` 에 `-m "not krx"` (Task 1) |
| `tests/test_integration.py` | 유일한 KRX 접촉 테스트 | `pytest.mark.krx` 추가 (Task 1) |
| `tests/test_krx_contact_isolation.py` | **신규** — pytest 무접촉 고정 | 생성 (Task 1) |
| `kr_pipeline/common/trading_calendar.py` | ELTD 산출 | 파일 캐시 write + `cached_eltd()` read-only 추가 (Task 2) |
| `tests/test_trading_calendar.py` | ELTD 테스트 | 캐시 동작 테스트 추가 (Task 2) |
| `scripts/launchd/lib_guards.sh` | 래퍼 공용 가드 | `KR_DB` 변수화, `eltd_cached_latest()` 추가, `attempt_allowed()` 추가 (Task 2·3) |
| `scripts/launchd/watch_pipelines.sh` | 감시 | `q()` 변수화, ELTD 를 캐시 read-only 로, `eltd_stale` 알림 (Task 2) |
| `scripts/launchd/evening_chain.sh` | 평일 저녁 체인 | 데이터 체인 앞에 시도 상한 (Task 3) |
| `scripts/launchd/monthly_chain.sh` | 월간 체인 | universe 앞에 시도 상한 (Task 3) |
| `tests/test_launchd_guards.py` | **신규** — 셸 가드 검증 | 생성 (Task 3) |
| `scripts/launchd/probe_krx.sh` | **신규** — 재개 탐침 | 생성 (Task 4) |

---

### Task 1: pytest 의 KRX 접촉 차단 (선행 필수)

**왜 맨 앞인가:** 지금 `uv run pytest tests/` 는 실행마다 KRX 로그인 POST 를 낸다. `tests/conftest.py:10` 의 `load_dotenv()` 가 자격증명을 주입하고, 테스트 모듈이 모듈 레벨에서 `kr_pipeline.ohlcv.fetch` → `from pykrx import stock` 을 import 하면 `pykrx/website/comm/webio.py:12` 의 `_session = build_krx_session()` 이 로그인한다. **Task 2·3 은 pytest 를 여러 번 돌려야 하므로 이 차단이 선행되어야 한다.**

`build_krx_session` 은 자격증명이 falsy 면 HTTP 없이 `None` 을 반환한다(`auth.py:176-181`). 값을 **빈 문자열로 대입**해야 durable 하다 — `pop` 하면 `config.py:5` 의 `load_dotenv()` 가 복원한다(`dotenv/main.py:105`).

**Files:**
- Modify: `tests/conftest.py:10` 직후
- Modify: `pyproject.toml:36-39`
- Modify: `tests/test_integration.py` (마커 추가)
- Test: `tests/test_krx_contact_isolation.py` (신규)

**Interfaces:**
- Produces: env 규약 `KR_ALLOW_KRX=1` — 설정 시에만 자격증명이 유지된다. 마커 `krx` — KRX 접촉 테스트 표시, 기본 제외.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_krx_contact_isolation.py` 생성:

```python
"""pytest 실행이 KRX 로 나가지 않음을 고정 (#88 차단 재발 방지).

pykrx 는 import 시점에 build_krx_session() 을 실행해 KRX_ID/KRX_PW 로 로그인
POST 를 보낸다(pykrx/website/comm/webio.py:12). 자격증명이 falsy 면 HTTP 없이
None 을 반환하므로(comm/auth.py:176-181) conftest 가 pykrx import 전에 값을 비운다.
pop 이 아니라 빈 문자열이어야 한다 — kr_pipeline/common/config.py:5 의
load_dotenv() 가 "키가 없으면" 복원하기 때문(dotenv/main.py:105).
"""
import os
import tomllib
from pathlib import Path

import pytest

PYPROJECT = Path(__file__).parent.parent / "pyproject.toml"

# KR_ALLOW_KRX=1 세션은 격리를 의도적으로 해제한 것이므로 전부 skip.
# 특히 마지막 테스트는 get_auth_session() 이 호출 시점에 os.getenv 를 다시 읽어
# build_krx_session 을 재시도하므로(auth.py:208-223), 해제 세션에서 돌리면
# 실제 로그인 POST 가 나간다.
pytestmark = pytest.mark.skipif(
    os.environ.get("KR_ALLOW_KRX") == "1", reason="KR_ALLOW_KRX=1 — 격리 해제 세션"
)


def _ini() -> dict:
    with PYPROJECT.open("rb") as f:
        return tomllib.load(f)["tool"]["pytest"]["ini_options"]


def test_krx_credentials_are_blank():
    """자격증명이 빈 값이다 — import 시 로그인 요청이 나가지 않는다."""
    assert not os.environ.get("KRX_ID"), "KRX_ID 가 살아 있다 — 로그인 요청이 나간다"
    assert not os.environ.get("KRX_PW"), "KRX_PW 가 살아 있다 — 로그인 요청이 나간다"


def test_krx_keys_still_present_so_dotenv_cannot_restore():
    """키 자체는 남아 있어야 한다 — 없으면 load_dotenv() 가 되살린다."""
    assert "KRX_ID" in os.environ, "키가 제거됨 — config.py 의 load_dotenv 가 복원한다"
    assert "KRX_PW" in os.environ, "키가 제거됨 — config.py 의 load_dotenv 가 복원한다"


def test_dotenv_reload_does_not_restore_credentials():
    """config 를 import 해 load_dotenv 가 다시 돌아도 자격증명이 비어 있다."""
    from kr_pipeline.common import config  # noqa: F401 — import 부작용 확인용

    from dotenv import load_dotenv

    load_dotenv()
    assert not os.environ.get("KRX_ID"), "load_dotenv 가 KRX_ID 를 복원했다"


def test_krx_marker_declared_and_excluded_by_default():
    """krx 마커가 선언되고 기본 제외된다."""
    ini = _ini()
    assert any(m.startswith("krx:") for m in ini["markers"]), f"markers={ini['markers']}"
    assert "not krx" in ini["addopts"], f"addopts={ini['addopts']!r}"


def test_integration_db_tests_not_excluded():
    """DB 전용 integration 테스트 13개는 기본 실행에서 제외되지 않는다."""
    ini = _ini()
    assert "not integration" not in ini["addopts"], (
        "integration 통째 제외는 Postgres 전용 테스트 13개를 죽인다 — krx 마커만 제외할 것"
    )


def test_pykrx_session_is_none_after_import():
    """pykrx 를 import 해도 세션이 없다(= 로그인 요청 없음). green 단계에서만 실행."""
    from pykrx.website.comm.auth import get_auth_session

    assert get_auth_session() is None
```

- [ ] **Step 2: 테스트 실패 확인 (pykrx 미접촉 항목만)**

마지막 테스트는 pykrx 를 import 하므로 red 단계에서 실행하지 않는다. import 가
**함수 본문 안**에 있어 수집 단계에서는 실행되지 않으므로 `-k` 로 제외하면 접촉이 0이다.

```bash
pgrep -f pytest && echo "다른 pytest 실행 중 — 대기" || \
uv run pytest tests/test_krx_contact_isolation.py -p no:randomly \
  -k "not pykrx_session" -v
```

Expected: **3 FAIL / 2 PASS**.
- FAIL: `test_krx_credentials_are_blank`(값이 살아 있음), `test_dotenv_reload_does_not_restore_credentials`(동일), `test_krx_marker_declared_and_excluded_by_default`(markers 에 krx 없음)
- PASS: `test_krx_keys_still_present_so_dotenv_cannot_restore`(아직 아무것도 안 지웠으므로 키가 있다), `test_integration_db_tests_not_excluded`(현재 addopts 가 `-v` 뿐이라 "not integration" 이 없다)

- [ ] **Step 3: conftest 에 자격증명 무력화 추가**

`tests/conftest.py` 의 `load_dotenv()` (10행) 바로 아래 삽입:

```python
load_dotenv()

# ── KRX 자격증명 무력화 (#88) ────────────────────────────────────────
# pykrx 는 import 시점에 build_krx_session() 을 호출해 KRX 로 로그인 POST 를
# 보낸다(website/comm/webio.py:12). 자격증명이 falsy 면 HTTP 없이 None 을
# 반환하므로(comm/auth.py:176-181) 테스트 모듈 import 전에 값을 비운다.
# ⚠️ pop 하면 안 된다 — kr_pipeline/common/config.py:5 가 import 시 load_dotenv()
# 를 다시 돌리고, dotenv 는 "키가 os.environ 에 없을 때만" 주입하므로
# (dotenv/main.py:105) 제거한 값이 복원된다. 키는 남기고 값만 비운다.
if os.environ.get("KR_ALLOW_KRX") != "1":
    os.environ["KRX_ID"] = ""
    os.environ["KRX_PW"] = ""
```

`os` 는 `tests/conftest.py:1` 에서 이미 import 되어 있다.

- [ ] **Step 4: `krx` 마커 신설 및 기본 제외**

`pyproject.toml:36-39` 을 다음으로 교체:

```toml
addopts = "-v -m 'not krx'"
markers = [
    "integration: 실제 외부 IO (Postgres + pykrx)",
    "krx: 실제 KRX 접촉 — 기본 제외(#88). 실행은 KR_ALLOW_KRX=1 uv run pytest -m krx",
]
```

`tests/test_integration.py` 의 `pytestmark` 줄(2행 부근)을 교체:

```python
pytestmark = [pytest.mark.integration, pytest.mark.krx]
```

- [ ] **Step 5: 테스트 통과 확인**

```bash
uv run pytest tests/test_krx_contact_isolation.py -v
```

Expected: 6 passed. (이 시점에는 자격증명이 비어 있어 `test_pykrx_session_is_none_after_import`
의 pykrx import 가 로그인을 내지 않는다.)

- [ ] **Step 6: 전체 suite 회귀 확인 + deselect 수 검증**

```bash
pgrep -f pytest; uv run pytest tests/ 2>&1 | tail -25
```

Expected: **0 failed**, `1 deselected`. deselect 가 1을 넘으면 `krx` 마커를
과하게 붙인 것이므로 되돌린다. DB 전용 integration 13개(weekly 4·market_context 4·
corporate_actions 3·indicators 2)는 실행되어야 한다.

- [ ] **Step 7: 커밋**

```bash
git add tests/conftest.py pyproject.toml tests/test_integration.py tests/test_krx_contact_isolation.py
git commit -m "fix(#92): pytest 의 KRX 로그인 차단 — 자격증명 무력화 + krx 마커 신설

pytest 실행마다 pykrx import 가 KRX 로그인 POST 를 냈다. conftest 가 수집 전에
KRX_ID/KRX_PW 를 빈 문자열로 만들어 build_krx_session 이 HTTP 없이 None 을
반환하게 한다. pop 이 아니라 빈 문자열인 이유는 config.py 의 load_dotenv 가
'키가 없을 때만' 주입해 pop 한 값을 복원하기 때문.

integration 통째 제외는 Postgres 전용 테스트 13개를 죽이므로, KRX 접촉
테스트(test_integration.py 1개)에만 krx 마커를 붙여 그것만 제외한다."
```

---

### Task 2: ELTD 파일 캐시 — 감시의 KRX 접촉을 0으로

**문제:** `watch_pipelines.sh:60` 이 매시간 ELTD 라이브 조회를 낸다(실측 15회/일). 실패해도 백오프가 없어 차단 상태에서 매시간 재시도했다. 셸에만 캐시를 넣으면 Python 호출부(`llm_runner/__main__.py:96`, `weekly/modes.py:157`)를 못 막고, 셸 `eltd()` 는 매번 새 프로세스라 in-memory 캐시가 무의미하다.

**해법 — 역할 분리:**
- **체인**(하루 1회 도는 쪽)은 `expected_latest_trading_day` 를 **항상 라이브**로 호출하고, 성공 시 파일 캐시에 쓴다.
- **감시**(시간당)는 **순수 bash `eltd_cached_latest()`** 로 캐시 파일을 직접 읽는다. Python 을 태우지
  않는다 — `trading_calendar` 를 import 하는 순간 pykrx 가 로드되어 로그인이 나가기 때문이다.
  Python 쪽 `cached_eltd()` 는 캐시 형식을 정의·검증하는 SSOT 역할이며 Python 호출부용이다.
- 캐시가 낡았으면 그것이 곧 "체인이 안 돌았다" 신호이므로 `eltd_stale` 알림을 낸다. 공휴일에도 체인은 평일 스케줄로 발화해 라이브 조회 후 캐시를 갱신하므로(데이터 몫은 "완료 — skip") 오탐이 없다.

negative(실패) 캐시는 **넣지 않는다.** `llm_runner` 가 fail-closed 라, 일시 오류를 FAIL 캐시하면 그날 저녁 체인이 통째로 skip 된다.

**Files:**
- Modify: `kr_pipeline/common/trading_calendar.py`
- Modify: `tests/conftest.py` (캐시 경로 격리 autouse 픽스처)
- Modify: `scripts/launchd/lib_guards.sh` (`KR_DB` 변수화, `eltd_cached_latest()`)
- Modify: `scripts/launchd/watch_pipelines.sh` (`q()` 변수화, 캐시 read-only, `eltd_stale`)
- Test: `tests/test_trading_calendar.py` (추가)

**Interfaces:**
- Consumes: Task 1 의 pytest 격리
- Produces:
  - `trading_calendar.eltd_cache_path() -> Path` — env `ELTD_CACHE` 우선, 기본 `~/.kr-by-claude/state/eltd.cache`
  - `trading_calendar.cache_key(now: datetime) -> str` — `YYYY-MM-DD:pre|post` (17시 경계)
  - `trading_calendar.cached_eltd(now: datetime) -> date | None` — 캐시 read-only. 미스면 None. **라이브 호출 없음**
  - `expected_latest_trading_day(now)` — 기존 시그니처·예외 유지 + 성공 시 캐시 write
  - 셸 `eltd_cached_latest()` — stdout 에 날짜 또는 빈 문자열, rc=0/1
  - env `KR_DB` (기본 `kr_pipeline`)

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_trading_calendar.py` 끝에 추가:

```python
# ─── #88 ELTD 파일 캐시 ────────────────────────────────────────────

def test_cache_key_distinguishes_close_buffer():
    """17시 경계로 키가 갈린다 — CLOSE_BUFFER=17:00 때문에 답이 다르다."""
    assert tc.cache_key(datetime(2026, 6, 10, 16, 59)).endswith(":pre")
    assert tc.cache_key(datetime(2026, 6, 10, 17, 0)).endswith(":post")
    assert tc.cache_key(datetime(2026, 6, 10, 17, 0)).startswith("2026-06-10")


def test_expected_latest_writes_cache(monkeypatch):
    """라이브 조회 성공 시 캐시에 쓴다."""
    _patch_fetch(monkeypatch, [date(2026, 6, 9), date(2026, 6, 10)])
    now = datetime(2026, 6, 10, 18, 0)
    assert tc.expected_latest_trading_day(now) == date(2026, 6, 10)
    assert tc.cached_eltd(now) == date(2026, 6, 10)


def test_cached_eltd_never_calls_live(monkeypatch):
    """cached_eltd 는 캐시 미스여도 라이브를 부르지 않는다."""
    calls = []

    def boom(*a, **k):
        calls.append(1)
        raise AssertionError("cached_eltd 가 라이브를 호출했다")

    monkeypatch.setattr(tc, "fetch_index", boom)
    assert tc.cached_eltd(datetime(2026, 6, 10, 18, 0)) is None
    assert calls == []


# ⚠️ 초안에 있던 `test_cached_eltd_miss_on_different_key`("다른 키면 미스") 는 **삭제했다**.
#    그 의미론을 고정하면 감시가 D+1 오전 17시간 동안 판정 불가가 된다(2회차 검토 F2).
#    Python `cached_eltd(now)` 는 같은 키의 값이 라이브와 정의상 동일함을 보장하는
#    용도로만 남기고, 감시(셸)는 `eltd_cached_latest` 로 최신 1건 + 나이를 읽는다.


def test_failure_is_not_cached(monkeypatch):
    """실패는 캐시하지 않는다 — negative 캐시는 fail-closed 체인을 마비시킨다."""
    _patch_fetch(monkeypatch, [], raises=True)
    now = datetime(2026, 6, 10, 18, 0)
    with pytest.raises(tc.TradingCalendarUnavailable):
        tc.expected_latest_trading_day(now)
    assert tc.cached_eltd(now) is None
    _patch_fetch(monkeypatch, [date(2026, 6, 9), date(2026, 6, 10)])
    assert tc.expected_latest_trading_day(now) == date(2026, 6, 10)


def test_cache_io_failure_degrades_to_live(monkeypatch, tmp_path):
    """캐시 경로가 쓸 수 없어도 라이브 조회 결과를 정상 반환한다(fail-closed 보호).

    `monkeypatch.setattr(Path, "mkdir", ...)` 로 하지 않는다 — 클래스 전역 패치라
    같은 테스트 안의 모든 mkdir 을 깨뜨리는 지뢰가 된다(2회차 검토 확인).
    실제 권한 없는 디렉터리를 쓴다.
    """
    ro = tmp_path / "ro"
    ro.mkdir(mode=0o500)
    try:
        monkeypatch.setenv("ELTD_CACHE", str(ro / "sub" / "eltd.cache"))
        _patch_fetch(monkeypatch, [date(2026, 6, 9), date(2026, 6, 10)])
        assert tc.expected_latest_trading_day(datetime(2026, 6, 10, 18, 0)) == date(2026, 6, 10)
    finally:
        ro.chmod(0o700)   # tmp_path 정리 보장


def test_corrupt_cache_self_heals(monkeypatch, tmp_path):
    """비-UTF8 로 손상된 캐시도 다음 쓰기에서 복구된다.

    `_write_cache` 가 기존 내용 읽기를 안쪽 try 로 감싸지 않으면 UnicodeDecodeError 가
    바깥 except 로 빠져 **쓰기 자체가 실행되지 않고** 캐시가 영구 손상 상태로 남는다
    (2회차 검토 F3 실측). 그러면 감시의 결측 판정이 죽는다.
    """
    p = tmp_path / "eltd.cache"
    p.write_bytes(b"\xff\xfe bad\n")
    monkeypatch.setenv("ELTD_CACHE", str(p))
    _patch_fetch(monkeypatch, [date(2026, 6, 9), date(2026, 6, 10)])
    now = datetime(2026, 6, 10, 18, 0)
    assert tc.expected_latest_trading_day(now) == date(2026, 6, 10)
    assert tc.cached_eltd(now) == date(2026, 6, 10), "손상 캐시가 자기치유되지 않았다"
```

`tests/conftest.py` 에 캐시 격리 픽스처 추가 (파일 끝):

```python
@pytest.fixture(autouse=True)
def _isolate_eltd_cache(tmp_path, monkeypatch):
    """#88: ELTD 파일 캐시를 테스트별로 격리.

    캐시가 없으면 test_trading_calendar 의 서로 다른 기대값이 같은 키를 공유해
    가짜 초록이 된다 (예: test_eltd_today_after_buffer 와 test_unavailable_on_empty
    는 둘 다 now=2026-06-10 18:00 → 키 '2026-06-10:post').
    """
    monkeypatch.setenv("ELTD_CACHE", str(tmp_path / "eltd.cache"))
```

- [ ] **Step 2: 테스트 실패 확인**

```bash
uv run pytest tests/test_trading_calendar.py -v
```

Expected: 신규 6개 FAIL (`AttributeError: module ... has no attribute 'cache_key'` 등).
**기존 8개는 PASS 유지**되어야 한다 — 통과하지 않으면 autouse 픽스처가 기존 테스트를 깨뜨린 것이다.

- [ ] **Step 3: `trading_calendar.py` 구현**

파일 상단 import 에 추가:

```python
import os
from pathlib import Path
```

`_LOOKBACK_DAYS` 상수 아래에 추가:

```python
_CACHE_DEFAULT = "~/.kr-by-claude/state/eltd.cache"


def eltd_cache_path() -> Path:
    """ELTD 캐시 파일 경로. env ELTD_CACHE 우선(테스트 격리용)."""
    return Path(os.environ.get("ELTD_CACHE") or _CACHE_DEFAULT).expanduser()


def cache_key(now: datetime) -> str:
    """캐시 키 = 날짜 + 마감버퍼 구간. 17시 전후로 ELTD 가 달라지므로 날짜만으로는 부족."""
    return f"{now.date().isoformat()}:{'post' if now.time() >= CLOSE_BUFFER else 'pre'}"


def cached_eltd(now: datetime) -> date | None:
    """캐시된 ELTD 를 읽는다. **라이브 조회를 하지 않는다** — 미스면 None.

    시간당 도는 감시(watch_pipelines.sh)용. 감시가 라이브를 부르면 차단 상태에서
    매시간 재시도하게 되어 재탐지를 유발한다(08-02 실측 15회/일).
    """
    try:
        text = eltd_cache_path().read_text()
    except (OSError, ValueError):
        return None
    want = cache_key(now)
    for line in reversed(text.splitlines()):
        k, _, v = line.partition("|")
        if k == want and v:
            try:
                return date.fromisoformat(v)
            except ValueError:
                return None
    return None


def _write_cache(now: datetime, value: date) -> None:
    """캐시 갱신. 실패는 무시한다 — 캐시는 보조 수단이고 호출부는 fail-closed 경로다.

    ⚠️ 기존 내용 읽기를 **안쪽 try 로 감싼다**(2회차 검토 F3). 파일이 비-UTF8 로 손상되면
    `read_text()` 가 UnicodeDecodeError 를 던지고, 그게 바깥 except 로 빠지면 **쓰기 자체가
    실행되지 않아** 캐시가 영구히 손상 상태로 남는다. 그러면 감시가 매 평일 21시
    eltd_stale 만 울리고 결측 판정(miss.data/miss.llm/miss.eval)이 죽는다.
    손상된 내용은 버리고 새로 쓴다 = 자기치유.

    쓰기는 tmp → replace 로 원자 교체한다. 감시(시간당)와 체인이 같은 파일을 읽고 쓰므로
    부분 쓰기로 인한 손상 경로 자체를 없앤다.
    """
    try:
        p = eltd_cache_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        try:
            prev = p.read_text().splitlines() if p.exists() else []
        except (OSError, UnicodeDecodeError):
            prev = []          # 손상 파일은 버린다 — 쓰기를 막지 않는다
        want = cache_key(now)
        keep = [ln for ln in prev if not ln.startswith(f"{want}|")][-30:]
        tmp = p.with_name(p.name + ".tmp")
        tmp.write_text("\n".join(keep + [f"{want}|{value.isoformat()}"]) + "\n")
        tmp.replace(p)         # 원자 교체
    except Exception as e:  # noqa: BLE001 — 캐시 실패가 ELTD 산출을 막아선 안 된다
        log.warning("ELTD 캐시 쓰기 실패(무시): %s", e)
```

`expected_latest_trading_day` 의 두 `return` 을 캐시 write 경유로 바꾼다.
43-50행의 `if today in trading_days ...` 블록을 다음으로 교체:

```python
    if today in trading_days and now.time() >= CLOSE_BUFFER:
        _write_cache(now, today)
        return today
    prior = [d for d in trading_days if d < today]
    if not prior:
        raise TradingCalendarUnavailable(
            f"직전 거래일 없음(lookback {_LOOKBACK_DAYS}d, today={today})"
        )
    result = max(prior)
    _write_cache(now, result)
    return result
```

- [ ] **Step 3b: `assert_data_fresh` 가 캐시를 먼저 읽게 한다** (결정 1 — 채택)

`trading_calendar.py:53-63` 의 `assert_data_fresh` 를 다음으로 교체:

```python
def assert_data_fresh(as_of: date, now: datetime) -> None:
    """as_of(최신 완전 지표일)가 ELTD 보다 뒤처지면 StaleDataError.

    #88: 캐시를 먼저 읽는다. 캐시 키가 (날짜 + 마감버퍼 구간)이므로 **같은 키의 값은
    라이브 조회 결과와 정의상 동일**하고(위 expected_latest_trading_day 의 분기가 그 두 축만
    사용), 따라서 판정력은 줄지 않는다. 저녁 체인은 15분 전 eltd() 로 이미 라이브 조회를
    했으므로 여기서 또 묻는 것은 KRX 요청 2건의 낭비이며, 그 15분 사이의 일시 장애가
    그날 LLM 분석을 통째로 취소시키는 취약점이기도 하다.
    캐시 미스 시에는 라이브로 폴백하므로 fail-closed 성질은 유지된다.
    """
    eltd = cached_eltd(now)
    if eltd is None:
        eltd = expected_latest_trading_day(now)
    if as_of < eltd:
        raise StaleDataError(
            f"최신 완전 데이터 {as_of} < 기대 최신 거래일 {eltd} — 분석 중단"
        )
```

기존 예외 메시지 문구는 `trading_calendar.py:61-63` 의 것을 그대로 유지할 것(문구를 바꾸면
`tests/test_trading_calendar.py` 의 `pytest.raises` 매칭이나 로그 grep 관례가 깨질 수 있다).

`tests/test_trading_calendar.py` 에 추가:

```python
def test_assert_fresh_uses_cache_without_live_call(monkeypatch):
    """캐시가 있으면 assert_data_fresh 가 라이브를 부르지 않는다(결정 1)."""
    _patch_fetch(monkeypatch, [date(2026, 6, 9), date(2026, 6, 10)])
    now = datetime(2026, 6, 10, 18, 0)
    tc.expected_latest_trading_day(now)          # 캐시 채우기(라이브 1회)

    def boom(*a, **k):
        raise AssertionError("assert_data_fresh 가 라이브를 호출했다")

    monkeypatch.setattr(tc, "fetch_index", boom)
    tc.assert_data_fresh(date(2026, 6, 10), now)          # 통과해야 함
    with pytest.raises(tc.StaleDataError):
        tc.assert_data_fresh(date(2026, 6, 9), now)       # 판정력 유지 확인


def test_assert_fresh_falls_back_to_live_on_cache_miss(monkeypatch):
    """캐시가 없으면 라이브로 폴백한다 — fail-closed 유지."""
    _patch_fetch(monkeypatch, [], raises=True)
    with pytest.raises(tc.TradingCalendarUnavailable):
        tc.assert_data_fresh(date(2026, 6, 10), datetime(2026, 6, 10, 18, 0))
```

- [ ] **Step 4: 테스트 통과 확인**

```bash
uv run pytest tests/test_trading_calendar.py -v
```

Expected: 17 passed (기존 8 + 캐시 7 + 결정 1의 2개).

- [ ] **Step 5: 셸 측 `eltd_cached_latest()` 와 `KR_DB` 구현**

`lib_guards.sh` 의 `LOCK_DIR` 블록(9-10행) 아래에 삽입:

```bash
KR_DB="${KR_DB:-kr_pipeline}"
ATTEMPT_MAX_DEFAULT="${ATTEMPT_MAX_DEFAULT:-2}"
# 6h — 실측 기반(2회차 검토 F6): 08-01 의 두 스윕 간격이 5h57m 이라 4h 게이트로는 통과한다.
# 6h 로 두면 08-01·08-02 의 두 번째 스윕이 모두 차단되고, 6시간 뒤 정당한 만회는 허용된다.
ATTEMPT_GAP_DEFAULT="${ATTEMPT_GAP_DEFAULT:-21600}"
# ⚠️ ${HOME:-/tmp} — plist EnvironmentVariables 에는 PATH·KR_REPO 만 있어 HOME 이 없을 수
# 있고, 이 파일은 set -u 라 무방비 참조 시 source 자체가 죽는다(log() 정의 전이라 무음).
ELTD_CACHE="${ELTD_CACHE:-${HOME:-/tmp}/.kr-by-claude/state/eltd.cache}"
```

`db_query`(18-22행)의 `-d kr_pipeline` → `-d "$KR_DB"`.

`eltd()` (25-34행) 뒤에 추가:

```bash
# 캐시된 ELTD 만 읽는다 — 감시 전용. 미스면 빈 문자열 + rc=1.
#
# ⚠️ 순수 bash 로 구현한다. Python 을 태우면 안 된다 —
#   trading_calendar.py:10 → ohlcv/fetch.py:9 → pykrx → webio.py:12 build_krx_session()
#   이므로 "캐시만 읽는" 호출이 매시간 KRX 로그인 POST 를 낸다(실측 확인:
#   `KRX_ID= uv run python -c "import kr_pipeline.common.trading_calendar"` 가
#   "KRX 로그인 실패: ... 환경 변수가 설정되지 않았습니다" 를 출력 = build_krx_session 실행).
#   캐시 형식이 KEY|VALUE 라 bash 로 자명하게 읽을 수 있고, uv 기동 비용도 없다.
# TZ=Asia/Seoul 고정 — Python 쪽 CLOSE_BUFFER 판정이 KST 기준이라 시스템 TZ 를 쓰면 키가 어긋난다.
# 캐시 최신 1건과 그 나이(초)를 "<date> <age_sec>" 로 출력. 미스/손상이면 rc=1.
#
# ⚠️ 정확일치 키로 읽으면 안 된다(2회차 검토 F2). 캐시를 쓰는 주체는 저녁 체인
#   (18:30 → 키 `D:post`)뿐이므로, D+1 00:00~16:59 의 조회 키 `D+1:pre` 는 **항상 미스**가
#   된다. 그런데 그 17시간이 바로 "어제 저녁 통째 수면"을 탐지해야 하는 구간이고,
#   #88 이 존재하는 이유가 그 시나리오다. 정확일치로 읽으면 감시가 그 구간에서 죽는다.
#   최신 1건 + 파일 나이로 읽으면 KRX 접촉 0을 유지하면서 24시간 커버리지를 지킨다.
#   시각 판정은 기존 DUE 게이트(대상일 +21h)가 이미 담당한다.
eltd_cached_latest() {
  local v m
  [ -f "$ELTD_CACHE" ] || return 1
  v=$(tail -1 "$ELTD_CACHE" 2>/dev/null | cut -d'|' -f2)
  case "$v" in [0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]) ;; *) return 1 ;; esac
  m=$(stat -f %m "$ELTD_CACHE" 2>/dev/null) || return 1
  echo "$v $(( $(date +%s) - m ))"
}
```

bash 가 키를 계산하지 않으므로 Python `cache_key` 와의 desync 위험이 사라진다(초안이 우려했던 항목 해소).

- [ ] **Step 6: `watch_pipelines.sh` 를 캐시 read-only 로 전환**

**29행과 33행 둘 다** `psql -d "$KR_DB"` 로 바꾼다 — 29행(DB 불통 자체 확인)도 하드코딩이며,
빠뜨리면 Step 7 의 "리터럴 0건" 기대가 실패한다(2회차 검토 F7). 30행 알림 문구의
`kr_pipeline DB` 도 `$KR_DB` 로.

그리고 59-73행 블록을 교체:

```bash
# ── 3. 저녁 몫 결측 — 캐시 최신 1건 기준. 라이브 조회하지 않는다(#88).
#    캐시는 체인이 발화할 때마다 갱신된다(공휴일에도 평일 스케줄로 발화 → 갱신).
#    따라서 "캐시가 오래 안 갱신됐다" = "체인이 안 돌았다" 이고, 그 자체가 결측 신호다.
CACHED=$(eltd_cached_latest) || CACHED=""
E=""; AGE=999999
if [ -n "$CACHED" ]; then E=${CACHED%% *}; AGE=${CACHED##* }; fi
if [ -n "$E" ] && [ "$AGE" -lt 108000 ]; then   # 30h — 주말(금 저녁→월 저녁)은 stale 판정에서 제외됨
  DUE=$(q "SELECT (now() >= '$E'::date + interval '21 hours')::int")   # 대상일 21시 이후부터 판정
  if [ "$DUE" = "1" ]; then
    MAXI=$(q "SELECT COALESCE(MAX(date)::text,'0001-01-01') FROM daily_indicators")
    [ "$MAXI" \< "$E" ] && alert "miss.data.$E" "데이터 체인 미완료 (대상 거래일 $E, 지표 최신 $MAXI)"
    N=$(q "SELECT COUNT(*) FROM pipeline_runs WHERE pipeline='llm_daily_delta' AND mode='full-daily' AND status IN ('success','running') AND params->>'as_of'='$E'")
    [ "${N:-0}" -gt 0 ] || alert "miss.llm.$E" "LLM full-daily 미시작 (대상 $E)"
    N=$(q "SELECT COUNT(*) FROM pipeline_runs WHERE pipeline='trade_management' AND mode='daily-eval' AND status='success' AND started_at >= '$E'::date + interval '17 hours'")
    [ "${N:-0}" -gt 0 ] || alert "miss.eval.$E" "포지션 일일 평가 미실행 (대상 $E — 소급 불가 항목)"
  fi
else
  # 캐시가 30h 넘게 안 갱신됐거나 없음 = 체인 미발화 의심.
  # ⚠️ 체인 잡이 **로드돼 있을 때만** 알림한다(2회차 검토 F4). bootout 상태(지금처럼
  #   의도적으로 내려둔 기간, 또는 "감시만 먼저 재개" 하는 재개 3단계)에서는 정보량이 0인
  #   소음이 평일마다 울린다.
  DOW_S=$(date +%w); HOUR_S=$(date +%H)
  if [ "$DOW_S" != "0" ] && [ "$DOW_S" != "6" ] && [ "$HOUR_S" -ge 21 ] \
     && launchctl list com.krbyclaude.evening-chain >/dev/null 2>&1; then
    alert "eltd_stale.$(date +%Y%m%d)" "ELTD 캐시 미갱신(${AGE}s) — 저녁 체인 미실행 의심(라이브 조회 없음)"
  fi
fi
```

- [ ] **Step 6b: ELTD 산출 실패를 `exit 0` 으로 낮춘다** (결정 4 — 채택)

`evening_chain.sh:16-21` 을 교체:

```bash
# ── 대상 거래일 (fail-closed — 산출 못 하면 아무 단계도 진행하지 않는다)
ELTD=$(eltd)
if [ -z "$ELTD" ]; then
  # #88 결정 4: 중단은 유지하되 종료 코드는 0. exit 1 이면 launchd 가 failed 로 기록하고
  # 감시의 failed.* 알림이 발화마다 울린다(차단 기간엔 같은 알림 반복). 데이터 결측 자체는
  # miss.data.* 알림이 담당하므로 정보 손실이 없다.
  log "ELTD 산출 실패 — fail-closed 중단(exit 0: launchd failed 소음 회피)"
  exit 0
fi
```

**주의:** 중단 자체는 그대로다 — 뒤따르는 어떤 단계도 실행되지 않는다. 바뀌는 것은
launchd 의 성공/실패 기록과 그에 따른 알림뿐이다.

- [ ] **Step 7: 문법·정합 확인**

```bash
for f in scripts/launchd/*.sh; do bash -n "$f" || echo "문법 오류: $f"; done; echo "문법 검사 완료"
grep -n 'psql -d' scripts/launchd/*.sh    # 하드코딩 잔여 0 이어야 함
grep -n 'eltd\b\|eltd_cached' scripts/launchd/*.sh
```

Expected: 문법 오류 없음. `psql -d kr_pipeline` 리터럴 0건.
`eltd()` 는 `evening_chain.sh:17` 만, `eltd_cached_latest()` 는 `watch_pipelines.sh` 만 사용.

- [ ] **Step 8: 전체 suite 회귀 확인**

```bash
pgrep -f pytest; uv run pytest tests/ 2>&1 | tail -20
```

Expected: 0 failed, 1 deselected.

- [ ] **Step 9: 커밋**

```bash
git add kr_pipeline/common/trading_calendar.py tests/test_trading_calendar.py tests/conftest.py \
        scripts/launchd/lib_guards.sh scripts/launchd/watch_pipelines.sh
git commit -m "fix(#92): ELTD 파일 캐시 — 감시의 KRX 접촉을 0회로

감시가 매시간 라이브 지수 조회를 냈고(08-02 실측 15회/일) 실패 백오프가 없어
차단 상태에서 계속 재시도했다. 역할을 분리한다: 체인(하루 1회)은 항상 라이브로
조회하고 캐시에 쓰고, 감시는 cached_eltd 로 캐시만 읽는다.

negative 캐시는 넣지 않는다 — llm_runner 가 fail-closed 라 일시 오류를 캐시하면
그날 저녁 체인이 통째로 skip 된다. 캐시 미갱신은 곧 체인 미발화이므로 eltd_stale
알림으로 처리해 결측 감시 기능을 유지한다(공휴일에도 체인은 발화하므로 오탐 없음).

캐시를 셸이 아니라 trading_calendar 에 둔 이유: 셸 eltd() 는 매번 새 프로세스라
in-memory 캐시가 무의미하고, Python 호출부(llm_runner·weekly)도 함께 덮어야 한다."
```

---

### Task 3: 시도 상한 — 전 종목 스윕 폭주 차단

**문제:** `RunAtLoad=true`(`install.sh:55`)로 launchctl 재로드·로그인 시 체인이 즉발한다. `evening_chain.sh:31` 의 멱등 조건(지표 행수 < 2200)은 데이터가 불완전하면 **매 발화마다 전 종목 스윕**을 시작한다(08-02 2회·08-03 1회, 각 2,549종목 × 2호출). `monthly_chain.sh:17` 의 `universe` 도 같은 결함이 있다 — 성공 이력 기준 멱등이라 **실패한 달에는 발화마다 재시도**한다(08-01 06:36 실제 실패).

**해법:** plist 를 건드리지 않고 래퍼에서 파이프라인별 시도 횟수·간격을 제한한다. 이력은 `pipeline_runs` 로 판단한다 — `run_tracking` 이 스윕 **시작 전**에 행을 커밋하므로(`db/runs.py:55-56`) 진행 중 실행도 보인다.

**주말 catch-up 은 막지 않는다.** 금요일 결측을 토요일에 만회하는 것은 정당하고, 문제는 요일이 아니라 하루 여러 회였다. 요일을 막으면 금요일 저녁 결측이 영구 복구 불가가 된다.

**Files:**
- Modify: `scripts/launchd/lib_guards.sh` (`attempt_allowed()` 추가)
- Modify: `scripts/launchd/evening_chain.sh:31-36`
- Modify: `scripts/launchd/monthly_chain.sh:13-18`
- Test: `tests/test_launchd_guards.py` (신규)

**Interfaces:**
- Consumes: Task 2 의 `KR_DB`, `db_query`, `ATTEMPT_MAX_DEFAULT`, `ATTEMPT_GAP_DEFAULT`
- Produces: `attempt_allowed <pipeline> [max] [gap_sec]` — rc=0 허용 / rc=1 상한·백오프. **DB 실패 시 `exit 1`**(기존 `has_success_since` 관례와 일치 — 인프라 장애를 rate-limit 판단으로 은폐하지 않는다)

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_launchd_guards.py` 생성:

```python
"""launchd 래퍼 가드(lib_guards.sh) 검증 — bash 서브프로세스로 실행.

#88: KRX 접촉 빈도 제한이 회귀하지 않도록 고정한다. pykrx 는 호출하지 않는다.
"""
import os
import subprocess
from pathlib import Path
from urllib.parse import urlparse

import psycopg
import pytest

REPO = Path(__file__).parent.parent
GUARDS = REPO / "scripts" / "launchd" / "lib_guards.sh"
TEST_DSN = os.environ.get("TEST_DATABASE_URL", "")


def _pg_env() -> dict:
    """TEST_DATABASE_URL 을 psql 이 쓰는 PG* 환경변수로 분해.

    KR_DB 에 dbname 만 넘기면 host/port/user 가 빠져 엉뚱한 DB 에 붙을 수 있다.
    """
    u = urlparse(TEST_DSN)
    env = {}
    if u.hostname:
        env["PGHOST"] = u.hostname
    if u.port:
        env["PGPORT"] = str(u.port)
    if u.username:
        env["PGUSER"] = u.username
    if u.password:
        env["PGPASSWORD"] = u.password
    return env


def run_guard(script: str, env_extra: dict | None = None) -> subprocess.CompletedProcess:
    """lib_guards.sh 를 source 한 뒤 script 실행. HOME 은 실제 값을 유지한다(uv 캐시)."""
    env = dict(os.environ)
    env.update({"PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin", "KR_REPO": str(REPO)})
    env.update(_pg_env())
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        ["bash", "-c", f"source {GUARDS}\n{script}"],
        capture_output=True, text=True, env=env,
    )


@pytest.fixture
def runs_conn():
    """kr_test 의 pipeline_runs 에서 이 테스트가 쓰는 파이프라인 행만 정리."""
    if not TEST_DSN:
        pytest.skip("TEST_DATABASE_URL 미설정")
    name = urlparse(TEST_DSN).path.lstrip("/")
    with psycopg.connect(TEST_DSN) as conn:
        conn.execute("DELETE FROM pipeline_runs WHERE pipeline='guardtest'")
        conn.commit()
        conn.dbname_for_shell = name  # type: ignore[attr-defined]
        yield conn
        conn.execute("DELETE FROM pipeline_runs WHERE pipeline='guardtest'")
        conn.commit()


def _insert_at(conn, offset_sql: str, status: str = "failed"):
    """당일 창(date_trunc('day', now()))에 앵커해서 삽입.

    ⚠️ `now() - N hours` 로 시드하면 안 된다. 게이트 창이 당일 00시 기준이라
    자정 근처에서 시드가 창을 벗어나 테스트가 시각 의존 flaky 가 된다
    (예: hours_ago=10 은 00~10시 실행 시 어제로 넘어가 COUNT 가 줄어든다).
    """
    conn.execute(
        "INSERT INTO pipeline_runs (pipeline, mode, started_at, status) "
        f"VALUES ('guardtest','incremental', {offset_sql}, %s)",
        (status,),
    )
    conn.commit()


_DAY_START = "date_trunc('day', now())"
# 당일 창을 벗어나지 않는 '방금' — 자정 직후에도 안전
_RECENT = "GREATEST(date_trunc('day', now()), now() - interval '1 hour')"


def _kr_db(conn) -> dict:
    return {"KR_DB": conn.dbname_for_shell}


def test_attempt_allowed_when_no_history(runs_conn):
    r = run_guard("attempt_allowed guardtest && echo ALLOW || echo BLOCK", _kr_db(runs_conn))
    assert "ALLOW" in r.stdout, f"stdout={r.stdout!r} stderr={r.stderr!r}"


def test_attempt_blocked_within_gap(runs_conn):
    """직전 시도가 1시간 이내면 간격 백오프로 차단(어느 시각에 돌려도 성립)."""
    _insert_at(runs_conn, _RECENT)
    env = _kr_db(runs_conn) | {"ATTEMPT_GAP_DEFAULT": "14400", "ATTEMPT_MAX_DEFAULT": "9"}
    r = run_guard("attempt_allowed guardtest && echo ALLOW || echo BLOCK", env)
    assert "BLOCK" in r.stdout, f"stdout={r.stdout!r} stderr={r.stderr!r}"


def test_attempt_allowed_below_cap_when_gap_disabled(runs_conn):
    """상한 미달 + 간격 제한 없음이면 허용 — 상한 카운트 경로만 검증."""
    _insert_at(runs_conn, _DAY_START)
    env = _kr_db(runs_conn) | {"ATTEMPT_GAP_DEFAULT": "0", "ATTEMPT_MAX_DEFAULT": "2"}
    r = run_guard("attempt_allowed guardtest && echo ALLOW || echo BLOCK", env)
    assert "ALLOW" in r.stdout, f"stdout={r.stdout!r} stderr={r.stderr!r}"


def test_attempt_blocked_at_daily_cap(runs_conn):
    """상한 도달이면 간격과 무관하게 차단. 두 시드 모두 당일 창 안이라 시각 무관."""
    _insert_at(runs_conn, _DAY_START)
    _insert_at(runs_conn, f"{_DAY_START} + interval '1 minute'")
    env = _kr_db(runs_conn) | {"ATTEMPT_GAP_DEFAULT": "0", "ATTEMPT_MAX_DEFAULT": "2"}
    r = run_guard("attempt_allowed guardtest && echo ALLOW || echo BLOCK", env)
    assert "BLOCK" in r.stdout, f"stdout={r.stdout!r} stderr={r.stderr!r}"


def test_attempt_db_failure_exits_nonzero(runs_conn):
    """DB 장애는 상한 도달과 다르게 취급한다 — fail-closed 중단."""
    env = _kr_db(runs_conn) | {"KR_DB": "kr_definitely_no_such_db"}
    r = run_guard("attempt_allowed guardtest; echo RC=$?", env)
    assert "RC=" not in r.stdout, "DB 실패인데 계속 진행했다(exit 되지 않음)"
    assert r.returncode != 0


def test_evening_chain_gates_data_chain():
    text = (GUARDS.parent / "evening_chain.sh").read_text()
    assert text.find("attempt_allowed data_daily") != -1, "게이트 없음"
    assert text.find("attempt_allowed data_daily") < text.find("--chain=daily"), "게이트가 실행 뒤"


def test_monthly_chain_gates_universe():
    text = (GUARDS.parent / "monthly_chain.sh").read_text()
    assert text.find("attempt_allowed universe") != -1, "universe 게이트 없음"
    assert text.find("attempt_allowed universe") < text.find("kr_pipeline.universe"), "게이트가 실행 뒤"


def test_weekend_chain_gates_weekly():
    text = (GUARDS.parent / "weekend_chain.sh").read_text()
    assert "attempt_allowed data_weekly" in text, "data_weekly 게이트 없음"
    assert text.find("attempt_allowed data_weekly") < text.find("--chain=weekly"), "게이트가 실행 뒤"


def test_eltd_cached_latest_never_runs_python():
    """감시 경로가 Python 을 태우면 pykrx import 로 KRX 로그인 POST 가 나간다.

    trading_calendar:10 → ohlcv/fetch.py:9 → pykrx → webio.py:12 build_krx_session().
    실측: `KRX_ID= uv run python -c "import kr_pipeline.common.trading_calendar"` 가
    "KRX 로그인 실패: ... 환경 변수가 설정되지 않았습니다" 를 출력 = build_krx_session 실행됨.
    자격증명이 살아 있는 운영 환경에서는 그것이 곧 로그인 요청이다.
    """
    r = run_guard("declare -f eltd_cached_latest")
    body = r.stdout
    assert body.strip(), f"함수가 정의되지 않았다 stderr={r.stderr!r}"
    for forbidden in ("uv run", "python", "pykrx"):
        assert forbidden not in body, f"eltd_cached_latest 가 {forbidden!r} 를 호출한다 — KRX 접촉 위험"


def test_eltd_cached_latest_reports_value_and_age(tmp_path):
    """최신 1건과 나이를 반환한다 — 정확일치 키가 아니어야 한다(D+1 오전 커버리지)."""
    cache = tmp_path / "eltd.cache"
    cache.write_text("2026-06-09:post|2026-06-09\n2026-06-10:post|2026-06-10\n")
    r = run_guard("eltd_cached_latest", {"ELTD_CACHE": str(cache)})
    out = r.stdout.split()
    assert out and out[0] == "2026-06-10", f"stdout={r.stdout!r} stderr={r.stderr!r}"
    assert int(out[1]) >= 0


def test_eltd_cached_latest_rejects_corrupt(tmp_path):
    """손상된 캐시는 미스로 취급한다(잘못된 날짜를 감시에 넘기지 않는다)."""
    cache = tmp_path / "eltd.cache"
    cache.write_bytes(b"\xff\xfe garbage\n")
    r = run_guard("eltd_cached_latest && echo HIT || echo MISS", {"ELTD_CACHE": str(cache)})
    assert "MISS" in r.stdout, f"stdout={r.stdout!r}"
```

- [ ] **Step 2: 테스트 실패 확인**

```bash
uv run pytest tests/test_launchd_guards.py -v
```

Expected: 7개 FAIL (`attempt_allowed: command not found`, 게이트 없음).

- [ ] **Step 3: `attempt_allowed()` 구현**

`lib_guards.sh` 의 `has_running_recent`(87행) 아래에 추가:

```bash
# 대량 외부 호출 파이프라인의 시도 허용 판정 — #88 재탐지 방지.
# 사용: attempt_allowed <pipeline> [max_per_day] [min_gap_sec]
# 이력은 pipeline_runs(성공·실패 모두 기록, run_tracking 이 시작 시 커밋)로 판단.
# rc=0 허용 / rc=1 상한·백오프. DB 실패는 exit 1(기존 has_success_since 관례).
attempt_allowed() {
  local pl="$1" mx="${2:-$ATTEMPT_MAX_DEFAULT}" gp="${3:-$ATTEMPT_GAP_DEFAULT}" row n age
  row=$(db_query "SELECT COUNT(*)||' '||COALESCE(FLOOR(EXTRACT(EPOCH FROM (now() - MAX(started_at))))::bigint, 999999) FROM pipeline_runs WHERE pipeline='$pl' AND started_at >= date_trunc('day', now())") \
    || { log "시도 이력 조회 불가(DB) — fail-closed 중단"; exit 1; }
  n=${row%% *}; age=${row##* }
  if [ "$n" -ge "$mx" ]; then
    log "$pl 일일 시도 상한 도달($n/$mx) — skip"; return 1
  fi
  if [ "$n" -gt 0 ] && [ "$age" -lt "$gp" ]; then
    log "$pl 직전 시도 후 ${age}s < ${gp}s — skip(백오프)"; return 1
  fi
  return 0
}
```

- [ ] **Step 4: `evening_chain.sh` 에 게이트 적용**

31-36행을 교체:

```bash
if [ "$NIND" -lt 2200 ]; then
  if ! attempt_allowed data_daily; then
    # 결정 2: 웹 UI(/runner) 수동 실행도 같은 pipeline_runs 행을 남겨 이 상한을 공유한다.
    # 아침에 수동 2회를 돌리면 그날 저녁 정규 실행이 여기서 멈추므로 이유를 명확히 남긴다.
    log "데이터 체인 필요($ELTD 지표 $NIND행 < 2200)하나 시도 상한/백오프 — skip (웹 UI 수동 실행도 이 상한을 소모함: pipeline_runs 의 오늘 data_daily 행 확인)"
    exit 0
  fi
  log "데이터 체인 실행 (ELTD=$ELTD 지표 $NIND행 < 2200)"
  uv run python -m kr_pipeline.pipeline --chain=daily || { log "데이터 체인 실패 — 후속 중단"; exit 1; }
else
  log "데이터 몫 완료($ELTD 지표 $NIND행) — skip"
fi
```

**`exit 0` 인 이유:** `exit 1` 이면 launchd 가 실패로 기록하고 감시의 `failed.*` 알림이
발화마다 울린다. 결측 자체는 `miss.data.*` 가 이미 담당한다.

**후속 단계(포지션 평가·시장지표·LLM)를 함께 skip 하는 것의 검증:** 1회차 검토에서
"포지션 평가는 소급 불가 항목이니 계속 돌려야 한다"는 지적이 있었으나, 코드를 확인한
결과 **실효 차이가 없다.** `run_daily_eval` 은 `as_of = MAX(daily_prices.date)` 를 쓰고
`(position_id, eval_date)` 로 멱등하다(`trade_management/runner.py:35-45`). 데이터가
07-31 에 멈춘 상태에서 돌리면 07-31 을 재평가하는 것이고, 이미 평가됐으면 no-op 이다.
즉 "오늘 몫"을 잃는 게 아니다. 반면 계속 진행하면 LLM 단계의 `assert_data_fresh` 가
ELTD 라이브 조회를 1회 더 쓴다(2 요청). 따라서 `exit 0` 으로 멈추는 편이 접촉이 적고
효과는 같다. (데이터가 완전한 정상적인 날에는 `NIND >= 2200` 이라 이 게이트를 **통과조차
하지 않으므로** 정상 운영에는 영향이 없다.)

- [ ] **Step 5: `monthly_chain.sh` 에 게이트 적용**

13-18행을 교체:

```bash
if has_success_since universe "$MONTH_START"; then  # universe 는 단일 mode
  log "universe 이번 달 몫 완료 — skip"
elif ! attempt_allowed universe; then
  log "universe 미완료이나 시도 상한/백오프 — skip"
else
  log "universe 실행"
  uv run python -m kr_pipeline.universe || { log "universe 실패 — 매핑 단계 중단(순서 보전)"; exit 1; }
fi
```

- [ ] **Step 5b: `weekend_chain.sh` 에도 게이트 적용**

`weekend_chain.sh:24-29` 를 교체:

```bash
if has_success_since data_weekly "$ANCHOR" incremental; then
  log "주봉 데이터 몫 완료 — skip"
elif has_running_recent data_weekly 6; then
  log "data_weekly running 중 — 이중 스윕 방지 skip"
elif ! attempt_allowed data_weekly 1 43200; then
  log "주봉 데이터 미완료이나 시도 상한/백오프 — skip"
else
  log "주봉 데이터 체인 실행"
  uv run python -m kr_pipeline.pipeline --chain=weekly || { log "주봉 체인 실패 — 후속 중단"; exit 1; }
fi
```

**근거:** 기존 멱등은 **성공 기준**이라 실패하면 토 03:00·월 07:00·모든 RunAtLoad 발화마다
전량 재스윕한다. `has_running_recent` 가 없는 것도 실측으로 확인된 구멍이다 — LLM 단계
(`weekend_chain.sh:41`)에는 있는데 주봉 단계에는 없어서, `08-01 16:30 data_weekly running`
(좌초, 완료 안 됨) → `08-03 07:06 data_weekly success`(월 catch-up 이 전량 재스윕) 이 실제로 발생했다. 대량 조회 자체는 Naver 경로(`fetch_adj_only` → `adjusted=True` →
pykrx `stock_api.py:236-237` 의 `naver` 분기, 실측: run 1219 가 KRX 차단 중에도
2,549종목 `failures:0`)지만, `weekly/modes.py:157` 의 ELTD 는 KRX 이고 Naver 를
2,549× 반복 두드리는 것도 자체 위험이다. 주 1회면 충분하므로 `1 43200`(12시간).

- [ ] **Step 5c: ELTD 1회당 KRX 요청을 6 → 2 로 (독립 즉효 완화)**

`kr_pipeline/ohlcv/fetch.py:101-105` 의 호출에 `name_display=False` 를 추가
(`name_display` 는 `get_index_ohlcv` 의 정식 optional 인자 — pykrx `stock_api.py:1332` 확인):

```python
    df = stock.get_index_ohlcv(
        start.strftime("%Y%m%d"),
        end.strftime("%Y%m%d"),
        index_code,
        name_display=False,   # #88: True(기본) 면 IndexTicker() 가 시장 4종 마스터를 추가 fetch
    )
```

**근거:** `stock.get_index_ohlcv` 는 `name_display=True` 가 기본인 유일한 API
(pykrx `stock_api.py:1422`)이고, 그러면 `get_index_ticker_name` → `IndexTicker()` 가
시장 4종 마스터를 **추가로 가져온다**(`ticker.py:78-89`). 즉 ELTD 1회 =
로그인 1 + 지수 OHLCV 1 + 마스터 4 = **6 요청**이었다.
우리 코드는 컬럼명 메타데이터를 쓰지 않는다(`fetch.py:44-46` 주석이 명시하고,
`transform.to_index_rows` 는 `date/open/high/low/close/volume/value` 만 읽는다).

기존 `IndexTicker.get_name` 안전 패치(`fetch.py:45-57`)는 인스턴스화 자체를 막지 못하므로
이 한 줄이 실제 완화 수단이다. 회귀 확인:

```bash
uv run pytest tests/test_ohlcv_fetch.py tests/test_ohlcv_modes.py tests/test_trading_calendar.py -v
```

Expected: 0 failed. (테스트는 `fetch_index`/`stock.get_market_ohlcv` 를 모킹하므로
시그니처 변경 영향 없음 — 실패하면 모킹이 인자를 단정하고 있다는 뜻이니 그 단정을 갱신.)

- [ ] **Step 6: 테스트 통과 확인**

```bash
uv run pytest tests/test_launchd_guards.py -v
for f in scripts/launchd/*.sh; do bash -n "$f" || echo "문법 오류: $f"; done; echo "문법 검사 완료"
```

Expected: 8 passed(weekend 게이트 테스트 포함), 문법 오류 없음.

- [ ] **Step 7: 전체 suite 회귀 확인**

```bash
pgrep -f pytest; uv run pytest tests/ 2>&1 | tail -20
```

Expected: 0 failed, 1 deselected.

- [ ] **Step 8: 커밋**

```bash
git add scripts/launchd/lib_guards.sh scripts/launchd/evening_chain.sh \
        scripts/launchd/monthly_chain.sh tests/test_launchd_guards.py
git commit -m "fix(#92): 대량 호출 파이프라인 시도 상한 — 하루 2회 + 4시간 간격

RunAtLoad/catch-up 이 하루 여러 번 전 종목 스윕(2,549종목 × 2호출)을 발화시켜
차단을 유발한 것으로 의심(08-02 2회·08-03 1회 실측). monthly 의 universe 도
성공 이력 기준 멱등이라 실패한 달에는 발화마다 재시도했다(08-01 06:36 실패).

plist 는 건드리지 않는다(install.sh 재실행 시 crontab 재변경·즉발 위험).
이력은 pipeline_runs 로 판단 — run_tracking 이 스윕 시작 전에 커밋하므로
진행 중 실행도 보인다. DB 실패는 상한 도달과 구분해 exit 1(기존 관례)."
```

---

### Task 4: 재개 탐침 + 재개 절차

**Files:**
- Create: `scripts/launchd/probe_krx.sh`

**Interfaces:**
- Produces: `probe_krx.sh` — 종목 1개 조회. rc=0 정상 / rc=1 차단 지속. DB 미기록.

- [ ] **Step 1: 탐침 스크립트 작성**

`scripts/launchd/probe_krx.sh` 생성:

```bash
#!/bin/bash
# probe_krx.sh — KRX 차단 해제 확인용 최소 탐침 (#88).
# 전 종목 스윕으로 확인하면 그 자체가 재탐지 유발 행위다. 종목 1개만 조회한다.
# DB 를 쓰지 않고 판정만 출력한다. rc=0 정상 / rc=1 차단 지속.
#
# 사용: scripts/launchd/probe_krx.sh
# 주의: 하루 1회를 넘기지 말 것. 차단 대기 중에는 실행하지 말 것.
set -u
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO" || exit 1
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"

echo "[probe] 005930 최근 5일 원주가 조회 — KRX 접촉 = 로그인 1회 + OHLCV 1~3회(_fetch_one 은 @with_retry(attempts=3))"
OUT=$(uv run python -c "
from kr_pipeline.common import config  # noqa: F401 — .env 로드(KRX 인증)
from datetime import date, timedelta
from kr_pipeline.ohlcv.fetch import _fetch_one
end = date.today(); start = end - timedelta(days=5)
df = _fetch_one('005930', start, end, adjusted=False)
print('ROWS', 0 if df is None or df.empty else len(df))
" 2>&1)
rc=$?
echo "$OUT" | grep -v '로그인 ID'   # pykrx auth.py:189 가 계정 ID 를 stdout 에 print — 로그 평문 기록 차단
ROWS=$(echo "$OUT" | grep -E '^ROWS ' | awk '{print $2}')
if [ "$rc" -ne 0 ] || [ -z "$ROWS" ] || [ "$ROWS" = "0" ]; then
  echo "[probe] 판정: 차단 지속(빈 응답 또는 오류) — 재개하지 말 것"
  exit 1
fi
echo "[probe] 판정: 정상($ROWS행) — 단계적 재개 가능"
exit 0
```

- [ ] **Step 2: 실행 권한·문법 확인 (실행은 하지 않는다)**

```bash
chmod +x scripts/launchd/probe_krx.sh
bash -n scripts/launchd/probe_krx.sh && echo "문법 OK"
```

- [ ] **Step 3: README 갱신** (2회차 검토 F7)

`README.md:57-68` 의 launchd 잡 표와 "공통 가드" 목록에 이번 변경이 반영돼 있지 않고,
`:54` 는 `install.sh` 를 정상 갱신 경로로 안내한다. 다음 사람이 그냥 재실행하면
crontab 이 다시 바뀌고 RunAtLoad 즉발이 발생한다. 두 줄을 추가한다.

- 공통 가드 목록에: `ELTD 파일 캐시(감시는 캐시만 읽어 KRX 접촉 0)`, `시도 상한(하루 2회·6시간 간격)`
- `install.sh` 안내 옆에: `⚠️ KRX 차단 대응/재개 기간에는 재실행 금지 — 재개는 launchctl bootstrap 개별 4회(계획서 참조)`

- [ ] **Step 4: 커밋**

```bash
git add scripts/launchd/probe_krx.sh README.md docs/superpowers/plans/2026-08-03-krx-contact-hardening.md
git commit -m "feat(#92): KRX 차단 해제 탐침 + 재개 절차 기록

해제 확인을 전 종목 스윕으로 하면 재탐지를 유발한다. 종목 1개만 조회해
판정하는 최소 탐침을 추가하고 단계적 재개 순서를 계획서에 고정한다."
```

---

## 재개 절차 (2026-08-06 이후)

Task 1~4 완료가 **선행 조건**이다.

- [ ] **1. 무접촉 확인**

```bash
launchctl list | grep krbyclaude          # morning-corp, bt-c-watchdog 2개만
psql -d kr_pipeline -Atc "SELECT COUNT(*) FROM pipeline_runs WHERE pipeline IN ('ohlcv','data_daily','universe') AND started_at > '2026-08-03 15:00'"
```

Expected: 잡 2개, 실행 0건.

- [ ] **2. 탐침 1회** — `scripts/launchd/probe_krx.sh`. **rc=1 이면 중단하고 3일 더 대기.**

- [ ] **3. 감시부터 재개** — 캐시 read-only 라 KRX 접촉이 0이어야 한다

⚠️ **로그 grep 으로 검증하면 안 된다.** `grep -ac "KRX 로그인" launchd-pipeline-watch.log` 는
**구조적으로 항상 0** 이다(2회차 검토) — pykrx 의 "KRX 로그인 시도..." 는 `uv run python` 의
stdout 으로 나오고, 함수가 그것을 `grep -E '^[0-9]{4}-...'` 로 걸러 **반환값으로 캡처**하며
stderr 는 `2>/dev/null` 로 버린다. 즉 실패를 표현할 수 없는 게이트였다.

**대신 함수 본문과 실제 실행을 직접 본다:**

```bash
# ① 함수가 Python 을 아예 안 태우는지 (실패 가능한 검증)
bash -c 'source scripts/launchd/lib_guards.sh; declare -f eltd_cached_latest' \
  | grep -cE 'uv run|python|pykrx'          # 0 이어야 함

# ② 감시를 손으로 1회 돌려 접촉이 없는지 (파이프로 가려지지 않는 경로로 관찰)
KR_REPO=$PWD scripts/launchd/watch_pipelines.sh 2>&1 | grep -i 'KRX 로그인\|pykrx' \
  && echo "접촉 있음 — 재개 중단" || echo "접촉 없음"

# ③ 위 둘이 통과하면 잡을 올린다
launchctl bootstrap "gui/$(id -u)" ~/Library/LaunchAgents/com.krbyclaude.pipeline-watch.plist
```

Expected: ① = `0`, ② = `접촉 없음`. 하나라도 어긋나면 bootstrap 하지 않는다.

**참고:** 4단계 전까지는 캐시가 갱신되지 않는다. `eltd_stale` 알림은 체인 잡이 **로드돼 있을
때만** 울리도록 게이트를 넣었으므로(Task 2 Step 6) 이 구간에서는 조용한 것이 정상이다.

- [ ] **4. 저녁 체인 재개 — 반드시 평일 09:00~16:59 에 bootstrap 한다**

`RunAtLoad=true` 라 bootstrap 즉시 발화하고, 시도 이력이 0이면 게이트가 ALLOW 하므로
**해제 직후 2,549종목 스윕이 곧바로 시작된다**. 장중에 bootstrap 하면 `intraday_lock`
(`lib_guards.sh:37-42`, 평일 09~17시 차단)이 `evening_chain.sh:11-14` 에서 즉발을 흡수해
`exit 0` 으로 끝나고, **첫 실제 실행이 18:30 정규 슬롯**이 된다.

```bash
# 평일 09:00~16:59 에 실행할 것 (장중 자물쇠가 즉발을 흡수)
launchctl bootstrap "gui/$(id -u)" ~/Library/LaunchAgents/com.krbyclaude.evening-chain.plist
sleep 20; tail -5 ~/.kr-by-claude/launchd-evening-chain.log   # "장중 — skip" 이어야 한다
# 이후 18:30 정규 발화 결과를 확인
sleep 60; tail -20 ~/.kr-by-claude/launchd-evening-chain.log
psql -d kr_pipeline -Atc "SELECT COUNT(*) FROM pipeline_runs WHERE pipeline='data_daily' AND started_at >= date_trunc('day', now())"
psql -d kr_pipeline -Atc "SELECT date, COUNT(*) FROM daily_prices WHERE date >= current_date - 5 GROUP BY date ORDER BY date"
```

Expected: `data_daily` 당일 1건, `empty_fetch` 경고 없음, 일봉 ~2,549행.

- [ ] **5. 나머지 재개**

```bash
for j in weekend-chain monthly-chain; do
  launchctl bootstrap "gui/$(id -u)" ~/Library/LaunchAgents/com.krbyclaude.$j.plist
done
launchctl list | grep krbyclaude   # 6개
```

- [ ] **6. 오염 데이터 복구(별건)** — 07-31 일봉이 47%(1,197/2,549)이고 그 위에서 주봉·주간지표가 재계산되어 오염됐다. 일봉 복구 후 `--chain=weekly` 수동 1회 필요. 본 계획 범위 밖.

---

## Self-Review

**1. 스펙 커버리지**

| 요구 | 담당 | 결과 |
|---|---|---|
| 시간당 ELTD 조회 제거 | Task 2 | 감시 접촉 **0회** (캐시 read-only) |
| RunAtLoad 즉발 차단 | Task 3 | plist 미변경, 래퍼 상한으로 달성 |
| catch-up 하루 1회 상한 | Task 3 | 하루 2회 + 4시간 간격 (정규 1 + 만회 1 허용) |
| 주말 전 종목 스윕 억제 | Task 3 | **요구를 수정.** 요일 차단이 아니라 횟수 상한 — 요일을 막으면 금요일 결측이 영구 복구 불가 |
| pytest KRX 로그인 차단 | Task 1 | 자격증명 무력화(빈 문자열) + `krx` 마커 |
| Python 호출부 커버 | Task 2 | 캐시를 `trading_calendar` 에 두어 `llm_runner`·`weekly` 도 캐시 write 경유 |
| monthly universe 커버 | Task 3 | `attempt_allowed universe` |

**2. 플레이스홀더 스캔** — TBD/TODO 없음. 모든 코드 단계에 실제 코드가 있다.

**3. 타입·이름 일관성** — `eltd_cache_path`/`cache_key`/`cached_eltd`/`_write_cache`(Python), `eltd`/`eltd_cached`/`attempt_allowed`(셸), env `ELTD_CACHE`/`KR_DB`/`ATTEMPT_MAX_DEFAULT`/`ATTEMPT_GAP_DEFAULT`/`KR_ALLOW_KRX` 가 정의·테스트·문서에서 일치. `run_guard`·`_pg_env`·`_kr_db` 는 Task 3 테스트 파일 내에서 정의·사용.

**4. 잔여 리스크 — 2회차 검토에서 전부 실측 판정됨**

| 항목 | 판정 | 조치 |
|---|---|---|
| `source` 된 함수의 `exit` 가 `bash -c` 전체를 죽이는가 | ✅ **의도대로 동작** (실측: `RC=` 미출력, rc=1) | 단정 강화 — 앞에 `echo BEFORE` 를 넣어 부트스트랩 실패와 구분 |
| psycopg3 커넥션 동적 속성 | ✅ 동작(`__slots__` 없음, psycopg 3.3.4) | 그래도 불필요 → 모듈 상수 `KR_TEST_DB` 로 단순화 |
| `monkeypatch.setattr(Path,"mkdir")` | ❌ 교차 누수는 없으나 **같은 테스트 내 모든 mkdir 을 깨뜨림** | `chmod 0o500` 실제 디렉터리로 교체 (반영) |
| autouse `tmp_path` 스코프 충돌 | ✅ 없음 (세션 autouse 는 `_setup_schema` 하나, 방향이 반대라 ScopeMismatch 불가). 오버헤드 +0.7ms/test | 유지 |
| `row%% *` 파싱 | ✅ `COUNT` 집계라 1줄 보장 | 값싼 방어 `row=${row%%$'\n'*}` 추가 권장 — `db_query` 가 `2>&1` 로 stderr 를 합치는 **기존 결함** 때문에 NOTICE 가 섞일 수 있음 |

**5. 결정 완료 (2026-08-03, 사용자 승인 — 전부 권고안 채택)**

| # | 결정 | 반영 위치 |
|---|---|---|
| 1 | `assert_data_fresh` 가 **캐시를 먼저 읽는다**(미스 시 라이브 폴백) | Task 2 Step 3b |
| 2 | 웹 UI 수동 실행 구분은 **코드로 하지 않고 문서·로그로** 처리 | Task 3 Step 4 로그 문구 + 재개 절차 |
| 3 | 이슈 소유 = **[#92](https://github.com/itsmehank/kr-by-claude/issues/92)** 생성 완료. #88 에는 정지·재개 코멘트만 남김 | 커밋 메시지 전부 `#92` 로 변경 |
| 4 | ELTD 산출 실패 시 **`exit 0`** (중단은 유지, launchd failed 소음만 회피) | Task 2 Step 6b |

<details>
<summary>결정 전 원문 (판단 근거 보존)</summary>

- **`llm_runner` 의 `assert_data_fresh` 가 캐시를 읽을지** — 저녁마다 라이브 ELTD 가 2회
  (`evening_chain.sh:17` + `llm_runner/__main__.py:96`) 나간다. 캐시 키가 (날짜, 마감버퍼 구간)이므로
  **같은 키의 캐시값은 라이브값과 정의상 동일**하고, 따라서 캐시를 읽어도 `StaleDataError` 판정력은
  줄지 않는다. 캐시 미스 시 라이브 폴백을 두면 fail-closed 도 유지된다. 채택 시 저녁 접촉 2요청 절감.
- **`data_daily` 카운터를 웹 UI 수동 실행과 공유하는 문제** — `pipeline_specs` 가 `data-daily`·
  `universe`·`--chain=weekly` 를 `/runner` UI 에 노출하고 셸 게이트를 타지 않는다. 아침에 수동으로
  2회 돌리면 그날 저녁 정규 체인이 조용히 skip 된다. 최소한 재개 기간 UI 실행 금지를 명시하고,
  근본적으로는 래퍼가 `KR_RUN_SOURCE=launchd` 를 주입해 카운터를 분리하는 방안 검토.
- **이슈 소유** — 커밋을 전부 `fix(#92)` 로 달았으나 #88 은 "저녁 크론 결측(Mac 수면)"이고
  본문에 KRX 접촉 총량 얘기가 없다. 이 주제의 상위 이슈는 **#91**(KDM 스크레이핑 차단 리스크)이다.
  신규 이슈 또는 #91 하위로 소유를 옮기고, #88 에는 "4잡 bootout, 재개 08-06" 코멘트만 남기는 것을 권고.
- **`evening_chain.sh:17` 의 라이브 `eltd()` 는 상한 밖** — 차단 상태에선 실패 → `exit 1` →
  launchd failed → 감시 `failed.*` 알림이 발화마다. 접촉량은 작으나 `exit 0` 으로 낮추는 것 검토
  (fail-closed 유지, launchd failed 만 회피).

</details>

**6. 재개 기간 추가 수칙 (결정 2)**

재개가 완료될 때까지 **웹 UI `/runner` 의 파이프라인 실행 버튼을 누르지 않는다.**
`data-daily`·`universe`·`--chain=weekly` 는 셸 게이트를 타지 않고 같은 `pipeline_runs`
행을 남겨 자동 실행 예산을 소모한다. 눌렀다면 그날 저녁 자동 실행이 건너뛰어질 수 있으므로
로그(`launchd-evening-chain.log`)에서 "시도 상한/백오프 — skip" 문구를 확인한다.

---

## 3차 검토(구현 후 위임 검토) 반영 — 확정 수정안 (2026-08-04, 사용자 승인)

구현 커밋 4개 이후 위임 검토가 치명 2건을 추가 발견했고, 실측으로 확정했다.
아래가 확정된 수정 스펙이다.

### H-1 (치명) — 감시가 "어제 목표일"로 오늘을 검사해 저녁 1회 결측을 놓친다

**실측 재현**: 캐시 = `2026-08-03:post|2026-08-03`(월 18:30 기록), 화 21:00 감시 →
나이 26.5h < 30h → HIT 분기, `E=어제`. 어제 데이터는 있으므로 miss.* 3종 전부 무발화.
수요일 체인이 정상이면 화요일 결측은 영구 미탐지. `ELTD_STALE_SEC=108000` 의
주석 근거("금 저녁→월 저녁 간격")도 틀렸다(실제 72h).

**확정 수정 — 두 신호 분리 (KRX 접촉 0 유지)**:

- **miss.\* 판정은 캐시가 "오늘 17:00 이후"에 쓰였을 때만** 수행한다. 그때만 캐시 값이
  오늘의 목표일이다. 판정식(macOS 실측 검증):
  ```bash
  TODAY17=$(date -j -f "%Y-%m-%d %H:%M:%S" "$(date +%F) 17:00:00" +%s)
  MT=$(( $(date +%s) - AGE ))          # eltd_cached_latest 의 age 로부터
  [ "$MT" -ge "$TODAY17" ]             # → miss.* 판정 / 아니면 stale 분기
  ```
- **stale 분기** = 평일 && (HOUR≥21 **|| mtime < 어제 17:00**) && evening-chain 잡 로드됨
  → `eltd_stale` 알림("저녁 체인 미실행 의심"). 기존 30h 지연(최초 신호 50.5h 후)을
  당일 21시로 앞당기고, **`mtime < 어제 17:00` 조건이 "다음날 아침" 탐지를 복원한다**
  — 이 조건이 없으면 "화 저녁 통째 수면(감시도 못 돎) → 수 08:00 기상" 시나리오에서
  구 코드는 아침에 miss.data 를 울렸지만 확정안 초안은 21시까지 침묵했고, 수요일 체인이
  성공하면 화요일 daily-eval(소급 불가) 소실이 영구 무알림이 됐다(1회 검토에서 발견).
  정상일 아침(mtime=어제 18:30 ≥ 어제 17:00)은 침묵 — 오탐 없음(실측 검증).
- `ELTD_STALE_SEC` 상수는 **폐기**한다(어떤 시나리오도 근거로 갖지 못했다).
- 판정 게이트를 lib_guards 의 함수 `eltd_cache_fresh_today()` 로 추출해 단위 테스트한다
  (watch 스크립트 본문은 top-level 실행이라 직접 테스트가 어렵다).

**시나리오 검증표** (수정 후):

| 시나리오 | 캐시 mtime | 감시 동작 | 판정 |
|---|---|---|---|
| 정상일 21:00 | 오늘 18:30 | fresh → E=오늘 → miss.* 정밀 판정 | ✓ 기존과 동일 |
| 저녁 통째 결측, 당일 21:00 | 어제 18:30 | stale → **당일 알림** | ✓ 구 라이브 방식과 동일 시점 |
| KRX 차단으로 eltd() 실패(exit 0) | 갱신 안 됨 | stale → 당일 알림 | ✓ 사라졌던 eltd_fail 가시성 복원 |
| 토·일 | 금 18:30 | stale 이지만 주말 게이트로 침묵 | ✓ 오탐 없음 |
| 공휴일(평일 스케줄) | 당일 18:30 (체인이 발화해 갱신) | fresh → 판정(몫 완료로 통과) | ✓ 오탐 없음 |
| 아침 catch-up 만 돈 날(08:00 기록) | 오늘 08:00(pre) | 17시 전 기록이나 ≥어제17시 → 아침엔 침묵, 21시 알림 | ✓ E=어제로 오판하지 않음 |
| 어젯밤 통째 수면 후 아침 기상 | 그저께 18:30 | mtime < 어제17시 → **아침 즉시 알림** | ✓ 구 코드와 동일 시점(1회 검토 보완) |

### H-2 (치명) — attempt_allowed 가 psql 경고 한 줄에 fail-open

**실측**: `db_query` 는 `2>&1` 이고 psql 경고는 결과보다 **먼저** 온다. 현행
`row=${row%%$'\n'*}`(첫 줄)는 경고를 취해 비숫자 비교 → 오류 → false → **무제한 허용**.

**확정 수정**: `row=${row##*$'\n'}`(마지막 줄 — 결과는 항상 끝) + `n`/`age` 에도
`case ... *[!0-9]*` 숫자 검증, 위반 시 DB 실패와 동일하게 `exit 1`(fail-closed).

### ⚠️ 함께 수정 (5건)

1. `_write_cache` tmp 에 PID — `p.with_name(f"{p.name}.{os.getpid()}.tmp")`.
   동시 writer(체인·llm_runner·weekly·웹 UI)가 같은 tmp 를 밟으면 원자성이 깨진다.
2. `cached_eltd` 손상 줄 — `return None` → `continue`. 같은 키의 손상 줄이
   뒤에 있어도 앞의 유효 줄을 살린다.
3. README "1회/12h·1회/24h" → **"1회/일"** 로 정정. `max=1` 이면 `n>0` 이 항상
   상한에 먼저 걸려 gap 인자는 발화하지 않는다(죽은 인자). 호출부 gap 인자 제거.
4. `watch_pipelines.sh:4` 헤더 주석 갱신 — "ELTD 기준(라이브)" 서술이 거짓이 됐고,
   PR #89 에서 제거했던 DOW/HOUR 게이트가 stale 분기에 한정 부활한 근거를 남긴다.
5. `probe_krx.sh` 날짜 가드 — `[ "$(date +%Y%m%d)" -ge 20260806 ] || exit 2`
   (+`PROBE_FORCE=1` 오버라이드). 실행 자체가 리스크인 스크립트가 주석으로만 보호되고 있었다.
6. `probe_krx.sh` 조회 창 5일 → **10일** — 연휴 직후엔 5일 창이 정상 상황에서도 0행이라
   "차단 지속" 오판 가능(1회 검토 반영. 보수적 방향의 오판이지만 재개를 불필요하게 미룬다).

### 테스트 공백 채움 (4건)

- `eltd_cache_fresh_today()` 단위 테스트(fresh/stale/파일 없음)
- `attempt_allowed` **기본값 경로** 테스트(인자 없이 호출 — 현재는 전부 명시 인자라
  기본값이 99/0 으로 바뀌어도 초록)
- `_write_cache` 의 "마지막 줄 = 최신 항목" 계약 테스트(감시의 `tail -1` 이 의존)
- stderr 오염 재현 테스트 — `run_guard` 에서 `db_query` 를 경고+결과 다줄 스텁으로
  재정의해 attempt_allowed 가 마지막 줄을 취하는지 고정

### 기록만 (수정 안 함)

- 자정 구멍: 23:50 실패 + 00:05 RunAtLoad 는 `n=0` → 15분 간격 ALLOW.
  당일 창 설계의 본질적 한계, 발생 확률·피해 낮음(다음 시도가 상한에 걸림).
- `stat -f %m` 은 macOS 전용 — 이 프로젝트는 macOS 운영 전제. 이식성 부채로만 기록.
- `launchctl list` 게이트는 crash-loop unload 와 의도적 bootout 을 구분하지 못함.
- 커밋 `df41b9a` 본문의 "3+1+4=6요청" 산술 오류(실제 8) — 이미 커밋된 메시지라
  수정 불가, 여기 정정 기록. 방향(name_display=False 로 절반 감축)은 유효.

---

## 4차 검토(전체 2회 검토, 2026-08-04) 반영

**1회차(통합 실행 + 위임 전체검토)**: 아무도 실행해보지 않았던 watch 통합 경로를 실제
실행으로 검증 — fresh 캐시 → miss 3종 목표일 기준 발화 / 3일 전 캐시 → 아침 즉시 알림 /
정상 패턴 → 침묵. 모두 설계대로.

**2회차에서 수리한 결함 1건 (머지 차단급)**:

- **매주 월요일 아침 오탐** — `eltd_cache_older_than_yesterday17` 의 기준이 단순
  '어제 17시'라, 월요일의 어제 = 일요일이 되어 정상 주말(마지막 기록 = 금 18:30 저녁체인
  또는 토 03:00 주말체인)조차 OLD 판정 → 재개 후 매주 월요일 `eltd_stale` 허위 알림.
  3차 커밋의 "정상일 아침 오탐 없음 실측"은 화~금만 검증한 것이었다(위임 검토 발견,
  직접 재현 확정). → **직전 평일 17시** 기준으로 교체(`eltd_cache_older_than_prev_workday17`,
  월요일만 -3d). 요일별 테스트는 함수 내부 `date` 셰도잉으로 결정론화 — 실행 요일에 따라
  결과가 달라지는 flaky 를 차단(월요일 오탐이 3차에서 숨은 경로가 정확히 이것).

**잔존 갭(기록)**: "금 저녁 통째 결측 + 토 03:00 주말체인이 캐시 기록" 복합 시나리오는
월요일 아침 판정에서 마스킹된다 — 단 금 21:00 의 당일 알림(HOUR≥21 경로)이 이미 잡았을
사안이라 리마인더 소실일 뿐. / 같은 결측이 당일 21시 + 익일 아침 두 번 울릴 수 있다
(dedupe 키가 날짜별) — 리마인더로 간주. / `_write_cache` 의 PID tmp 는 크래시 시 잔존
파일이 누적될 수 있다(cosmetic). / 캐시 없음일 때 알림 문구는 "캐시 없음"으로 표시.

---

## 5차 — PR#93 코드 리뷰(7회차) 반영 (2026-08-04)

리뷰 발견 높음 2·중간 3·낮음 4 중, 검증(1회)으로 전부 확정 후 높음 2 + 중간 3 수리.

- **H-1(수리)**: weekend_chain 의 running/상한 분기가 fall-through → 주봉 미완 상태로
  LLM 분류 실행 → 불완전 분류가 그 주의 최신으로 박제(weekend.py 계약 위반). main 에서는
  구조적으로 불가능했던 경로를 이 PR 이 열었었다. → 두 분기 `exit 0`(체인 전체 보류).
- **H-2(수리)**: monthly_chain 상한 분기 fall-through → 매핑이 universe 를 앞질러 월 몫
  완료 마킹 → "역순이면 한 달 누락" 실현. → `exit 0`(순서 보전).
- **M-1(수리)**: `pytest -m integration` 이 addopts 의 `-m 'not krx'` 를 덮어 krx 테스트가
  실행됨 + pykrx webio 는 세션 없이도 무인증 요청을 보냄 → conftest 수집 훅으로 krx 마커
  강제 skip(KR_ALLOW_KRX=1 제외). skip 마커는 픽스처보다 먼저 평가되므로 내부 스키마
  리셋도 발생하지 않는다.
- **M-2(수리)**: 백오프 간격의 자정 리셋(count·age 둘 다 당일 필터 → 어제 23:30 +
  오늘 00:05 = 35분 통과) → age 를 전역 최근 시도 기준으로, `n>0` 전제 제거.
- **M-3(수리)**: "웹 UI 수동 실행도 상한 소모" 문구가 부분만 참(standalone ohlcv/weekly
  스펙은 별도 이름이라 상한 밖) → evening_chain 주석·README 정정.
- **낮음 4(기록)**: tail/stat 비원자(1h 내 자기 정정) / FRESH 경계 테스트의 자정 순간
  flaky 잔존 / ELTD 실패 exit 0 은 탐지가 당일 21시로 지연됨(수용) / probe 마스킹은
  pykrx 문구 결합(비밀번호는 어떤 경로로도 미출력 확인).
- 리뷰 과정 사고: 리뷰 에이전트가 워킹트리를 main 으로 되돌림 → 재체크아웃 복구(유실 0).

---

## ⚠️ 재개 절차 필수 변경 (2026-08-04 오후 — 머지 직후 발견)

**bootout 은 영구적이지 않다.** 08-04 10:01 로그인/재부팅 시 launchd 가 디스크의 plist 를
재로드해 정지시킨 4잡이 전부 되살아났고, RunAtLoad 로 즉발했다. 피해: evening(장중 skip)·
weekend(주차 창 밖 skip)·watch(캐시 read-only — 새 코드가 설계대로 접촉 0) 무해,
**monthly 만 universe 실행**(KRX ~6요청. 결과는 성공 — 차단 해제 긍정 신호이나 소량 조회라
대량 스윕과는 별개, 탐침으로 확인 필요).

→ 4잡에 `launchctl disable gui/$UID/<label>` 적용(재로그인에도 유지되는 영구 플래그).

**재개 시 bootstrap 전에 반드시 enable 부터**:
```bash
launchctl enable "gui/$(id -u)/com.krbyclaude.<잡>"      # disable 플래그 해제
launchctl bootstrap "gui/$(id -u)" ~/Library/LaunchAgents/com.krbyclaude.<잡>.plist
```
disable 상태에서는 bootstrap 이 거부되거나 무시된다. 재개 절차 3~5단계의 각 bootstrap 앞에
이 enable 을 추가할 것.
