#!/bin/bash
# install_bt110.sh — (#242) #110 확장 백필 설치 스크립트. 다른 PC 에서 git clone 후에도 이 한 번으로 설치된다.
# 순서: ① 스키마(backfill_control 만 표적 적용) → ② 표본 C 워치독 bootout(교차 kill 방지) → ③ 핀 worktree(detached
#       @ origin/main 또는 --commit) + uv sync → ④ 워치독 plist 생성(경로는 이 리포 기준 파생)·bootstrap → ⑤ 스모크.
# 재핀: --repin 이면 기존 worktree 를 unlock·remove 후 새로 만들고 backfill_control.pinned_commit 을 NULL 로(사용자 psql 아님 — 여기서 수행).
# 웹 스위치는 설치와 무관하게 DB 값만 바꾼다(#86). 설치 후 /runner 에서 켜야 동작한다(기본 꺼짐).
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
case "$REPO" in *worktrees*) echo "오류: 워크트리($REPO)에서 설치 금지 — 본 리포에서 실행"; exit 1;; esac
LA="$HOME/Library/LaunchAgents"
LOGD="$HOME/.kr-by-claude"
UIDN=$(id -u)
RUN_DIR="$(dirname "$REPO")/kr-by-claude-worktrees/bt-110-run"
LABEL="com.krbyclaude.bt-110-watchdog"
COMMIT="origin/main"
REPIN=0
for a in "$@"; do
  case "$a" in
    --repin) REPIN=1;;
    --commit=*) COMMIT="${a#--commit=}";;
    *) echo "사용법: $0 [--repin] [--commit=<sha|ref>]"; exit 2;;
  esac
done
mkdir -p "$LOGD" "$LA"

# .env 의 DATABASE_URL(없으면 로컬 기본)
if [ -f "$REPO/.env" ]; then set -a; source "$REPO/.env"; set +a; fi
export DATABASE_URL="${DATABASE_URL:-postgresql://localhost/kr_pipeline}"

echo "== ① 스키마: backfill_control 표적 적용 (lock_timeout 5s)"
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -q -c "SET lock_timeout='5s'" \
  -f <(sed -n '/CREATE TABLE IF NOT EXISTS backfill_control/,/^);/p' "$REPO/kr_pipeline/db/schema.sql")
echo "   ok: $(psql "$DATABASE_URL" -tA -c "SELECT to_regclass('backfill_control')")"

echo "== ② 표본 C 워치독 제거(로드돼 있으면) — bt_loop_c 의 'profitability_cli backfill' pkill 이 110 백필을 죽이지 않게"
if launchctl list 2>/dev/null | grep -q "com.krbyclaude.bt-c-watchdog"; then
  launchctl bootout "gui/$UIDN/com.krbyclaude.bt-c-watchdog" && echo "   bootout: bt-c-watchdog"
  [ -f "$LA/com.krbyclaude.bt-c-watchdog.plist" ] && mv "$LA/com.krbyclaude.bt-c-watchdog.plist" "$LOGD/com.krbyclaude.bt-c-watchdog.plist.removed-$(date +%Y%m%d)"
else
  echo "   (미로드) — 건너뜀"
fi

echo "== ③ 핀 worktree: $RUN_DIR @ $COMMIT"
git -C "$REPO" fetch -q origin
if [ -d "$RUN_DIR" ]; then
  if [ "$REPIN" = "1" ]; then
    if [ -f /tmp/bt_loop_110.pid ] && kill -0 "$(cat /tmp/bt_loop_110.pid)" 2>/dev/null; then
      echo "오류: 루프 실행 중(pid $(cat /tmp/bt_loop_110.pid)) — 웹에서 스위치를 끄고 종료를 기다린 뒤 재실행"; exit 1
    fi
    git -C "$REPO" worktree unlock "$RUN_DIR" 2>/dev/null || true
    git -C "$REPO" worktree remove --force "$RUN_DIR"
    psql "$DATABASE_URL" -q -c "UPDATE backfill_control SET pinned_commit = NULL, updated_at = now() WHERE key = 'bt110'"
    echo "   재핀: 기존 worktree 제거·pinned_commit 초기화"
  else
    echo "   이미 존재 — 유지($(git -C "$RUN_DIR" rev-parse --short HEAD)). 코드 갱신은 --repin"
  fi
fi
if [ ! -d "$RUN_DIR" ]; then
  mkdir -p "$(dirname "$RUN_DIR")"
  git -C "$REPO" worktree add --detach "$RUN_DIR" "$COMMIT"
  git -C "$REPO" worktree lock "$RUN_DIR" --reason "bt110 pinned run dir (#242)"
  echo "   생성: $(git -C "$RUN_DIR" rev-parse --short HEAD) (locked)"
fi
(cd "$RUN_DIR" && uv sync -q) && echo "   uv sync ok"

echo "== ④ 워치독 plist 생성·로드 ($LABEL, 30분)"
cat > "$LA/$LABEL.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$LABEL</string>
  <key>EnvironmentVariables</key><dict>
    <key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
    <key>BT110_RUN_DIR</key><string>$RUN_DIR</string>
    <key>DATABASE_URL</key><string>$DATABASE_URL</string>
  </dict>
  <key>ProgramArguments</key><array><string>$RUN_DIR/scripts/bt_watchdog_110.sh</string></array>
  <key>StartInterval</key><integer>1800</integer>
  <key>AbandonProcessGroup</key><true/>
  <key>StandardOutPath</key><string>$LOGD/launchd-bt-110-watchdog.log</string>
  <key>StandardErrorPath</key><string>$LOGD/launchd-bt-110-watchdog.log</string>
</dict></plist>
EOF
launchctl bootout "gui/$UIDN/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$UIDN" "$LA/$LABEL.plist"
echo "   loaded: $(launchctl list | grep "$LABEL" || echo '(실패)')"

echo "== ⑤ 스모크(격리 로그, 비일요일/스위치 꺼짐이면 즉시 종료)"
SMOKE=$(mktemp -d)
BT110_RUN_DIR="$RUN_DIR" BT110_LOGDIR="$SMOKE" BT110_LOCK="$SMOKE/lock.pid" bash "$RUN_DIR/scripts/bt_backfill_loop_110.sh" || true
sed 's/^/   /' "$SMOKE/bt_loop_110.log"
echo "== 완료. 웹 /runner → '확장 백필 #110' 스위치는 기본 꺼짐 — 켜면 일요일 워치독이 기동한다."
echo "   상태: $(cd "$RUN_DIR" && uv run python -m kr_pipeline.backtest.bt110_cli status --kv)"
