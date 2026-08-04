#!/bin/bash
# probe_krx.sh — KRX 차단 해제 확인용 최소 탐침 (#92).
#
# 전 종목 스윕으로 해제를 확인하면 그 자체가 재탐지 유발 행위다. 3종목만 조회한다.
# DB 를 쓰지 않고 판정만 출력한다. rc=0 정상 / rc=1 차단 지속.
#
# KRX 접촉 = 로그인 1회(pykrx import 부작용) + OHLCV 종목당 1~3회
#            (_fetch_one 은 @with_retry(attempts=3) — 차단 시엔 빈 DataFrame 을 예외 없이
#             반환하므로 재시도하지 않고 1회로 끝난다)
#
# 사용: scripts/launchd/probe_krx.sh
# 주의: 하루 1회를 넘기지 말 것. 차단 대기 중에는 실행하지 말 것.
set -u
# 날짜 가드 — 실행 자체가 재탐지 리스크인 스크립트가 주석으로만 보호되면 안 된다(3차 검토).
# 차단 대기 종료일(08-06) 전에는 거부. 불가피하면 PROBE_FORCE=1 로 명시 오버라이드.
if [ "$(date +%Y%m%d)" -lt 20260806 ] && [ "${PROBE_FORCE:-0}" != "1" ]; then
  echo "[probe] 차단 대기 기간(08-06 전) — 실행 거부. 불가피하면 PROBE_FORCE=1"
  exit 2
fi
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO" || exit 1
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"

echo "[probe] 대형주 3종목 최근 10일 원주가 조회"
OUT=$(uv run python -c "
from kr_pipeline.common import config  # noqa: F401 — .env 로드(KRX 인증)
from datetime import date, timedelta
from kr_pipeline.ohlcv.fetch import _fetch_one

end = date.today()
start = end - timedelta(days=10)   # 5일이면 연휴 직후 정상인데도 0행 → 차단 오판(3차 검토)
ok = 0
for t in ('005930', '000660', '005380'):
    try:
        df = _fetch_one(t, start, end, adjusted=False)
        n = 0 if df is None or df.empty else len(df)
    except Exception as e:  # noqa: BLE001
        print(f'  {t}: 예외 {type(e).__name__}')
        n = 0
    print(f'  {t}: {n}행')
    if n > 0:
        ok += 1
print('OK_COUNT', ok)
" 2>&1)
rc=$?
# pykrx auth.py:189 가 계정 ID 를 stdout 에 print 한다 — 로그 평문 기록 차단
echo "$OUT" | grep -v '로그인 ID'

OKC=$(echo "$OUT" | grep -E '^OK_COUNT ' | awk '{print $2}')
if [ "$rc" -ne 0 ] || [ -z "$OKC" ] || [ "$OKC" = "0" ]; then
  echo "[probe] 판정: 차단 지속(3종목 전부 빈 응답 또는 오류) — 재개하지 말 것"
  exit 1
fi
if [ "$OKC" != "3" ]; then
  echo "[probe] 판정: 부분 응답($OKC/3) — 스로틀 잔존 의심. 재개 보류 권장"
  exit 1
fi
echo "[probe] 판정: 정상(3/3) — 단계적 재개 가능"
exit 0
