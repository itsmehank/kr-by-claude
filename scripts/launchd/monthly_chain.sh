#!/bin/bash
# monthly_chain.sh — 월간 체인 (#88): universe 갱신 → corp_code 매핑 갱신
# launchd 매일 06:30 + RunAtLoad. 순서 고정: universe 가 먼저여야 그 달
# 신규 상장 종목의 corp_code 매핑이 잡힌다(역순이면 한 달 누락 — #88 검토).
# 월간 몫 멱등이라 그 달 몫이 끝난 뒤의 발화는 DB 조회만 하고 끝난다(KRX 접촉 0).
# (#284) 매월 1일만 발화하던 때에는 1일 실행이 실패하면 다음 발화가 로그인·재설치뿐이라 재시도 로직이 깨어나지 못했다
# (11-01 KRX 접속 실패 → 11-09 까지 8일 방치). 매일 발화로 바꾸고, 재시도는 아래 세 조건으로 묶는다:
#   하루 1회(attempt_allowed) · 한 달 MONTH_ATTEMPT_MAX 회(장애·차단 장기화 시 접촉 반복 방지) · 가드 실패는 자동 재시도 안 함.
source "$(dirname "${BASH_SOURCE[0]}")/lib_guards.sh"

MONTH_START="date_trunc('month', now())"
MONTH_ATTEMPT_MAX="${MONTH_ATTEMPT_MAX:-5}"

mapping_done() {
  local n
  n=$(db_query "SELECT COUNT(*) FROM pipeline_runs WHERE pipeline='corporate_actions' AND mode='refresh-mapping' AND status='success' AND started_at >= $MONTH_START") \
    || { log "DB 조회 실패 — fail-closed 중단"; exit 1; }
  [ "$n" -gt 0 ]
}

# 이번 달 몫(universe·매핑)이 모두 끝났으면 락도 잡지 않고 끝낸다 — 매일 발화의 평상시 경로.
if has_success_since universe "$MONTH_START" && mapping_done; then
  exit 0
fi

log "monthly_chain 시작"

# (#221) 이번 달 universe 가 아직 성공 전이면, 직전 실패 run 의 잔여 조사 보고서가 미전송 상태일 수 있다(웹훅 일시 장애 등) — 시도 상한과
# 무관하게 매 발화마다 전송 시도(KRX 접촉 0·이미 전송됐으면 즉시 no-op). data 락 **획득 전**에 돌린다 — LLM 재시도(사실만 전송 다음 날)는
# 최대 ~8분이라 락을 쥐면 morning_corp 등 다른 체인을 막는다(리뷰 #223 5차). universe 재시도 전에 돌려 사람이 더 일찍 본다.
if ! has_success_since universe "$MONTH_START"; then
  uv run python scripts/universe_exclusion_report.py || log "exclusion 보고서 단계 실패(비차단)"
fi

if ! acquire_lock data 7200; then log "data 락 획득 실패(2h) — 중단"; exit 1; fi

if has_success_since universe "$MONTH_START"; then  # universe 는 단일 mode
  log "universe 이번 달 몫 완료 — skip"
elif last_run_failed_with universe "$MONTH_START" "guard("; then
  # (#284) 가드 실패(배제 집합 변동 등)는 사람이 원인을 보고 수용해야 풀린다 — 다시 돌려도 KRX 만 접촉하고 같은 실패다.
  # 사람이 universe 를 --accept-exclusion-diff 로 직접 실행해 성공하면 다음 발화가 매핑을 잇는다.
  log "universe 직전 실패가 가드 — 자동 재시도 안 함(사람 확인 필요), 매핑 단계 포함 전체 보류"
  exit 0
elif ! attempts_below universe "$MONTH_START" "$MONTH_ATTEMPT_MAX"; then
  log "universe 이번 달 시도 상한 — 매핑 단계 포함 전체 보류(순서 보전)"
  exit 0
elif ! attempt_allowed universe 1; then   # max=1 → 하루 1회. gap 인자는 발화 불가라 제거(3차 검토)
  # #92: 멱등이 성공 기준이라 실패한 달에는 RunAtLoad 발화마다 재시도한다(08-01 실측 실패).
  # ⚠️ exit 0 필수(PR#93 리뷰 H-2) — fall-through 하면 매핑이 universe 보다 먼저 성공해
  #   월 몫 완료로 마킹되고, 헤더가 경고한 "역순이면 한 달 누락"이 실제로 일어난다.
  log "universe 미완료이나 시도 상한/백오프 — 매핑 단계 포함 전체 보류(순서 보전)"
  exit 0
else
  log "universe 실행"
  if ! uv run python -m kr_pipeline.universe; then
    log "universe 실패 — 매핑 단계 중단(순서 보전)"
    # (#221) 배제 집합 잔여 변동이면 조사 보고서(claude -p 웹 검색 + Slack, KRX 접촉 0 — 보고서 경로는 pykrx 미import). data 락을 먼저
    # 놓는다 — LLM 대기(report.py 예산: 2회 × 1시도 × 240s ≤ 8분) 동안 morning_corp 등 다른 체인을 막지 않는다. 마지막 성공 이후 이미 전송된
    # 잔여 키(details.report_key_sent)는 생략되므로 RunAtLoad 재발화에 안전. LLM 실패여도 규칙 판정만으로 Slack 은 간다.
    release_lock data
    uv run python scripts/universe_exclusion_report.py || log "exclusion 보고서 단계 실패(비차단)"
    exit 1
  fi
fi

# refresh-mapping 도 corporate_actions pipeline 으로 기록되므로 mode 로 구분
if mapping_done; then
  log "corp_code 매핑 이번 달 몫 완료 — skip"
else
  log "corp_code 매핑 갱신 실행"
  uv run python -m kr_pipeline.corporate_actions --mode=refresh-mapping || log "매핑 갱신 실패(비차단)"
fi

log "monthly_chain 종료"
