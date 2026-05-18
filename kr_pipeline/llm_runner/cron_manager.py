"""crontab read/write 관리 — 마커 기반 영역, 자동 백업, diff 미리보기.

안전장치:
- BEGIN/END 마커 안만 read/write. 사용자가 손으로 추가한 다른 라인 절대 안 건드림.
- 변경 직전 timestamp 백업 (~/.kr-by-claude/cron-backups/)
- replace 후 일관성 검증 (외부에서 사용)
"""
from __future__ import annotations

import difflib
import re
import subprocess
from datetime import datetime
from pathlib import Path


BEGIN_MARKER = "# === kr-by-claude-llm-runner BEGIN ==="
END_MARKER = "# === kr-by-claude-llm-runner END ==="

BACKUP_DIR = Path.home() / ".kr-by-claude" / "cron-backups"


def get_current_crontab() -> str:
    """현재 user crontab 텍스트 반환. 없으면 빈 문자열."""
    try:
        result = subprocess.run(
            ["crontab", "-l"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return result.stdout
        # rc=1 이면 보통 "no crontab for user" — 빈 crontab 으로 처리
        return ""
    except FileNotFoundError:
        raise RuntimeError("crontab command not found")


def install_crontab(text: str) -> None:
    """주어진 텍스트로 crontab 덮어쓰기."""
    result = subprocess.run(
        ["crontab", "-"],
        input=text,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode != 0:
        raise RuntimeError(f"crontab install failed: {result.stderr}")


def extract_managed_lines(crontab_text: str) -> list[str]:
    """마커 사이의 cron 라인 추출. 마커 자체 + 빈 줄 제외."""
    if BEGIN_MARKER not in crontab_text or END_MARKER not in crontab_text:
        return []

    pattern = re.escape(BEGIN_MARKER) + r"(.*?)" + re.escape(END_MARKER)
    match = re.search(pattern, crontab_text, re.DOTALL)
    if not match:
        return []

    lines = match.group(1).strip().splitlines()
    return [line for line in lines if line.strip() and not line.strip().startswith("#")]


def replace_managed_block(crontab_text: str, new_lines: list[str]) -> str:
    """마커 영역을 new_lines 로 교체. 마커 없으면 끝에 append.

    Returns: 새 crontab 텍스트
    """
    block = "\n".join([BEGIN_MARKER, *new_lines, END_MARKER])

    if BEGIN_MARKER in crontab_text and END_MARKER in crontab_text:
        pattern = re.escape(BEGIN_MARKER) + r".*?" + re.escape(END_MARKER)
        return re.sub(pattern, block, crontab_text, count=1, flags=re.DOTALL)

    sep = "" if crontab_text.endswith("\n") or not crontab_text else "\n"
    return crontab_text + sep + "\n" + block + "\n"


def remove_managed_block(crontab_text: str) -> str:
    """마커 영역 전체 제거 (마커 라인 포함)."""
    if BEGIN_MARKER not in crontab_text or END_MARKER not in crontab_text:
        return crontab_text
    pattern = re.escape(BEGIN_MARKER) + r".*?" + re.escape(END_MARKER) + r"\n?"
    return re.sub(pattern, "", crontab_text, count=1, flags=re.DOTALL)


def backup_crontab(crontab_text: str) -> Path:
    """현재 crontab 을 timestamp 파일로 저장."""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    path = BACKUP_DIR / f"crontab-{ts}.txt"
    path.write_text(crontab_text)
    return path


def diff_managed_block(current_lines: list[str], new_lines: list[str]) -> list[str]:
    """current → new diff (unified format, prefix 만 추출).

    Returns: ["-old_line", "+new_line", " unchanged_line", ...]
    """
    diff = list(
        difflib.unified_diff(
            current_lines,
            new_lines,
            fromfile="current",
            tofile="new",
            lineterm="",
            n=0,
        )
    )
    # @@ hunk header 와 파일 헤더 제외
    return [
        line for line in diff
        if not line.startswith("@@") and not line.startswith("---") and not line.startswith("+++")
    ]


PROJECT_DIR = Path(__file__).parent.parent.parent  # repo root


def _get_default_cron_lines() -> list[str]:
    """PIPELINE_SPECS 기반 동적 생성. 순환 import 회피 위해 함수 안에서 import."""
    from kr_pipeline.llm_runner.pipeline_specs import get_default_cron_lines
    return get_default_cron_lines()


DEFAULT_CRON_LINES = _get_default_cron_lines()


def register(lines: list[str] | None = None) -> tuple[Path, str]:
    """LLM runner cron 라인을 등록.

    Returns: (backup_path, new_crontab_text)
    """
    if lines is None:
        lines = DEFAULT_CRON_LINES

    current = get_current_crontab()
    backup_path = backup_crontab(current)

    new_text = replace_managed_block(current, lines)
    install_crontab(new_text)

    # 일관성 검증
    installed = get_current_crontab()
    if extract_managed_lines(installed) != lines:
        # 롤백
        install_crontab(current)
        raise RuntimeError(
            f"crontab install verification failed; rolled back. Backup at {backup_path}"
        )
    return backup_path, new_text


def unregister() -> tuple[Path, str]:
    """LLM runner cron 영역 제거.

    Returns: (backup_path, new_crontab_text)
    """
    current = get_current_crontab()
    backup_path = backup_crontab(current)

    new_text = remove_managed_block(current)
    install_crontab(new_text)

    # 검증
    installed = get_current_crontab()
    if BEGIN_MARKER in installed:
        install_crontab(current)
        raise RuntimeError(
            f"crontab unregister verification failed; rolled back. Backup at {backup_path}"
        )
    return backup_path, new_text


def get_status() -> dict:
    """현재 cron 등록 상태 + 마커 안 라인 + 다음 예정 시각 정보."""
    current = get_current_crontab()
    managed = extract_managed_lines(current)
    return {
        "registered": len(managed) > 0,
        "lines": managed,
        "default_lines": DEFAULT_CRON_LINES,
        "marker_begin": BEGIN_MARKER,
        "marker_end": END_MARKER,
    }
