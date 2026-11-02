# #242 — #110 1차 조각(2021+2024) 백필 배관: 웹 스위치·일요일 루프·스냅샷 모집단·핀 worktree

2026-11-02. 소유 이슈 #242(설계 승인·검토 1회 반영), 상위 #110(결정 코멘트 2026-11-02). 규약은 `docs/superpowers/governance.md` 절 ID 인용.

## 1. 구성 요소

| 요소 | 파일 | 역할 |
|---|---|---|
| 제어 테이블 | `kr_pipeline/db/schema.sql` `backfill_control` | 스위치(enabled)·슬라이스·**셀 스냅샷**·기준선·핀 커밋. 웹은 이 행만 바꾼다(#86 — cron/launchd 등록 금지) |
| 제어 모듈 | `kr_pipeline/backtest/bt110.py` | 셀 열거(0단계 견적과 동일 필터)·스위치·진행·트립와이어·커밋 핀. 노출 값 = 건수·모델 종수(미열람 보존) |
| 루프 CLI | `kr_pipeline/backtest/bt110_cli.py` | `status [--kv]` / `pin --head` — 쉘이 SQL 을 갖지 않게 |
| 러너 | `profitability_cli backfill --population=bt110` | 스냅샷 셀만 처리(`run_backtest_backfill(candidates_by_date=…)`, 기본 None 이면 기존 동작 불변). `MAX_SAMPLE` 가드 우회는 의도(동결 표본 아닌 DB 고정 목록) |
| 루프 | `scripts/bt_backfill_loop_110.sh` | 일요일 전용·스위치 조회·트립와이어·**23:30 데드라인**·핀 대조·모델 변경 경고·STUCK/서킷 대기 |
| 워치독 | `scripts/bt_watchdog_110.sh` + `scripts/launchd/com.krbyclaude.bt-110-watchdog.plist` | 30분마다: 일요일 ∧ on ∧ 마커 없음 ∧ 루프 없음 → `caffeinate -s` 로 루프 기동 |
| 라이브 가드 | `scripts/launchd/lib_guards.sh bt_loop_alive` | `/tmp/bt_loop_c.pid`·`/tmp/bt_loop_110.pid` 둘 다 검사 — 일요일 RunAtLoad 체인이 백필 중 skip |
| API | `api/routers/backfill.py` | `GET /api/backfill/bt110/status`, `POST /api/backfill/bt110/switch {enabled}` |
| 웹 | `web/src/pages/RunnerPage.tsx` `Bt110Section` | 스위치·진행·핀·트립와이어·모델 종수. 결과 미표시 |

## 2. 설치 절차 (사용자 수동 — 순서 고정)

1. **스키마 적용(두 DB)**: `psql -d kr_pipeline -f kr_pipeline/db/schema.sql` / `psql -d kr_test -f …` (conftest 는 kr_test 를 자동 재적용).
2. **표본 C 워치독 제거**(교차 kill 방지 — 검토 A-2):
   `launchctl bootout gui/$(id -u)/com.krbyclaude.bt-c-watchdog && rm ~/Library/LaunchAgents/com.krbyclaude.bt-c-watchdog.plist`
   (bt-c-run worktree 는 보존 — 기록용. COMPLETE 마커 로그는 그대로.)
3. **핀 worktree**(머지 커밋 = 시작 커밋):
   ```
   cd /Users/hank.es/git/personal/kr-by-claude && git fetch origin
   git worktree add --detach /Users/hank.es/git/personal/kr-by-claude-worktrees/bt-110-run origin/main
   git worktree lock /Users/hank.es/git/personal/kr-by-claude-worktrees/bt-110-run
   cd /Users/hank.es/git/personal/kr-by-claude-worktrees/bt-110-run && uv sync
   ```
   `.env` 없음 → 루프가 `DATABASE_URL`·`KR_CLAUDE_MODEL=sonnet` 을 export 한다(Config.load 는 env 우선).
4. **dry-run 1패스**(비일요일에도 OK — 스위치 꺼짐이면 즉시 종료, 켜짐이면 일요일 아님으로 종료):
   `BT110_LOGDIR=/tmp/bt110-smoke bash scripts/bt_backfill_loop_110.sh && cat /tmp/bt110-smoke/bt_loop_110.log`
5. **plist 등록**: `cp scripts/launchd/com.krbyclaude.bt-110-watchdog.plist ~/Library/LaunchAgents/ && launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.krbyclaude.bt-110-watchdog.plist`
6. **웹에서 켜기**(`/runner` → 확장 백필 #110 → 켜기). 켜는 순간 셀 스냅샷·기준선이 동결된다(목표 ≈19,734 — 0단계 견적과 ±수십 차이는 지표 재계산분).
7. 첫 일요일 뒤 `~/.kr-by-claude/bt_loop_110.log` 의 pass 행(processed/failures)과 웹 진행률만 확인. **BF_LOG·DB 분류 결과는 열람하지 않는다**(3-4·evidence-tier v2).

## 3. 운영 규칙

- 스위치 off = 다음 패스에서 종료(진행 중 패스는 데드라인 23:30 까지 계속). on = 멱등 재개(스냅샷 유지).
- 종결 마커(`=== COMPLETE|STUCK|TRIPWIRE|PIN_MISMATCH`) 가 로그에 있으면 워치독은 기동하지 않는다. 재개하려면 로그를 날짜 접미로 옮긴다(마커 보존).
- 재핀(코드 수정 반영): 스위치 off → 루프 종료 확인 → worktree unlock·remove → 새 커밋으로 3번 재실행 → `UPDATE backfill_control SET pinned_commit=NULL WHERE key='bt110'`(사용자 psql) → on.
- 2차 조각(2023): 1차 COMPLETE → `#110` 코멘트·LOOK_LOG("미열람 — 생산만") → 사용자 지시로 `slice` 변경 + `cells=NULL`(재스냅샷) → on.
- 일요일 백필 중 `/api/issues/refresh` 금지(같은 claude 시그니처). 1일=일요일(다음 2027-08-01)은 monthly-chain 과 쿼터 공유.
- 처리량 전제: 일요일 중앙값 344셀(213~590), TRIP_SLEEP 30분 → 1차 ≈58회.

## 4. 테스트

`tests/test_bt110_control.py`(8) · `tests/test_api_backfill_bt110.py`(3) · `tests/test_profitability_cli_bt110.py`(4) · `tests/test_backtest_backfill.py`(+2) · `tests/test_launchd_guards.py`(+2). 루프·워치독은 격리 경로(`BT110_LOGDIR`·`BT110_LOCK`·`BT110_RUN_DIR`) 스모크 1회(비일요일 → 즉시 종료, 핀 미기록).

## 5. 범위 밖
상폐 포함(#180 ②-2 후 같은 핀 커밋으로 추가), 2차 자동 전환, 결과 분석(#108 안건 4·5).
