> **[기록 문서]** 본 문서의 규약 문장은 작성 시점 기록이며, 현행 규칙은 `docs/superpowers/governance.md` 절 ID를 따른다 (#155, 2026-09-09).

# #221 universe 배제 집합 변동 자동 판정 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `verify_universe_after_load` 의 guard(snapshot) 가 배제 집합 변동 원소를 3분류해 설명 가능한 2유형(상폐·신규 상장 배제)은 자동 수용하고, 잔여분만 실패 + `claude -p` 조사 보고서를 Slack 으로 보낸다.

**Architecture:** 분류는 순수 함수(`kr_pipeline/universe/exclusion_diff.py: classify_exclusion_diff`) — 입력 = 직전 스냅샷 집합·이번 배제 df·이번 원본(raw) 티커 집합·"stocks 에 존재한 적 있는 티커" 집합. 가드는 이 결과로 잔여분이 있을 때만 `UniverseGuardError`(판정 객체 첨부). `__main__` 이 예외를 잡아 보고서(`report.py: build_local_facts` → `call_claude(tools=Read+Web)` → `slack.notify_universe_exclusion_report`)를 보내고 재발생시킨다(run_tracking 이 failed 기록). 보고서 실패는 비차단(로그). 자동 수용은 기본, `--strict-exclusion-diff` 로 끔. 수용 내역은 `pipeline_runs.details.exclusion_auto_accepted`.

**Tech Stack:** Python(psycopg, pandas), Claude CLI 래퍼(`llm_runner/llm/claude_cli.call_claude` — `tools` 파라미터 신설, 기본 "Read" 불변), Slack webhook(`llm_runner/slack._post`).

**Spec:** GitHub issue #221 본문(해결 방법 1~3·완료 조건 5). 권한 분리는 governance 2-1(리포 자동 규칙 우선)·2-2(질의 필요 경우)·2-3(질의 양식) 인용 — 보고서는 자료, 수용은 규칙/사람.

## Global Constraints

- #199 wake 절("기존 포함 → 신규 배제 차분은 --accept-exclusion-diff 단독 수용 금지")을 코드로 고정 — governance 2-1/2-2 인용.
- 자동 수용 상한 `MAX_AUTO_DELISTED=10`·`MAX_AUTO_NEW_LISTING=30`(리뷰 #223 반영) 은 spec 에 없는 수치 — governance 2-2 에 따라 **[Q] 전문가 판정 대기**(잠정값, 초과 시 fail-closed 라 보수 방향). PR #223 본문에 질의 기재.
- 분류 규칙(이슈 본문): removed ∧ raw 에 없음 → 상폐 자동 / added ∧ stocks 에 없던 티커 ∧ axis ∈ {spac, preferred, security_group} → 신규 상장 배제 자동 / 그 외 잔여.
- 접촉 정책 = CLAUDE.md 운영 규칙 5 인용. 보고서 사실은 로컬 DB 만; LLM 도구는 `claude_cli.ALLOWED_TOOLSETS`("Read,WebSearch", WebFetch 미개방)로 도구 층에서 제한(리뷰 #223).
- `call_claude` 기본 동작(tools="Read", 분류 결정론) 불변 — 새 `tools` 인자는 opt-in.
- 운영 규칙: 브랜치 `issue221-universe-exclusion-auto`(worktree univ-221), `git add` 명시 경로, suite 전 `pgrep -f pytest`, Co-Authored-By 금지. thresholds 미변경(2축 표 불요).

---

### Task 1: 순수 분류 `classify_exclusion_diff`

**Files:** Create `kr_pipeline/universe/exclusion_diff.py`; Test `tests/test_universe_exclusion_diff.py`.
**Produces:** `@dataclass ExclusionDiff(added_new_listing: list[str], removed_delisted: list[str], unexplained_added: list[dict], unexplained_removed: list[dict])` + `.unexplained` 프로퍼티(bool) + `.summary()` dict; `classify_exclusion_diff(*, prev_set, excluded: pd.DataFrame, raw_tickers: set[str], ever_in_stocks: set[str]) -> ExclusionDiff`. `AUTO_ACCEPT_AXES = frozenset({"spac", "preferred", "security_group"})`.

- [ ] RED: 4 케이스 — 상폐(removed, raw 에 없음) 자동 / 신규 스팩(added, stocks 무, axis spac) 자동 / 기존 활성 → 배제(added, stocks 유) 잔여(#199) / raw 에 있는데 배제에서 빠짐(removed, raw 유) 잔여. 10-01 실제 변동(+0200G0 +0209J0 −465320) 재현 → 전부 자동.
- [ ] GREEN 구현 → 통과.

### Task 2: 가드 통합 + `--strict-exclusion-diff`

**Files:** Modify `kr_pipeline/universe/guards.py`(verify_universe_after_load 에 `raw_tickers: set[str] | None`, `auto_accept: bool = True` 추가), `kr_pipeline/universe/__main__.py`(플래그·raw_tickers 전달·details 기록); Test `tests/test_universe_guards.py`.
**Produces:** `UniverseGuardError.diff: ExclusionDiff | None`; info 에 `exclusion_auto_accepted: {"removed_delisted": [...], "added_new_listing": [...]}`, `exclusion_unexplained: {...}`.

- [ ] RED: (a) 자동 수용분만 → 실패 없음·info 기록, (b) 잔여분 → UniverseGuardError 에 `.diff`, (c) `auto_accept=False` 면 자동 유형도 실패(strict), (d) `accept_exclusion_diff=True` 는 종전대로 전부 수용. raw_tickers None 이면 removed 는 전부 잔여(보수).
- [ ] GREEN → 통과. 기존 `test_snapshot_first_run_writes_baseline_and_diff_fails_next` 는 R1 이 raw 에 남아 있는 케이스로 유지(잔여).

### Task 3: 조사 보고서(`claude -p` + Slack)

**Files:** Create `kr_pipeline/universe/report.py`, `prompts/universe_exclusion_report_v1.md`; Modify `kr_pipeline/llm_runner/llm/claude_cli.py`(`tools: str = "Read"` 인자), `kr_pipeline/llm_runner/slack.py`(`notify_universe_exclusion_report(text)`), `__main__.py`(예외 처리); Test `tests/test_universe_exclusion_report.py`, `tests/test_claude_cli*.py` 중 cmd 조립 테스트가 있으면 tools 반영.
**Produces:** `build_local_facts(conn, diff, snapshot_date) -> dict`(티커별 name/market/security_group/axis, stocks 존재·delisted_at, 마지막 일봉, 직전 스냅샷 존재, corporate_actions 최근 5건), `make_report(diff, facts, *, call=call_claude) -> dict`(스키마: `{"items":[{"ticker","verdict":"delisted|new_listing|axis_change|unknown","evidence":str,"recommend":"accept|hold"}], "summary":str}`), `send_report(report, *, post=...) -> bool`, `report_unexplained(conn, diff, snapshot_date, *, call, post) -> None`(실패 비차단).

- [ ] RED: build_local_facts 가 시드 데이터로 사실 수집 / make_report 가 가짜 call 로 스키마 검증·불일치 1회 재시도 / send_report 가 post 호출·webhook 없음·예외 시 False / `call_claude(tools="Read,WebSearch,WebFetch")` 가 cmd 에 반영(subprocess mock).
- [ ] GREEN → 통과. 프롬프트: 역할(사실 자료 + 웹 검색으로 상폐·합병·종목명 변경 공시 확인), 규칙(결정 아님·근거 URL 명시·KRX 도메인 접촉 금지·JSON 만), 스키마.

### Task 4: `__main__` 배선·월간 체인 로그·검증·PR

**Files:** Modify `kr_pipeline/universe/__main__.py`, `scripts/launchd/monthly_chain.sh`(실패 로그에 "조사 보고서 Slack 전송 여부" 1줄); Test 통합(`tests/test_universe_guards.py` 또는 신규): main 경로는 함수로 분리해(`run_universe(conn, *, today, accept, strict, fetchers...)`) KRX monkeypatch 로 10-01 재현.

- [ ] RED: 10-01 재현(raw 에 0200G0·0209J0 추가, 465320 제거, 직전 스냅샷 09-22) → run success·details.exclusion_auto_accepted 기록·보고서 미전송. 잔여 케이스 → 실패 + report 호출 1회.
- [ ] GREEN → 통과. 전체 suite·커밋·push·PR(`gh pr create`), 이슈 #221 코멘트.

## 리뷰 2차 반영(10-05)

보고서를 `--report-last-failed` 별도 단계로(실패 run 의 details 에 판정 + 원본 행 사본 보존 → monthly_chain 이 data 락 해제 후 호출 → 커밋된 상태에서 사실 수집 → 전송 성공 시 `details.report_sent_at`·`report_key_sent` 로 dedup), `ever_seen`(이전 배제/원본 스냅샷) 으로 재등장 왕복 차단, 상한 초과·security_group 조회 실패는 systemic 으로 LLM 생략·사실만 Slack, 보고서 도구 WebSearch 만, Slack 본문 20건 상한, 성공·실패 details 키 통일(`ExclusionDiff.summary`), accept/strict 충돌을 KRX 접촉 전에 검사, `UniverseGuardError.prev_date`, `_post(raise_on_error)` 공유, dict_row·집합 질의.

## 리뷰 3차 반영(10-05)

보고서 경로의 pykrx import 제거(`__main__` fetch 래퍼 지연 import, 테스트가 subprocess 로 고정), #199 유형은 `--accept` 로도 거부(`ExclusionDiff.has_199`), dedup 을 마지막 성공 이후 **모든** 실패 run 의 `report_key_sent` 와 비교, LLM 단계 실패 시 규칙 판정만으로 Slack(`format_facts_only`)·`main()` 은 failed 에 rc 1, 원본 응답 파일 보존(`universe_raw_<date>.json`, 운영 규칙 5), 부분 응답 2차 신호(`_raw_complete`: 직전 원본 대비 시장별 2% 급감 → 상폐 자동 수용 보류·systemic `raw_shrunk`), `systemic` 복수(list), 읽기 트랜잭션을 LLM 대기 전 종료, CLI 재시도 예산(`call_claude(max_attempts=1)`, 2×240s ≤ 8분), [Q-1] 양식으로 상한 3종 질의.

## 리뷰 4차 반영(10-05)

스냅샷 판정을 쓰기 전 `preflight_exclusion_diff` 로(잔여·strict·#199 accept 는 upsert/mark_delisted 없이 실패 — 오폐지 커밋 경로 제거), 원본 급감은 `UniverseRawIncomplete` 로 쓰기 전 fail-closed(상수 = store.MAX_DELIST_RATIO 공유), UNRESOLVED 로 적재돼 있던 행의 늦은 분류는 kind `late_resolution`(accept 가능 — #199 는 확정 그룹이었던 행만), strict 실패 행(report_key=[])이 잔여 run 을 가리지 않게, facts_only 전송은 당일만 dedup(다음 날 LLM 재시도), 전송 마커 3회 재시도, 응답 파일을 시각 포함 이름으로 universe·security_group·sector 3응답 누적 보존, monthly_chain 이 universe 시도와 무관하게 매 발화마다 미전송 보고서 시도, `max_attempts<1` 거부. 잔여 위험(기록): 직전 대비 2% 미만 결손의 ≤10 종목 부분 응답은 자동 수용될 수 있음 — [Q-1] 에 포함.

## Self-Review
- 완료 조건 1(분류·자동 수용 테스트 3케이스) → T1·T2; 2(잔여 → 실패 + Slack 보고서, 프롬프트 파일) → T3; 3(details·로그) → T2·T4; 4(#199 유형 금지 테스트) → T1·T2; 5(10-01 재현) → T1·T4.
- 타입: `ExclusionDiff` 필드명·`classify_exclusion_diff` kwargs·`report_unexplained(conn, diff, snapshot_date, *, call, post)` 를 T2~T4 가 동일 사용.

## 후속 (2026-10-05, 회신 23 Q-G — 위 4차 반영의 일부 superseded)

늦은 분류(`late_resolution`)도 `--accept-exclusion-diff` 로 **수용 불가**로 변경 — 금지 사유는 원인(조회 지연 vs 규칙 변경)이 아니라 결과(stocks 행이 있는
종목을 배제하면 `mark_delisted` 가 상장 종목을 폐지로 기록)이며 두 유형이 같다(회신 10·12). `ExclusionDiff.has_199` → `has_accept_refused`/`accept_refused_tickers`
(`ACCEPT_REFUSED_KINDS`). 첫 발생 = #199 착수 신호(의미 정정 + 상태 컬럼 동시). 상한 10/30/20 은 회신 22 Q-C 로 A 채택(잠정, 6회 누적 후 재설정).
