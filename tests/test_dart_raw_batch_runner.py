"""#186 일일 반복 러너(scripts/dart_raw_batch_186.sh) — 가짜 uv 로 루프 종결 경로 검증. DART 접촉 0."""
import os
import subprocess
from datetime import date
from pathlib import Path

SCRIPT = Path(__file__).parent.parent / "scripts" / "dart_raw_batch_186.sh"


def _run_loop(tmp_path, body: str, last_run: str | None = None):
    home = tmp_path / "home"; (home / ".kr-by-claude" / "state").mkdir(parents=True)
    if last_run:
        (home / ".kr-by-claude" / "state" / "dart186.last_run").write_text(last_run + "\n")
    fake = tmp_path / "uv"; fake.write_text("#!/bin/bash\n" + body); fake.chmod(0o755)
    log = tmp_path / "run.log"
    env = {**os.environ, "HOME": str(home), "UV_BIN": str(fake), "START_HHMM": "0000", "LATEST_HHMM": "2400", "DART186_LOG": str(log), "DART186_NO_NOTIFY": "1"}
    r = subprocess.run(["bash", str(SCRIPT), "_loop"], env=env, capture_output=True, text=True, timeout=20)
    return r, log.read_text(), home / ".kr-by-claude" / "state"


def test_loop_ends_on_complete(tmp_path):
    r, log, st = _run_loop(tmp_path, 'echo \'{"stopped": "complete"}\'\nexit 0\n')
    assert "실행 종료 rc=0 stopped=complete" in log and "완주 — 루프 종료" in log
    assert (st / "dart186.last_run").read_text().strip() == date.today().isoformat()


def test_loop_ends_on_abnormal_stop(tmp_path):
    r, log, _ = _run_loop(tmp_path, 'echo \'{"stopped": "transient:TimeoutError"}\'\nexit 1\n')
    assert "rc=1 stopped=transient:TimeoutError" in log and "비정상 중단 — 루프 종료" in log


def test_loop_passes_dart_gate_env(tmp_path):
    r, log, _ = _run_loop(tmp_path, 'echo "GATE=$DART_ALLOW_BATCH ARGS=$*"\necho \'{"stopped": "complete"}\'\n')
    assert "GATE=1 ARGS=run python -m kr_pipeline.financials.raw_batch --run" in log


def test_loop_skips_after_latest_start(tmp_path):
    """시작 창 밖(LATEST_HHMM 이후)이면 실행하지 않고 대기 — 자정 넘김 방지. STOP 파일로 대기 루프를 빠져나오게 해 검증."""
    home = tmp_path / "home"; st = home / ".kr-by-claude" / "state"; st.mkdir(parents=True)
    fake = tmp_path / "uv"; fake.write_text("#!/bin/bash\necho RAN\n"); fake.chmod(0o755)
    log = tmp_path / "run.log"
    env = {**os.environ, "HOME": str(home), "UV_BIN": str(fake), "START_HHMM": "0000", "LATEST_HHMM": "0000",
           "DART186_LOG": str(log), "DART186_NO_NOTIFY": "1"}
    import signal, time
    p = subprocess.Popen(["bash", str(SCRIPT), "_loop"], env=env, start_new_session=True)   # 그룹째 종료 — sleep 300 고아 방지(재리뷰)
    try:
        for _ in range(100):                          # 루프가 분기에 도달했는지 확인(조기 사망으로 무의미 통과 방지)
            if log.exists() and "루프 시작" in log.read_text():
                break
            time.sleep(0.1)
        time.sleep(0.5)
    finally:
        os.killpg(p.pid, signal.SIGKILL); p.wait()
    text = log.read_text()
    assert "루프 시작" in text
    assert "RAN" not in text and "실행 시작" not in text
    assert not (st / "dart186.last_run").exists()
