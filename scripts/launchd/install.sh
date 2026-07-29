#!/bin/bash
# install.sh — #88 크론 → launchd 전환 설치 스크립트
# 순서(원자성, #88 검토): ① crontab 백업 → ② kr 관련 라인 제거 → ③ 구 LLM
# plist 3종 bootout → ④ 새 plist 5종 생성·bootstrap. RunAtLoad 즉발은 각
# 래퍼의 멱등·자물쇠 가드가 no-op 으로 흡수한다.
# 롤백: launchctl bootout gui/$UID/<label> 5종 + crontab < 백업파일 + 구 plist 재로드.
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SCRIPTS="$REPO/scripts/launchd"
LA="$HOME/Library/LaunchAgents"
LOGD="$HOME/.kr-by-claude"
UIDN=$(id -u)
TS=$(date +%Y%m%d-%H%M%S)

# ── 선행 검사 (#88 리뷰 차단 4·권고 12)
GITCOMMON=$(git -C "$REPO" rev-parse --git-common-dir 2>/dev/null || echo "")
case "$REPO" in
  *worktrees*) echo "오류: 워크트리($REPO)에서 설치 금지 — 본 리포에서 실행"; exit 1;;
esac
case "$GITCOMMON" in
  *"/worktrees/"*) echo "오류: 워크트리에서 설치 금지"; exit 1;;
esac
if ! pmset -g custom | grep -qE "^\s*sleep\s+0"; then
  echo "오류: pmset -c sleep 0 미설정 — 저녁 잡 중단 위험(#88 전제). sudo pmset -c sleep 0 후 재실행"
  echo "      (무시하려면 FORCE=1 로 실행)"
  [ "${FORCE:-0}" = "1" ] || exit 1
fi
pmset -g sched | grep -q "wakepoweron" || echo "경고: 반복 wake 예약 없음 — sudo pmset repeat wakeorpoweron MTWRFS 18:25:00 권장"

echo "== ① crontab 백업"
mkdir -p "$LOGD/cron-backups"
crontab -l > "$LOGD/cron-backups/crontab.backup.$TS" 2>/dev/null || true
echo "   저장: $LOGD/cron-backups/crontab.backup.$TS"

echo "== ② crontab 에서 kr-by-claude 라인 제거 (그 외 라인 보존)"
crontab -l 2>/dev/null | grep -v "kr-by-claude" | grep -v "KR-BY-CLAUDE" | crontab - || true
echo "   잔여 crontab:"; crontab -l 2>/dev/null || echo "   (비어 있음)"

echo "== ③ 구 LLM plist bootout (full-daily / weekend / performance)"
for L in llm-full-daily llm-weekend llm-performance; do
  launchctl bootout "gui/$UIDN/com.krbyclaude.$L" 2>/dev/null && echo "   bootout: $L" || echo "   (미로드): $L"
  [ -f "$LA/com.krbyclaude.$L.plist" ] && mv "$LA/com.krbyclaude.$L.plist" "$LOGD/cron-backups/com.krbyclaude.$L.plist.$TS"
done

plist_head() { cat <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.krbyclaude.$1</string>
  <key>WorkingDirectory</key><string>$REPO</string>
  <key>EnvironmentVariables</key><dict><key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string><key>KR_REPO</key><string>$REPO</string></dict>
  <key>StandardOutPath</key><string>$LOGD/launchd-$1.log</string>
  <key>StandardErrorPath</key><string>$LOGD/launchd-$1.log</string>
  <key>RunAtLoad</key><true/>
EOF
}
cal() { echo "    <dict><key>Weekday</key><integer>$1</integer><key>Hour</key><integer>$2</integer><key>Minute</key><integer>$3</integer></dict>"; }

echo "== ④ 새 plist 생성·로드"

# evening-chain: 평일 18:30, caffeinate -s 로 수면 억제
{ plist_head evening-chain
  echo "  <key>ProgramArguments</key><array><string>/usr/bin/caffeinate</string><string>-s</string><string>$SCRIPTS/evening_chain.sh</string></array>"
  echo "  <key>StartCalendarInterval</key><array>"
  for W in 1 2 3 4 5; do cal $W 18 30; done
  echo "  </array>"
  echo "</dict></plist>"
} > "$LA/com.krbyclaude.evening-chain.plist"

# weekend-chain: 토 03:00 + 월 08:00 catch-up 슬롯
{ plist_head weekend-chain
  echo "  <key>ProgramArguments</key><array><string>/usr/bin/caffeinate</string><string>-s</string><string>$SCRIPTS/weekend_chain.sh</string></array>"
  echo "  <key>StartCalendarInterval</key><array>"
  cal 6 3 0; cal 1 7 0   # 월 슬롯 07:00 — 08:00 morning-corp 와 락 경합 회피(#88 리뷰 22)
  echo "  </array>"
  echo "</dict></plist>"
} > "$LA/com.krbyclaude.weekend-chain.plist"

# monthly-chain: 매월 1일 06:30
{ plist_head monthly-chain
  echo "  <key>ProgramArguments</key><array><string>/usr/bin/caffeinate</string><string>-s</string><string>$SCRIPTS/monthly_chain.sh</string></array>"
  echo "  <key>StartCalendarInterval</key><dict><key>Day</key><integer>1</integer><key>Hour</key><integer>6</integer><key>Minute</key><integer>30</integer></dict>"
  echo "</dict></plist>"
} > "$LA/com.krbyclaude.monthly-chain.plist"

# morning-corp: 평일 08:00
{ plist_head morning-corp
  echo "  <key>ProgramArguments</key><array><string>$SCRIPTS/morning_corp.sh</string></array>"
  echo "  <key>StartCalendarInterval</key><array>"
  for W in 1 2 3 4 5; do cal $W 8 0; done
  echo "  </array>"
  echo "</dict></plist>"
} > "$LA/com.krbyclaude.morning-corp.plist"

# pipeline-watch: 1시간마다 감시
{ plist_head pipeline-watch
  echo "  <key>ProgramArguments</key><array><string>$SCRIPTS/watch_pipelines.sh</string></array>"
  echo "  <key>StartInterval</key><integer>3600</integer>"
  echo "</dict></plist>"
} > "$LA/com.krbyclaude.pipeline-watch.plist"

for L in evening-chain weekend-chain monthly-chain morning-corp pipeline-watch; do
  launchctl bootout "gui/$UIDN/com.krbyclaude.$L" 2>/dev/null || true
  launchctl bootstrap "gui/$UIDN" "$LA/com.krbyclaude.$L.plist"
  echo "   loaded: $L"
done

echo "== 완료. 현재 상태:"
launchctl list | grep krbyclaude
