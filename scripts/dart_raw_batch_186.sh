#!/bin/bash
# dart_raw_batch_186.sh — #186 DART 주요계정 원본 보존 배치의 일일 반복 러너(사용자 승인 2026-10-06, A안).
#
# 사용: scripts/dart_raw_batch_186.sh {start|stop|status|log}
#   start   백그라운드 루프 기동 — 매일 START_HHMM(08:30, 아침 공시 수집 08:00 뒤) 이후 1회 raw_batch --run.
#           일 cap(18,000) 소진(rc 0)이면 다음 날 이어감, 완주(complete)면 종료, 비정상 중단(rc≠0: 020·fatal·parity·transient)이면 종료.
#   stop    다음 대기 지점에서 종료(STOP 파일) — 진행 중 배치는 끝까지 둔다(재개 멱등).
#   status  실행 여부 + 마지막 실행 결과 + dart_batch_log 최근 7일
#   log     tail -f
#
# 자정 경계: raw_batch 는 시작일로 일 한도를 센다(dart_batch_log.batch_date) — 시작 창 START_HHMM~LATEST_HHMM(08:30~20:00)으로 cap 소진이
#   자정 전에 끝나게 한다(1일차 실측 77분). 덮개를 닫으면 caffeinate -i 로도 잠들 수 있어 그때도 같은 위험 — 전원 연결·덮개 열림 권장.
# ⚠️ 반드시 라이브 체크아웃에서 start 한다 — REPO·.env·응답 보존 경로(data/dart_raw)가 스크립트 위치 기준이라 worktree 에서 띄우면
#   worktree 삭제 시 원본 응답이 사라질 수 있다(운영 규칙 5). 재부팅·로그아웃 후엔 자동 재기동 없음 — status 확인 후 start.
# 테스트 훅: UV_BIN(가짜 러너), START_HHMM, DART186_LOG, DART186_NO_NOTIFY=1, HOME(상태 디렉터리 격리).
# KRX 접촉 0: raw_batch 의 import 체인에 pykrx 없음(DART 전용). DART 접촉 게이트 DART_ALLOW_BATCH=1 은 이 러너가 설정한다(승인 = 이 러너 start).
set -u
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATE="$HOME/.kr-by-claude/state"
LOG="${DART186_LOG:-$HOME/.kr-by-claude/dart_raw_batch_186.log}"
PIDF="$STATE/dart186.pid"
STOPF="$STATE/dart186.stop"
LASTF="$STATE/dart186.last_run"        # 마지막 실행 날짜(YYYY-MM-DD) — 하루 1회 보장
RESULTF="$STATE/dart186.last_result"   # 마지막 실행 rc·stopped
START_HHMM="${START_HHMM:-0830}"
# 늦은 시작 상한(리뷰): 08:30 에 잠들어 있다가 밤늦게 깨면 실행이 자정을 넘겨, 우리 계정(시작일 기준)과 DART 한도(자정 초기화)가 어긋나
# 다음 날 020 으로 멈춘다. 이 시각 이후엔 그날 실행을 건너뛰고 다음 날 08:30 을 기다린다(1일차 실측 소요 77분 + 재시도 여유).
LATEST_HHMM="${LATEST_HHMM:-2000}"
UV="${UV_BIN:-/opt/homebrew/bin/uv}"
mkdir -p "$STATE"

ts() { date '+%F %T'; }
note() { echo "[$(ts)] $*" >> "$LOG"; }
notify() { [ "${DART186_NO_NOTIFY:-0}" = "1" ] || osascript -e "display notification \"$1\" with title \"kr-pipeline\"" >/dev/null 2>&1; }
alive() { [ -f "$PIDF" ] && kill -0 "$(cat "$PIDF" 2>/dev/null)" 2>/dev/null; }

loop() {
  note "루프 시작(pid $$, START_HHMM=$START_HHMM)"
  while true; do
    [ -f "$STOPF" ] && { note "STOP 파일 — 루프 종료"; rm -f "$STOPF"; break; }
    today=$(date +%F)
    now=$(date +%H%M)
    if [ "$now" -lt "$START_HHMM" ] || [ "$now" -ge "$LATEST_HHMM" ] || [ "$(cat "$LASTF" 2>/dev/null)" = "$today" ]; then
      sleep 300; continue
    fi
    echo "$today" > "$LASTF"
    note "실행 시작"
    out=$(mktemp "${TMPDIR:-/tmp}/dart186.XXXXXX")
    (cd "$REPO" && DART_ALLOW_BATCH=1 /usr/bin/caffeinate -i "$UV" run python -m kr_pipeline.financials.raw_batch --run) > "$out" 2>&1
    rc=$?
    cat "$out" >> "$LOG"
    stopped=$(grep -o '"stopped": *"[^"]*"' "$out" | tail -1 | sed 's/.*: *"//; s/"$//')
    rm -f "$out"
    echo "$today rc=$rc stopped=${stopped:-?}" > "$RESULTF"
    note "실행 종료 rc=$rc stopped=${stopped:-?}"
    if [ "$rc" -ne 0 ]; then
      note "비정상 중단 — 루프 종료(원인 확인 후 start 로 재개, 멱등)"
      notify "#186 배치 비정상 중단 rc=$rc ${stopped:-}"
      break
    fi
    if [ "$stopped" = "complete" ]; then
      note "완주 — 루프 종료"
      notify "#186 배치 완주"
      break
    fi
  done
  rm -f "$PIDF"
}

case "${1:-}" in
  start)
    if alive; then echo "이미 실행 중(pid $(cat "$PIDF"))"; exit 1; fi
    rm -f "$STOPF"
    nohup "$0" _loop >/dev/null 2>&1 &
    echo $! > "$PIDF"; disown
    echo "기동(pid $(cat "$PIDF")) — 매일 ${START_HHMM} 이후 1회, 로그: $LOG"
    ;;
  _loop) loop ;;
  stop)
    touch "$STOPF"; echo "STOP 파일 생성 — 다음 대기 지점에서 종료(진행 중 배치는 끝까지)"
    ;;
  status)
    if alive; then echo "실행 중(pid $(cat "$PIDF"))"; else echo "중지"; fi
    echo "마지막 실행: $(cat "$RESULTF" 2>/dev/null || echo 없음)"
    psql -d "${KR_DB:-kr_pipeline}" -Atc "SELECT batch_date, calls, cap, stopped_020 FROM dart_batch_log ORDER BY batch_date DESC LIMIT 7" 2>/dev/null
    psql -d "${KR_DB:-kr_pipeline}" -Atc "SELECT count(*) || ' 셀 / ' || count(DISTINCT corp_code) || ' corp' FROM dart_fin_raw" 2>/dev/null
    ;;
  log) tail -f "$LOG" ;;
  *) echo "사용: $0 {start|stop|status|log}"; exit 2 ;;
esac
