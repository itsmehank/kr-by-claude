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


@router.post("/register")
def register():
    try:
        backup_path, new_text = cron_manager.register()
    except RuntimeError as e:
        raise HTTPException(500, str(e))
    return {
        "registered": True,
        "backup_path": str(backup_path),
        "lines_count": len(cron_manager.DEFAULT_CRON_LINES),
    }


@router.post("/unregister")
def unregister():
    try:
        backup_path, new_text = cron_manager.unregister()
    except RuntimeError as e:
        raise HTTPException(500, str(e))
    return {"registered": False, "backup_path": str(backup_path)}
