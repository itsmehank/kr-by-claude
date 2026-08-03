"""launchd 래퍼 가드(lib_guards.sh) 검증 — bash 서브프로세스로 실행.

#92: KRX 접촉 빈도 제한이 회귀하지 않도록 고정한다. pykrx 는 호출하지 않는다.
"""
import os
import subprocess
from pathlib import Path
from urllib.parse import urlparse

import psycopg
import pytest

REPO = Path(__file__).parent.parent
LAUNCHD = REPO / "scripts" / "launchd"
GUARDS = LAUNCHD / "lib_guards.sh"
TEST_DSN = os.environ.get("TEST_DATABASE_URL", "")
KR_TEST_DB = urlparse(TEST_DSN).path.lstrip("/") if TEST_DSN else ""


def _pg_env() -> dict:
    """TEST_DATABASE_URL 을 psql 이 쓰는 PG* 환경변수로 분해.

    KR_DB 에 dbname 만 넘기면 host/port/user 가 빠져 엉뚱한 DB 에 붙을 수 있다.
    """
    u = urlparse(TEST_DSN)
    env = {}
    if u.hostname:
        env["PGHOST"] = u.hostname
    if u.port:
        env["PGPORT"] = str(u.port)
    if u.username:
        env["PGUSER"] = u.username
    return env


def run_guard(script: str, env_extra: dict | None = None) -> subprocess.CompletedProcess:
    """lib_guards.sh 를 source 한 뒤 script 실행. 환경은 상속(uv·psql 경로 보존)."""
    env = dict(os.environ)
    env.update({"KR_REPO": str(REPO)})
    env.update(_pg_env())
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        ["bash", "-c", f"source '{GUARDS}'\n{script}"],
        capture_output=True, text=True, env=env,
    )


# ─── ELTD 캐시 읽기 (감시 경로 — KRX 접촉 0이어야 함) ─────────────────

def test_eltd_cached_latest_never_runs_python():
    """감시 경로가 Python 을 태우면 pykrx import 로 KRX 로그인 POST 가 나간다.

    trading_calendar:10 → ohlcv/fetch.py:9 → pykrx → webio.py:12 build_krx_session().
    """
    r = run_guard("declare -f eltd_cached_latest")
    body = r.stdout
    assert body.strip(), f"함수가 정의되지 않았다 stderr={r.stderr!r}"
    for forbidden in ("uv run", "python", "pykrx"):
        assert forbidden not in body, (
            f"eltd_cached_latest 가 {forbidden!r} 를 호출한다 — KRX 접촉 위험"
        )


def test_eltd_cached_latest_reports_value_and_age(tmp_path):
    """최신 1건과 나이를 반환한다 — 정확일치 키가 아니어야 한다(D+1 오전 커버리지)."""
    cache = tmp_path / "eltd.cache"
    cache.write_text("2026-06-09:post|2026-06-09\n2026-06-10:post|2026-06-10\n")
    r = run_guard("eltd_cached_latest", {"ELTD_CACHE": str(cache)})
    out = r.stdout.split()
    assert out and out[0] == "2026-06-10", f"stdout={r.stdout!r} stderr={r.stderr!r}"
    assert int(out[1]) >= 0


def test_eltd_cached_latest_rejects_corrupt(tmp_path):
    """손상된 캐시는 미스로 취급한다 — 잘못된 날짜를 감시에 넘기지 않는다."""
    cache = tmp_path / "eltd.cache"
    cache.write_bytes(b"\xff\xfe garbage\n")
    r = run_guard("eltd_cached_latest && echo HIT || echo MISS", {"ELTD_CACHE": str(cache)})
    assert "MISS" in r.stdout, f"stdout={r.stdout!r}"


def test_eltd_cached_latest_misses_when_absent(tmp_path):
    """캐시 파일이 없으면 미스."""
    r = run_guard("eltd_cached_latest && echo HIT || echo MISS",
                  {"ELTD_CACHE": str(tmp_path / "nope.cache")})
    assert "MISS" in r.stdout, f"stdout={r.stdout!r}"


def test_lib_guards_survives_unset_home():
    """HOME 미설정 환경에서도 source 가 죽지 않는다(set -u + plist 에 HOME 없음)."""
    env = {k: v for k, v in os.environ.items() if k != "HOME"}
    env["KR_REPO"] = str(REPO)
    r = subprocess.run(
        ["bash", "-c", f"source '{GUARDS}'\necho REACHED_END"],
        capture_output=True, text=True, env=env,
    )
    assert "REACHED_END" in r.stdout, f"source 실패 stderr={r.stderr!r}"


# ─── 시도 상한 ─────────────────────────────────────────────────────

@pytest.fixture
def runs_conn():
    """kr_test 의 pipeline_runs 에서 이 테스트가 쓰는 파이프라인 행만 정리."""
    if not TEST_DSN:
        pytest.skip("TEST_DATABASE_URL 미설정")
    with psycopg.connect(TEST_DSN) as conn:
        conn.execute("DELETE FROM pipeline_runs WHERE pipeline='guardtest'")
        conn.commit()
        yield conn
        conn.execute("DELETE FROM pipeline_runs WHERE pipeline='guardtest'")
        conn.commit()


_DAY_START = "date_trunc('day', now())"
# 당일 창을 벗어나지 않는 '방금' — 자정 직후에도 안전
_RECENT = "GREATEST(date_trunc('day', now()), now() - interval '1 hour')"


def _insert_at(conn, offset_sql: str, status: str = "failed"):
    """당일 창(date_trunc('day', now()))에 앵커해서 삽입.

    `now() - N hours` 로 시드하면 게이트 창(당일 00시 기준)을 자정 근처에서 벗어나
    시각 의존 flaky 가 된다.
    """
    conn.execute(
        "INSERT INTO pipeline_runs (pipeline, mode, started_at, status) "
        f"VALUES ('guardtest','incremental', {offset_sql}, %s)",
        (status,),
    )
    conn.commit()


def _kr_db() -> dict:
    return {"KR_DB": KR_TEST_DB}


def test_attempt_allowed_when_no_history(runs_conn):
    r = run_guard("attempt_allowed guardtest && echo ALLOW || echo BLOCK", _kr_db())
    assert "ALLOW" in r.stdout, f"stdout={r.stdout!r} stderr={r.stderr!r}"


def test_attempt_blocked_within_gap(runs_conn):
    """직전 시도가 1시간 이내면 간격 백오프로 차단(어느 시각에 돌려도 성립)."""
    _insert_at(runs_conn, _RECENT)
    r = run_guard("attempt_allowed guardtest 9 14400 && echo ALLOW || echo BLOCK", _kr_db())
    assert "BLOCK" in r.stdout, f"stdout={r.stdout!r} stderr={r.stderr!r}"


def test_attempt_allowed_below_cap_when_gap_disabled(runs_conn):
    """상한 미달 + 간격 제한 없음이면 허용 — 상한 카운트 경로만 검증."""
    _insert_at(runs_conn, _DAY_START)
    r = run_guard("attempt_allowed guardtest 2 0 && echo ALLOW || echo BLOCK", _kr_db())
    assert "ALLOW" in r.stdout, f"stdout={r.stdout!r} stderr={r.stderr!r}"


def test_attempt_blocked_at_daily_cap(runs_conn):
    """상한 도달이면 간격과 무관하게 차단. 두 시드 모두 당일 창 안이라 시각 무관."""
    _insert_at(runs_conn, _DAY_START)
    _insert_at(runs_conn, f"{_DAY_START} + interval '1 minute'")
    r = run_guard("attempt_allowed guardtest 2 0 && echo ALLOW || echo BLOCK", _kr_db())
    assert "BLOCK" in r.stdout, f"stdout={r.stdout!r} stderr={r.stderr!r}"


def test_attempt_db_failure_exits_nonzero(runs_conn):
    """DB 장애는 상한 도달과 다르게 취급한다 — fail-closed 중단."""
    r = run_guard("echo BEFORE; attempt_allowed guardtest; echo RC=$?",
                  {"KR_DB": "kr_definitely_no_such_db"})
    assert "BEFORE" in r.stdout, f"부트스트랩 자체 실패 stderr={r.stderr!r}"
    assert "RC=" not in r.stdout, "DB 실패인데 계속 진행했다"
    assert r.returncode == 1, f"rc={r.returncode}"


# ─── 래퍼가 게이트를 실제로 호출하는지 ───────────────────────────────

@pytest.mark.parametrize("script,gate,runner", [
    ("evening_chain.sh", "attempt_allowed data_daily", "--chain=daily"),
    ("monthly_chain.sh", "attempt_allowed universe", "kr_pipeline.universe"),
    ("weekend_chain.sh", "attempt_allowed data_weekly", "--chain=weekly"),
])
def test_wrapper_gates_before_sweep(script, gate, runner):
    """게이트가 대량 호출 실행문보다 앞에 있어야 한다."""
    text = (LAUNCHD / script).read_text()
    assert gate in text, f"{script} 에 {gate} 게이트가 없다"
    assert text.find(gate) < text.find(runner), f"{script} 의 게이트가 실행문보다 뒤에 있다"


def test_weekend_chain_has_running_guard():
    """주봉 스윕에 running 가드가 있어야 한다(08-01 좌초 → 08-03 재스윕 실측)."""
    text = (LAUNCHD / "weekend_chain.sh").read_text()
    assert "has_running_recent data_weekly" in text


def test_no_hardcoded_db_name():
    """DB 이름이 하드코딩되어 있으면 KR_DB 로 테스트할 수 없다."""
    for f in LAUNCHD.glob("*.sh"):
        assert "psql -d kr_pipeline" not in f.read_text(), f"{f.name} 에 하드코딩"
