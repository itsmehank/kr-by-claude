"""cron_manager — crontab read/write + 마커 + 백업."""
import pytest
from pathlib import Path


def test_extract_managed_lines_from_text():
    """마커 사이의 라인만 추출."""
    from kr_pipeline.llm_runner.cron_manager import extract_managed_lines

    crontab_text = """
0 5 * * * /usr/local/bin/my-backup.sh

# === kr-by-claude-llm-runner BEGIN ===
0 20 * * 1-5 /path/llm_runner --mode=full-daily
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


def test_default_cron_lines_contains_three_modes():
    """default cron 라인에 LLM 3종 (full-daily, weekend, performance) + 통합 체인 2종 포함 확인.
    P1a 이후 예약 spec 8개: universe, corporate-actions, data-daily, data-weekly,
    market-context, llm-full-daily, llm-weekend, llm-performance.
    (기존 ohlcv/weekly/indicators-daily/indicators-weekly 는 비예약(cron="")으로 제외, llm-backfill 도 제외.)
    """
    from kr_pipeline.llm_runner.cron_manager import DEFAULT_CRON_LINES

    assert len(DEFAULT_CRON_LINES) == 8
    assert any("full-daily" in line for line in DEFAULT_CRON_LINES)
    assert any("weekend" in line for line in DEFAULT_CRON_LINES)
    assert any("performance" in line for line in DEFAULT_CRON_LINES)
    assert any("--chain=daily" in line for line in DEFAULT_CRON_LINES)
    assert any("--chain=weekly" in line for line in DEFAULT_CRON_LINES)


def test_register_and_unregister_flow(monkeypatch, tmp_path):
    """register → 마커 안 라인 있음 → unregister → 마커 사라짐."""
    from kr_pipeline.llm_runner import cron_manager as cm

    state = {"crontab": "0 5 * * * /user_backup\n"}

    def fake_get():
        return state["crontab"]

    def fake_install(text):
        state["crontab"] = text

    monkeypatch.setattr(cm, "get_current_crontab", fake_get)
    monkeypatch.setattr(cm, "install_crontab", fake_install)
    monkeypatch.setattr(cm, "BACKUP_DIR", tmp_path)

    backup1, new_text = cm.register()
    assert "kr-by-claude-llm-runner BEGIN" in state["crontab"]
    assert "--mode=full-daily" in state["crontab"]
    assert "/user_backup" in state["crontab"]
    assert backup1.exists()

    backup2, new_text = cm.unregister()
    assert "kr-by-claude-llm-runner" not in state["crontab"]
    assert "/user_backup" in state["crontab"]
    assert backup2.exists()


def test_register_is_idempotent(monkeypatch, tmp_path):
    """이미 등록된 상태에서 register 다시 호출 — 마커 한 번만 존재."""
    from kr_pipeline.llm_runner import cron_manager as cm

    state = {"crontab": ""}
    monkeypatch.setattr(cm, "get_current_crontab", lambda: state["crontab"])
    monkeypatch.setattr(
        cm, "install_crontab", lambda text: state.update(crontab=text)
    )
    monkeypatch.setattr(cm, "BACKUP_DIR", tmp_path)

    cm.register()
    cm.register()
    # 마커 BEGIN 이 1회만 등장
    assert state["crontab"].count("kr-by-claude-llm-runner BEGIN") == 1
