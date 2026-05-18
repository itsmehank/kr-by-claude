"""cron_manager — crontab read/write + 마커 + 백업."""
import pytest
from pathlib import Path


def test_extract_managed_lines_from_text():
    """마커 사이의 라인만 추출."""
    from kr_pipeline.llm_runner.cron_manager import extract_managed_lines

    crontab_text = """
0 5 * * * /usr/local/bin/my-backup.sh

# === kr-by-claude-llm-runner BEGIN ===
30 16 * * 1-5 /path/llm_runner --mode=full-daily
20 3 * * 6 /path/llm_runner --mode=weekend
# === kr-by-claude-llm-runner END ===

0 4 * * * /usr/local/bin/log-cleanup.sh
"""
    managed = extract_managed_lines(crontab_text)
    assert len(managed) == 2
    assert "--mode=full-daily" in managed[0]
    assert "--mode=weekend" in managed[1]


def test_extract_returns_empty_when_no_markers():
    from kr_pipeline.llm_runner.cron_manager import extract_managed_lines
    assert extract_managed_lines("0 5 * * * /bin/foo") == []


def test_replace_managed_block_preserves_other_lines():
    """마커 영역만 교체. 다른 라인 보존."""
    from kr_pipeline.llm_runner.cron_manager import replace_managed_block

    original = """0 5 * * * /backup
# === kr-by-claude-llm-runner BEGIN ===
old_line
# === kr-by-claude-llm-runner END ===
0 6 * * * /other"""

    new = replace_managed_block(original, ["new_line_a", "new_line_b"])
    assert "/backup" in new
    assert "/other" in new
    assert "new_line_a" in new
    assert "new_line_b" in new
    assert "old_line" not in new


def test_replace_managed_block_appends_if_no_markers():
    """마커 없으면 끝에 새 블록 append."""
    from kr_pipeline.llm_runner.cron_manager import replace_managed_block

    original = "0 5 * * * /backup\n"
    new = replace_managed_block(original, ["new_line"])
    assert "/backup" in new
    assert "kr-by-claude-llm-runner BEGIN" in new
    assert "kr-by-claude-llm-runner END" in new
    assert "new_line" in new


def test_remove_managed_block():
    """마커 영역 전체 제거."""
    from kr_pipeline.llm_runner.cron_manager import remove_managed_block

    original = """0 5 * * * /backup
# === kr-by-claude-llm-runner BEGIN ===
line1
line2
# === kr-by-claude-llm-runner END ===
0 6 * * * /other"""

    new = remove_managed_block(original)
    assert "/backup" in new
    assert "/other" in new
    assert "kr-by-claude-llm-runner" not in new
    assert "line1" not in new


def test_backup_writes_timestamp_file(tmp_path, monkeypatch):
    """현재 crontab 을 timestamp 파일로 저장."""
    from kr_pipeline.llm_runner.cron_manager import backup_crontab

    monkeypatch.setattr(
        "kr_pipeline.llm_runner.cron_manager.BACKUP_DIR",
        tmp_path / "backups",
    )

    backup_path = backup_crontab("0 5 * * * /test")
    assert backup_path.exists()
    assert "0 5 * * * /test" in backup_path.read_text()
    assert "crontab-" in backup_path.name


def test_diff_managed_block_shows_changes():
    """현재 vs 새 라인 diff."""
    from kr_pipeline.llm_runner.cron_manager import diff_managed_block

    current_lines = ["old_a", "old_b"]
    new_lines = ["new_a", "new_b", "new_c"]

    diff = diff_managed_block(current_lines, new_lines)
    assert any("-old_a" in line for line in diff)
    assert any("+new_a" in line for line in diff)
