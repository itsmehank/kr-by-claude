"""(#221) 유니버스 배제 집합 변동 잔여분 조사 보고서만 전송 — KRX 접촉 0·락 불요·멱등(이미 전송된 키면 no-op).

monthly_chain.sh 가 `attempt_allowed universe` 게이트 **앞에서** 호출한다: 미전송 보고서는 universe 재시도 가능 여부와 무관하게
그날 바로 사람에게 가야 하고(리뷰 #223 4차), 이 단계는 대량 스윕이 아니다. 전용 스크립트인 이유 = `python -m kr_pipeline.universe`
문자열이 게이트 앞에 놓이면 "스윕은 게이트 뒤" 안전 테스트(tests/test_launchd_guards.test_wrapper_gates_before_sweep, #92)가 깨진다 —
그 테스트는 토큰 위치로 판정하므로 보고서 전용 경로는 모듈 호출 형태를 쓰지 않는다. 수동 실행은
`python -m kr_pipeline.universe --report-last-failed` 로도 가능(같은 함수).
"""
import logging
import sys

from kr_pipeline.common.config import Config
from kr_pipeline.common.logging import setup_logging
from kr_pipeline.db.connection import connect
from kr_pipeline.universe.report import report_last_failed

log = logging.getLogger("kr_pipeline.universe.report")


def main() -> int:
    cfg = Config.load()
    setup_logging(cfg.log_level)
    with connect(cfg.database_url) as conn:
        outcome = report_last_failed(conn)
    log.info(f"exclusion report: {outcome}")
    return 1 if outcome == "failed" else 0


if __name__ == "__main__":
    sys.exit(main())
