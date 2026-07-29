#!/bin/bash
# watch_pipelines.sh — 파이프라인 감시 (#88 2단계). launchd StartInterval 3600.
# 판정 원칙: status='success' 만 인정(running 좌초 별도 탐지) / wake·부팅 직후
# 20분 유예(coalesce 발화가 아직 안 돌았는데 결측 오탐 방지) / 알림은 Slack
# 기본(webhook, .env — CWD 로드라 REPO 에서 실행) + osascript 보조 /
# 같은 날 같은 키는 1회만(dedupe) / 매 실행 heartbeat 기록(자기 감시).
# 기대 목록 정본 = pipeline_specs 의 scheduler=launchd 잡 — 변경 시 여기 동기.
# 감시 쿼리 앵커는 자정 넘김 대응식 사용(#88 코멘트 검증분).
source "$(dirname "${BASH_SOURCE[0]}")/lib_guards.sh"

STATE_DIR="$HOME/.kr-by-claude/watch_state"
mkdir -p "$STATE_DIR"
touch "$STATE_DIR/heartbeat"

alert() { # $1=dedupe_key $2=message
  local key="$STATE_DIR/$(date +%Y%m%d).$1"
  [ -f "$key" ] && return 0
  local webhook
  webhook=$(grep '^SLACK_WEBHOOK_URL=' "$REPO/.env" 2>/dev/null | cut -d= -f2-)
  if [ -n "$webhook" ]; then
    curl -s -m 10 -X POST -H 'Content-type: application/json' \
      --data "{\"text\":\"[kr-pipeline 감시] $2\"}" "$webhook" >/dev/null 2>&1 \
      && touch "$key" && log "alert(slack): $2" && return 0
  fi
  osascript -e "display notification \"$2\" with title \"kr-pipeline 감시\"" >/dev/null 2>&1
  touch "$key"; log "alert(osascript): $2"
}

# ── wake/부팅 20분 유예 (coalesce 발화 미도래 오탐 방지)
LAST_WAKE=$(pmset -g log 2>/dev/null | grep -E "Wake from|DarkWake from" | tail -1 | awk '{print $1" "$2}')
if [ -n "$LAST_WAKE" ]; then
  WAKE_TS=$(date -j -f "%Y-%m-%d %H:%M:%S" "$LAST_WAKE" +%s 2>/dev/null || echo 0)
  NOW_TS=$(date +%s)
  if [ "$WAKE_TS" -gt 0 ] && [ $((NOW_TS - WAKE_TS)) -lt 1200 ]; then
    log "wake 후 $(( (NOW_TS - WAKE_TS) / 60 ))분 — 유예 종료"
    exit 0
  fi
fi

DOW=$(date +%w); HOUR=$(date +%H)
EVENING_ANCHOR="date_trunc('day', now() - interval '17 hours') + interval '17 hours'"
WEEK_ANCHOR=$(last_saturday_expr)

# ── 1. failed 탐지 (오늘 발생분)
psql_one "SELECT pipeline||'/'||mode||' '||to_char(started_at,'HH24:MI') FROM pipeline_runs WHERE status='failed' AND started_at >= date_trunc('day', now())" \
| while read -r line; do
  [ -n "$line" ] && alert "failed.$(echo "$line" | tr ' /' '__')" "실행 실패: $line"
done

# ── 2. running 좌초 탐지 (12시간 초과 — full-daily 실측 7h21m 여유)
psql_one "SELECT pipeline||'/'||mode||' since '||to_char(started_at,'MM-DD HH24:MI') FROM pipeline_runs WHERE status='running' AND started_at < now() - interval '12 hours'" \
| while read -r line; do
  [ -n "$line" ] && alert "stuck.$(echo "$line" | tr ' /' '__')" "running 좌초(12h+): $line"
done

# ── 3. 평일 기대 실행 결측 (running 중이면 유예)
if [ "$DOW" != "0" ] && [ "$DOW" != "6" ]; then
  if [ "$HOUR" -ge 9 ]; then
    has_success_since corporate_actions "date_trunc('day', now())" \
      || alert "miss.corp" "08:00 공시 증분 미실행 (9시 경과)"
  fi
  if [ "$HOUR" -ge 21 ]; then
    has_success_since data_daily "$EVENING_ANCHOR" \
      || alert "miss.data_daily" "18:30 데이터 체인 미완료 (21시 경과)"
    N=$(psql_one "SELECT COUNT(*) FROM pipeline_runs WHERE pipeline='llm_daily_delta' AND mode='full-daily' AND status IN ('success','running') AND started_at >= $EVENING_ANCHOR")
    [ "${N:-0}" -gt 0 ] || alert "miss.llm" "LLM full-daily 미시작 (21시 경과)"
  fi
fi

# ── 4. 주말 몫 결측 (월 09:30 이후 = catch-up 창까지 닫힌 뒤)
if [ "$DOW" = "1" ] && { [ "$HOUR" -gt 9 ] || { [ "$HOUR" -eq 9 ] && [ "$(date +%M)" -ge 30 ]; }; }; then
  has_success_since data_weekly "$WEEK_ANCHOR" \
    || alert "miss.data_weekly" "주봉 데이터 체인 이번 주차 미완료"
  has_success_since llm_weekend "$WEEK_ANCHOR" \
    || alert "miss.llm_weekend" "주말 분류 이번 주차 미완료"
fi

log "watch 완료"
