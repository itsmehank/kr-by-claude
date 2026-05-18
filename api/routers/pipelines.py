from fastapi import APIRouter

from kr_pipeline.llm_runner.pipeline_specs import PIPELINE_SPECS


router = APIRouter(prefix="/api/pipelines", tags=["pipelines"])


@router.get("")
def list_pipelines():
    """모든 pipeline spec 반환 (frontend 가 동적 렌더링용)."""
    return {"pipelines": PIPELINE_SPECS}
