"""SSOT thresholds.py → web/src/data/thresholds.generated.ts 자동 생성.

사용:
    uv run python scripts/export_thresholds.py

이 스크립트는 빌드 단계 또는 SSOT 변경 시 수동 실행. 결과 파일
(thresholds.generated.ts) 은 git 에 commit (drift 추적용).
"""
import inspect
import json
from pathlib import Path
from typing import Any

from kr_pipeline.common import thresholds as ssot

OUTPUT_PATH = Path(__file__).resolve().parents[1] / "web" / "src" / "data" / "thresholds.generated.ts"

HEADER = """\
/* eslint-disable */
// AUTO-GENERATED — DO NOT EDIT BY HAND.
// Source: kr_pipeline/common/thresholds.py
// Regenerate: `uv run python scripts/export_thresholds.py`
"""


def _to_ts_value(v: Any) -> str:
    """Python 값을 TypeScript literal 로 직렬화."""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, str):
        return json.dumps(v)
    if isinstance(v, dict):
        items = ", ".join(f'"{k}": {_to_ts_value(val)}' for k, val in v.items())
        return "{ " + items + " }"
    if isinstance(v, (list, tuple)):
        items = ", ".join(_to_ts_value(x) for x in v)
        return "[" + items + "]"
    raise TypeError(f"Unsupported type for SSOT export: {type(v)}")


def _ts_type(v: Any) -> str:
    if isinstance(v, bool):
        return "boolean"
    if isinstance(v, int):
        return "number"
    if isinstance(v, float):
        return "number"
    if isinstance(v, str):
        return "string"
    if isinstance(v, dict):
        # 값 타입 균일 가정 (현 SSOT 의 dict 는 {market: float} 형태)
        if v:
            inner = _ts_type(next(iter(v.values())))
            return f"Record<string, {inner}>"
        return "Record<string, unknown>"
    if isinstance(v, list):
        if v:
            return f"{_ts_type(v[0])}[]"
        return "unknown[]"
    return "unknown"


def main() -> None:
    lines: list[str] = [HEADER]

    # ssot 모듈의 module-level 상수만 추출 (Final[...] 또는 평범한 대문자 변수)
    for name, value in vars(ssot).items():
        if name.startswith("_"):
            continue
        if inspect.ismodule(value) or inspect.isfunction(value) or inspect.isclass(value):
            continue
        # typing.Final 등 typing 이름은 skip
        if getattr(value, "__module__", None) == "typing":
            continue
        if not name.isupper() and not name[0].isupper():
            continue
        ts_type = _ts_type(value)
        ts_value = _to_ts_value(value)
        lines.append(f"export const {name}: {ts_type} = {ts_value};")

    OUTPUT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {OUTPUT_PATH} ({len(lines)-1} constants)")


if __name__ == "__main__":
    main()
