#!/bin/bash
# monthly_chain.sh — 월간 체인 (#88): universe 갱신 → corp_code 매핑 갱신
# launchd 매일 06:30 + RunAtLoad. 순서 고정: universe 가 먼저여야 그 달
# 신규 상장 종목의 corp_code 매핑이 잡힌다(역순이면 한 달 누락 — #88 검토).
# 월간 몫 멱등이라 그 달 몫이 끝난 뒤의 발화는 DB 조회만 하고 끝난다(KRX 접촉 0).
# (#284) 매월 1일만 발화하던 때에는 1일 실행이 실패하면 다음 발화가 로그인·재설치뿐이라 재시도가 깨어나지 못했다
# (11-01 KRX 접속 실패 → 11-09 까지 8일 방치). 매일 발화로 바꾸고 재시도를 아래로 묶는다:
#   universe: 사람 확인이 필요한 가드 실패가 있으면 보류 · 한 달 MONTH_ATTEMPT_MAX 회 · 하루 1회
#   매핑:     한 달 MONTH_ATTEMPT_MAX 회 · 하루 1회
# 보류·상한 판정은 읽기 전용이라 락·보고서 단계보다 먼저 한다(아무 일도 안 할 발화가 data 락을 기다리거나 쥐지 않게).
# 보류·상한 상태는 watch_pipelines 가 Slack 으로 알린다(발화 자체는 로그만 남기고 exit 0).
source "$(dirname "${BASH_SOURCE[0]}")/lib_guards.sh"

MONTH_START="date_trunc('month', now())"
DAY_START="date_trunc('day', now())"

mapping_done() { has_success_since corporate_actions "$MONTH_START" refresh-mapping; }

# 매핑 재시도 상한 — corporate_actions 는 아침 증분도 같은 pipeline 이름이라 mode 로 한정해 센다.
mapping_allowed() {
  attempts_below corporate_actions "$MONTH_START" "$MONTH_ATTEMPT_MAX" refresh-mapping \
    && attempts_below corporate_actions "$DAY_START" 1 refresh-mapping
}

# 가장 최근 가드 실패 run 의 잔여 조사 보고서를 (다시) 보낼 때인가. 아래 둘 중 하나:
#   - 아직 한 번도 전송되지 않았다(웹훅 일시 장애 등)
#   - LLM 조사 없이 사실만 전송됐고(facts_only) 실패 후 REPORT_RETRY_DAYS 일이 안 지났다 — 다음 날 LLM 조사를 다시 시도(#221)
# 매월 1일만 발화하던 때에는 "매 발화마다 전송 시도" 였지만, 매일 발화에서 그대로 두면 보류가 이어지는 동안
# 같은 사실만 보고가 매일 Slack 에 다시 올라간다(리뷰 #285). 같은 날 중복은 보고서 쪽(report.py)이 막는다.
REPORT_RETRY_DAYS="${REPORT_RETRY_DAYS:-3}"
report_due() {
  local n
  _uint_arg universe report_retry_days "$REPORT_RETRY_DAYS" || return 1
  n=$(db_query "SELECT COUNT(*) FROM (SELECT started_at, details FROM pipeline_runs WHERE pipeline='universe' AND status='failed' AND started_at >= $MONTH_START AND details ? 'report_key' AND details->'report_key' <> '[]'::jsonb ORDER BY started_at DESC, id DESC LIMIT 1) r WHERE NOT (r.details ? 'report_sent_at') OR (r.details->>'report_kind' = 'facts_only' AND r.started_at > now() - interval '$REPORT_RETRY_DAYS days')") \
    || { log "보고서 전송 여부 조회 실패 — fail-closed 중단"; exit 1; }
  [ "${n##*$'\n'}" = "1" ]
}

send_exclusion_report() {
  uv run python scripts/universe_exclusion_report.py || log "exclusion 보고서 단계 실패(비차단)"
}

UNIVERSE_DONE=0
has_success_since universe "$MONTH_START" && UNIVERSE_DONE=1

# 이번 달 몫(universe·매핑)이 모두 끝났으면 바로 끝낸다 — 매일 발화의 평상시 경로.
if [ "$UNIVERSE_DONE" = 1 ] && mapping_done; then
  exit 0
fi

log "monthly_chain 시작"

if [ "$UNIVERSE_DONE" = 0 ]; then
  # (#221) 직전 실패 run 의 잔여 조사 보고서 — 아래 보류·상한 판정보다 **앞**(시도 상한에 걸린 날에도 미전송 보고서는 간다),
  # data 락 획득보다 **앞**(LLM 대기 최대 ~8분 동안 락을 쥐면 morning_corp 등 다른 체인을 막는다 — 리뷰 #223 5차). KRX 접촉 0.
  report_due && send_exclusion_report
  if needs_human_since universe "$MONTH_START"; then
    # 사람이 원인을 보고 universe 를 --accept-exclusion-diff 로 직접 실행해 성공하면 다음 발화가 매핑을 잇는다.
    log "universe 가드 실패(사람 확인 필요) — 자동 재시도 안 함, 매핑 단계 포함 전체 보류"
    exit 0
  elif ! attempts_below universe "$MONTH_START" "$MONTH_ATTEMPT_MAX"; then
    log "universe 이번 달 시도 상한 — 매핑 단계 포함 전체 보류(순서 보전)"
    exit 0
  elif ! attempt_allowed universe 1; then   # max=1 → 하루 1회(#92). gap 은 기본값(6h)
    # ⚠️ exit 0 필수(PR#93 리뷰 H-2) — fall-through 하면 매핑이 universe 보다 먼저 성공해
    #   월 몫 완료로 마킹되고, 헤더가 경고한 "역순이면 한 달 누락"이 실제로 일어난다.
    log "universe 미완료이나 하루 시도 상한/간격 — 매핑 단계 포함 전체 보류(순서 보전)"
    exit 0
  fi
elif ! mapping_allowed; then
  log "corp_code 매핑 미완료이나 시도 상한 — 보류"
  exit 0
fi

if ! acquire_lock data 7200; then log "data 락 획득 실패(2h) — 중단"; exit 1; fi

# 락을 기다리는 동안 사람이 직접 실행해 끝냈을 수 있다 — 락을 쥔 뒤 다시 본다.
if has_success_since universe "$MONTH_START"; then  # universe 는 단일 mode
  log "universe 이번 달 몫 완료 — skip"
else
  log "universe 실행"
  if ! uv run python -m kr_pipeline.universe; then
    log "universe 실패 — 매핑 단계 중단(순서 보전)"
    # (#221) 배제 집합 잔여 변동이면 조사 보고서(claude -p 웹 검색 + Slack, KRX 접촉 0 — 보고서 경로는 pykrx 미import). data 락을 먼저
    # 놓는다 — LLM 대기(report.py 예산: 2회 × 1시도 × 240s ≤ 8분) 동안 morning_corp 등 다른 체인을 막지 않는다. 마지막 성공 이후 이미 전송된
    # 잔여 키(details.report_key_sent)는 생략된다. LLM 실패여도 규칙 판정만으로 Slack 은 간다.
    release_lock data
    send_exclusion_report
    exit 1
  fi
fi

# refresh-mapping 도 corporate_actions pipeline 으로 기록되므로 mode 로 구분
if mapping_done; then
  log "corp_code 매핑 이번 달 몫 완료 — skip"
elif ! mapping_allowed; then
  log "corp_code 매핑 미완료이나 시도 상한 — 보류"
else
  log "corp_code 매핑 갱신 실행"
  uv run python -m kr_pipeline.corporate_actions --mode=refresh-mapping || log "매핑 갱신 실패(비차단)"
fi

log "monthly_chain 종료"
