from fastapi import APIRouter, HTTPException

from kr_pipeline.llm_runner import cron_manager


router = APIRouter(prefix="/api/cron", tags=["cron"])


@router.get("/status")
def status():
    """현재 cron 등록 상태."""
    try:
        return cron_manager.get_status()
    except RuntimeError as e:
        raise HTTPException(500, str(e))


@router.get("/preview")
def preview(action: str):
    """register / unregister diff 미리보기."""
    if action not in ("register", "unregister"):
        raise HTTPException(400, "action must be 'register' or 'unregister'")

    try:
        current = cron_manager.get_current_crontab()
    except RuntimeError as e:
        raise HTTPException(500, str(e))

    current_lines = cron_manager.extract_managed_lines(current)
    if action == "register":
        new_lines = cron_manager.DEFAULT_CRON_LINES
        new_crontab = cron_manager.replace_managed_block(current, new_lines)
    else:
        new_lines = []
        new_crontab = cron_manager.remove_managed_block(current)

    diff = cron_manager.diff_managed_block(current_lines, new_lines)
    return {
        "action": action,
        "current_lines": current_lines,
        "new_lines": new_lines,
        "diff": diff,
        "new_crontab_preview": new_crontab,
    }


# 실전 LLM 작업(full-daily·weekend·performance)이 2026-07-26 macOS launchd 로 이전됨(#86).
# 그런데 pipeline_specs 는 미변경이라 cron_manager.DEFAULT_CRON_LINES 는 여전히 LLM 을 방출:
#  - register  → LLM cron 재생성 → launchd 와 이중 등록(performance 23:00 real 2회 등)
#  - unregister→ 관리블록 전체 삭제 = 데이터 cron(universe·pipeline·market_context 등) 전멸
# cron_manager/pipeline_specs 정합화(#86) 전까지 두 변경 엔드포인트를 하드 차단(read-only
# status/preview 는 허용). GET 아닌 이 POST 들은 버튼·직접호출 모두 이 가드에 걸린다.
_CRON_MGMT_DISABLED = (
    "cron register/unregister 는 비활성화되었습니다 — 실전 LLM 작업이 launchd 로 "
    "이전되어(#86) register 는 이중 등록, unregister 는 데이터 cron 삭제 위험이 있습니다. "
    "cron_manager/pipeline_specs 정합화 후 재활성화 예정."
)


@router.post("/register")
def register():
    raise HTTPException(409, _CRON_MGMT_DISABLED)


@router.post("/unregister")
def unregister():
    raise HTTPException(409, _CRON_MGMT_DISABLED)
