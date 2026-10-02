"""launchd 래퍼 가드(lib_guards.sh) 검증 — bash 서브프로세스로 실행.

#92: KRX 접촉 빈도 제한이 회귀하지 않도록 고정한다. pykrx 는 호출하지 않는다.
"""
import os
import re
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


def _bash_cache_path(env_extra: dict | None = None, drop_home: bool = False) -> str:
    env = {k: v for k, v in os.environ.items() if not (drop_home and k == "HOME")}
    env["KR_REPO"] = str(REPO)
    env.pop("ELTD_CACHE", None)          # 기본값을 보려면 오버라이드를 걷어야 한다
    if env_extra:
        env.update(env_extra)
    r = subprocess.run(
        ["bash", "-c", f"source '{GUARDS}'\nprintf '%s' \"$ELTD_CACHE\""],
        capture_output=True, text=True, env=env,
    )
    return r.stdout.strip()


def _python_cache_path(drop_home: bool = False) -> str:
    env = {k: v for k, v in os.environ.items() if not (drop_home and k == "HOME")}
    env["KRX_ID"] = ""
    env["KRX_PW"] = ""
    env.pop("ELTD_CACHE", None)
    # pykrx 가 import 시 stdout 에 로그인 문구를 print 하므로 접두어로 골라낸다
    r = subprocess.run(
        [os.sys.executable, "-c",
         "from kr_pipeline.common.trading_calendar import eltd_cache_path;"
         "print('PATH=' + str(eltd_cache_path()))"],
        capture_output=True, text=True, env=env, cwd=str(REPO),
    )
    for line in r.stdout.splitlines():
        if line.startswith("PATH="):
            return line[len("PATH="):].strip()
    raise AssertionError(f"경로를 얻지 못했다 stdout={r.stdout!r} stderr={r.stderr!r}")


@pytest.mark.parametrize("drop_home", [False, True], ids=["home-set", "home-unset"])
def test_bash_and_python_cache_paths_agree(drop_home):
    """bash(감시)와 Python(체인)의 기본 캐시 경로가 같아야 한다.

    갈리면 체인이 쓴 캐시를 감시가 못 읽어 **영구 미스**가 되고 결측 감시가 조용히 죽는다.
    Python 의 Path.expanduser() 는 HOME 이 없으면 passwd 로 폴백하므로 bash 도 `cd ~` 로
    같은 폴백을 해야 한다(초안의 `${HOME:-/tmp}` 는 여기서 갈렸다).
    """
    assert _bash_cache_path(drop_home=drop_home) == _python_cache_path(drop_home=drop_home)


def test_attempt_allowed_fails_closed_on_bad_args(runs_conn):
    """상한 인자가 비숫자면 차단한다.

    `[ x -ge y ]` 는 비숫자에서 오류로 false 가 되어 fail-**open** 한다 —
    재차단을 막는 가드가 오타 하나로 조용히 무력화되면 안 된다.
    """
    for bad in ("attempt_allowed guardtest abc 0", "attempt_allowed guardtest 2 xyz"):
        r = run_guard(f"{bad} && echo ALLOW || echo BLOCK", _kr_db())
        assert "BLOCK" in r.stdout, f"{bad!r} 가 ALLOW 됐다 stdout={r.stdout!r}"


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


# ─── #92 3차 검토 반영: 신선도 판정 · 파싱 방어 · 기본값 고정 ─────────

def _set_mtime(path: Path, dt) -> None:
    ts = dt.timestamp()
    os.utime(path, (ts, ts))


def test_eltd_cache_fresh_today_boundary(tmp_path):
    """오늘 INTRADAY_LOCK_END(20:25, =Python CLOSE_BUFFER) 이후 기록만 fresh — 그 전 기록은 D:pre(값=어제)라 오늘 판정에 쓰면 결측이 통과한다(H-1·#219 리뷰)."""
    from datetime import datetime, time, timedelta, date as _date

    cache = tmp_path / "eltd.cache"
    cache.write_text("2026-08-03:post|2026-08-03\n")
    env = {"ELTD_CACHE": str(cache)}
    cases = [
        (datetime.combine(_date.today(), time(20, 25)), "FRESH"),              # 오늘 20:25 = INTRADAY_LOCK_END(=CLOSE_BUFFER)
        (datetime.combine(_date.today(), time(20, 24)), "STALE"),              # 그 직전 — Python cache_key 는 아직 D:pre(값=어제)
        (datetime.combine(_date.today(), time(18, 0)), "STALE"),               # 구 17:00 기준이면 FRESH 였던 창(#219 리뷰)
        (datetime.combine(_date.today(), time(10, 0)), "STALE"),               # 오늘 아침
        (datetime.combine(_date.today() - timedelta(days=1), time(20, 30)), "STALE"),  # 어제 저녁
    ]
    for dt, want in cases:
        _set_mtime(cache, dt)
        r = run_guard("eltd_cache_fresh_today && echo FRESH || echo STALE", env)
        assert want in r.stdout, f"mtime={dt} 기대={want} 실제={r.stdout!r}"
    r = run_guard("eltd_cache_fresh_today && echo FRESH || echo STALE",
                  {"ELTD_CACHE": str(tmp_path / "absent.cache")})
    assert "STALE" in r.stdout, "캐시 없음이 fresh 로 판정됐다"


# 요일별 결정론 검증 — 함수 내부의 `date` 를 셰도잉해 "오늘"을 고정한다.
# (실행 요일에 따라 결과가 달라지면 flaky — 월요일 오탐이 3차 커밋에서 이렇게 숨었다)
_DATE_SHADOW = """date() {{
  case "$*" in
    "+%w") echo {dow};;
    "-j -v-1d +%F") echo {d1};;
    "-j -v-3d +%F") echo {d3};;
    *) command date "$@";;
  esac
}}
eltd_cache_older_than_prev_workday_close && echo OLD || echo OK"""


def _shadow(dow: int, d1: str, d3: str) -> str:
    return _DATE_SHADOW.format(dow=dow, d1=d1, d3=d3)


def test_older_than_prev_workday_close_monday_normal_weekend_is_ok(tmp_path):
    """정상 주말(금 20:30 기록) 뒤 월요일 아침 → 오탐 없어야 한다.

    기준이 단순 '어제(일요일) 17시'면 금 18:30 < 일 17:00 이라 매주 월요일 오탐
    (4차 전체검토 실측 재현). 월요일의 기준은 직전 평일 = 금요일 20:25 다.
    """
    cache = tmp_path / "eltd.cache"
    cache.write_text("2026-08-07:post|2026-08-07\n")
    _set_mtime(cache, __import__("datetime").datetime(2026, 8, 7, 20, 30))  # 금 20:30
    r = run_guard(_shadow(1, "2026-08-09", "2026-08-07"), {"ELTD_CACHE": str(cache)})
    assert "OK" in r.stdout, f"정상 주말이 월요일 아침 오탐: {r.stdout!r} {r.stderr!r}"


def test_older_than_prev_workday_close_monday_catches_weekend_outage(tmp_path):
    """목요일에 멈춘 캐시 → 월요일 아침 알림(금요일 저녁까지 통째 결측)."""
    cache = tmp_path / "eltd.cache"
    cache.write_text("2026-08-06:post|2026-08-06\n")
    _set_mtime(cache, __import__("datetime").datetime(2026, 8, 6, 20, 30))  # 목 20:30
    r = run_guard(_shadow(1, "2026-08-09", "2026-08-07"), {"ELTD_CACHE": str(cache)})
    assert "OLD" in r.stdout, f"주말 통째 결측을 월요일 아침에 못 잡음: {r.stdout!r}"


def test_older_than_prev_workday_close_tuesday(tmp_path):
    """화요일: 월 20:30 기록 = 정상(OK), 금 20:30 에 멈춤 = 월요일 결측(OLD)."""
    from datetime import datetime as _dt

    cache = tmp_path / "eltd.cache"
    cache.write_text("2026-08-10:post|2026-08-10\n")
    env = {"ELTD_CACHE": str(cache)}
    _set_mtime(cache, _dt(2026, 8, 10, 20, 30))          # 월 20:30 — 정상
    r = run_guard(_shadow(2, "2026-08-10", "2026-08-08"), env)
    assert "OK" in r.stdout, f"정상 화요일 아침 오탐: {r.stdout!r}"
    _set_mtime(cache, _dt(2026, 8, 7, 20, 30))           # 금 20:30 — 월요일 결측
    r = run_guard(_shadow(2, "2026-08-10", "2026-08-08"), env)
    assert "OLD" in r.stdout, f"월요일 결측을 화요일 아침에 못 잡음: {r.stdout!r}"


def test_older_than_prev_workday_close_absent_cache_is_ok(tmp_path):
    """캐시 없음은 '오래됨'으로 치지 않는다 — 재개 당일 아침 오탐 방지."""
    r = run_guard("eltd_cache_older_than_prev_workday_close && echo OLD || echo OK",
                  {"ELTD_CACHE": str(tmp_path / "absent.cache")})
    assert "OK" in r.stdout, "캐시 없음이 OLD 로 판정 — 재개 당일 아침 오탐"


def test_attempt_allowed_default_values_pinned():
    """기본값(하루 2회 · 간격 6h)이 바뀌면 테스트가 알아챈다 — 호출부는 인자 없이 부른다."""
    text = GUARDS.read_text()
    assert "ATTEMPT_MAX_DEFAULT:-2}" in text, "기본 상한이 2가 아니다"
    assert "ATTEMPT_GAP_DEFAULT:-21600}" in text, "기본 간격이 6h(21600)가 아니다"


def test_attempt_allowed_no_args_uses_defaults(runs_conn):
    """인자 없는 호출(evening_chain 의 실제 형태)이 기본 상한 2를 적용한다."""
    _insert_at(runs_conn, _DAY_START)
    _insert_at(runs_conn, f"{_DAY_START} + interval '1 minute'")
    r = run_guard("attempt_allowed guardtest && echo ALLOW || echo BLOCK", _kr_db())
    assert "BLOCK" in r.stdout, f"stdout={r.stdout!r} stderr={r.stderr!r}"


def test_attempt_allowed_takes_last_line_of_db_output(runs_conn):
    """psql 경고가 결과보다 먼저 와도(실측 순서) 마지막 줄의 결과를 파싱한다(H-2).

    첫 줄을 취하면 경고 문장을 숫자 비교해 오류 → false → **무제한 허용**이 됐다.
    """
    stub_ok = (
        'db_query() { printf "WARNING:  there is no transaction in progress\\n'
        'ROLLBACK\\n0 999999\\n"; }\n'
        "attempt_allowed guardtest && echo ALLOW || echo BLOCK"
    )
    r = run_guard(stub_ok, _kr_db())
    assert "ALLOW" in r.stdout, f"오염됐지만 결과는 0회 — 허용이어야 함: {r.stdout!r}"

    stub_cap = (
        'db_query() { printf "WARNING:  junk\\n2 999999\\n"; }\n'
        "attempt_allowed guardtest && echo ALLOW || echo BLOCK"
    )
    r = run_guard(stub_cap, _kr_db())
    assert "BLOCK" in r.stdout, f"상한 도달인데 허용됐다(fail-open): {r.stdout!r}"


def test_attempt_allowed_garbage_output_fails_closed(runs_conn):
    """마지막 줄까지 비숫자면 DB 실패와 동일하게 중단한다 — 조용한 허용 금지."""
    stub = (
        'db_query() { printf "total garbage output\\n"; }\n'
        "attempt_allowed guardtest; echo RC=$?"
    )
    r = run_guard(stub, _kr_db())
    assert "RC=" not in r.stdout, f"오염 출력인데 계속 진행: {r.stdout!r}"
    assert r.returncode == 1


# ─── PR#93 리뷰 반영: fall-through 봉쇄 · 자정 seam ──────────────────

@pytest.mark.parametrize("script,gate", [
    ("weekend_chain.sh", "has_running_recent data_weekly"),
    ("weekend_chain.sh", "attempt_allowed data_weekly"),
    ("monthly_chain.sh", "attempt_allowed universe"),
])
def test_blocked_branches_halt_the_chain(script, gate):
    """차단 분기는 후속 단계로 fall-through 하면 안 된다(PR#93 리뷰 H-1·H-2).

    weekend: 주봉 미완 상태로 LLM 분류가 실행되면 불완전 분류가 그 주의 최신으로
    박제된다(weekend.py 계약). monthly: 매핑이 universe 를 앞지르면 헤더가 경고한
    "역순이면 한 달 누락"이 실제로 일어난다. 각 분기 직후 5줄 안에 exit 0 이 있어야 한다.
    """

    lines = (LAUNCHD / script).read_text().splitlines()
    idx = next(i for i, ln in enumerate(lines) if gate in ln and ("elif" in ln or "if" in ln))
    # ⚠️ 주석을 제외한 **코드 줄**에서 exit 0 문을 찾는다(8회차 리뷰) — 분기 옆의
    # "exit 0 필수" 설명 주석이 문자열 매치돼, 실제 exit 문을 지워도 통과하는
    # 자기-무력화가 실측으로 재현됐다(3케이스 중 2케이스).
    code = [ln for ln in lines[idx:idx + 8] if not ln.lstrip().startswith("#")]
    assert any(re.match(r"\s*exit 0\s*$", ln) for ln in code), (
        f"{script} 의 {gate!r} 분기가 fall-through 한다(코드 줄에 exit 0 없음):\n"
        + "\n".join(code)
    )


def test_attempt_gap_survives_midnight(runs_conn):
    """어제 밤 시도 + 자정 직후 발화 = 간격 백오프가 여전히 차단한다(PR#93 리뷰 M-2).

    count·age 둘 다 당일 필터면 자정에 간격이 리셋돼 35분 간격 재스윕이 통과한다.
    age 를 전역 최근 시도 기준으로 바꿔, '35분 전' 행이 어제 날짜여도(자정 직후 실행)
    차단됨을 고정한다. now()-35min 은 자정을 걸치든 아니든 항상 간격 내다 — 시각 무관.
    """
    runs_conn.execute(
        "INSERT INTO pipeline_runs (pipeline, mode, started_at, status) "
        "VALUES ('guardtest','incremental', now() - interval '35 minutes', 'failed')"
    )
    runs_conn.commit()
    r = run_guard("attempt_allowed guardtest 9 21600 && echo ALLOW || echo BLOCK", _kr_db())
    assert "BLOCK" in r.stdout, f"35분 전 시도인데 통과(자정 seam): {r.stdout!r} {r.stderr!r}"


# ── (#207 2026-09-29) 잠정값 창 자물쇠 09:00~20:25 + schedule.env 단일 정의 ──────────────
def _lock_shadow(dow: int, hh: str, mm: str) -> str:
    return f"""date() {{
  case "$1" in
    +%w) echo {dow};;
    +%H) echo {hh};;
    +%M) echo {mm};;
    *) command date "$@";;
  esac
}}"""


@pytest.mark.parametrize("hh,mm,blocked", [
    ("08", "59", False),   # 개장 전 허용
    ("09", "00", True),    # 장중
    ("17", "19", True),    # 09-29 사고 시각 — 애프터마켓 잠정값 창(구 가드는 허용했음)
    ("20", "24", True),    # 확정 하한(20:20)+여유 직전
    ("20", "25", False),   # 창 종료
    ("20", "30", False),   # 정규 발화
    ("21", "47", False),
])
def test_intraday_lock_blocks_provisional_window_until_2025(hh, mm, blocked):
    r = run_guard(_lock_shadow(2, hh, mm) + "\nintraday_lock && echo BLOCKED || echo ALLOWED")
    assert r.stdout.strip() == ("BLOCKED" if blocked else "ALLOWED"), r.stderr


def test_intraday_lock_weekend_exempt():
    r = run_guard(_lock_shadow(6, "12", "00") + "\nintraday_lock && echo BLOCKED || echo ALLOWED")
    assert r.stdout.strip() == "ALLOWED"


def test_schedule_env_single_source_is_consistent():
    """schedule.env 값이 서로 정합 — 자물쇠 종료 < 발화 시각 ≤ 감시 판정, 대입문만 포함."""
    env_path = REPO / "scripts" / "launchd" / "schedule.env"
    text = env_path.read_text(encoding="utf-8")
    for line in text.splitlines():
        s = line.strip()
        assert not s or s.startswith("#") or "=" in s.split("#")[0], line
    r = run_guard('echo "$EVENING_HOUR $EVENING_MIN $INTRADAY_LOCK_END_HOUR $INTRADAY_LOCK_END_MIN $WATCH_DUE_HOUR $WAKE_TIME"')
    eh, em, lh, lm, wd, wake = r.stdout.split()
    assert (int(lh), int(lm)) < (int(eh), int(em)) <= (int(wd), 0)
    assert int(wd) - int(eh) >= 2                       # 데이터 체인 최대 2h10m 실측 여유
    assert wake < f"{eh}:{em}:00"                       # 기상은 발화 전


def test_close_buffer_equals_intraday_lock_end_and_precedes_evening_fire():
    """20:25 는 Python(market_hours.CLOSE_BUFFER)과 셸(schedule.env INTRADAY_LOCK_END) 두 곳에 적힌다 — 한쪽만 개정(Q-5b 20:55)하면
    20:30 발화가 ELTD=어제로 '몫 완료 skip' 하는 무음 결측(#219 리뷰). 둘을 같게, 그리고 발화 시각보다 앞서게 고정한다."""
    from datetime import time as _time
    from kr_pipeline.common.market_hours import CLOSE_BUFFER          # stdlib 전용 모듈 — pykrx 미로드
    r = run_guard('echo "$EVENING_HOUR $EVENING_MIN $INTRADAY_LOCK_END_HOUR $INTRADAY_LOCK_END_MIN"')
    eh, em, lh, lm = (int(x) for x in r.stdout.split())
    assert _time(lh, lm) == CLOSE_BUFFER
    assert CLOSE_BUFFER < _time(eh, em)


def test_close_buffer_helpers_decimal_and_sql_interval():
    """INTRADAY_LOCK_END 를 쓰는 셸 헬퍼: 선행 0(08) 을 8진수로 읽지 않고(printf %02d — 2차 리뷰 실측 'invalid number'),
    SQL interval 문자열은 같은 상수에서 나온다(evening_chain 멱등 경계·watch miss.eval 경계의 구 '17 hours' 대체)."""
    r = run_guard('echo "$(_close_buffer_hms) | $(close_buffer_sql_interval)"')
    assert r.stdout.strip() == "20:25:00 | interval '20 hours 25 minutes'", r.stdout + r.stderr
    r = run_guard('INTRADAY_LOCK_END_HOUR=20; INTRADAY_LOCK_END_MIN=08; echo "$(_close_buffer_hms) | $(close_buffer_sql_interval)"')
    assert r.stdout.strip() == "20:08:00 | interval '20 hours 8 minutes'", r.stdout + r.stderr


def test_no_hardcoded_17_hour_boundary_in_launchd_scripts():
    """구 CLOSE_BUFFER 17:00 의 잔존 리터럴 금지 — 코드 줄 한정(주석 제외). #219 2차 리뷰: evening_chain·watch 의 interval '17 hours'."""
    for path in sorted((REPO / "scripts" / "launchd").glob("*.sh")):
        for n, line in _code_lines(path):
            assert "17 hours" not in line and "17:00" not in line, f"{path.name}:{n}: {line.strip()}"


_VAR_NONASCII = re.compile(r"\$[A-Za-z_][A-Za-z0-9_]*[^\x00-\x7F]")


def _code_lines(path: Path):
    """주석 줄 제외(bash 는 주석에서 확장하지 않음)."""
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.lstrip().startswith("#"):
            yield n, line


def test_no_variable_immediately_followed_by_non_ascii_in_shell_scripts():
    """`$VAR<비ASCII>` 는 UTF-8 로케일 bash 3.2 에서 비ASCII 바이트가 변수명에 붙어 set -u unbound 로 죽는다
    (2026-09-29 20:35 수동 fallback 실패; launchd 는 C 로케일이라 잠복). 한글 음절뿐 아니라 —·漢·ㄱ·전각 전부.
    범위 = scripts/ 전체(backfill_132.sh 등 수동 실행 스크립트 포함). 반드시 `${VAR}…`."""
    scripts = sorted((REPO / "scripts").rglob("*.sh"))
    assert scripts, "scripts/**/*.sh 가 비어 있음 — 경로 확인"
    bad = [f"{sh.relative_to(REPO)}:{n}: {line.strip()[:80]}"
           for sh in scripts for n, line in _code_lines(sh) if _VAR_NONASCII.search(line)]
    assert bad == [], bad


def test_evening_chain_log_lines_expand_under_utf8_locale():
    """실제 스크립트의 log 줄을 추출해 ko_KR.UTF-8 + set -u 로 실행. 양성 대조 = 옛 표기(`$NIND행`)는 rc 127."""
    env = {**os.environ, "LANG": "ko_KR.UTF-8", "LC_ALL": "ko_KR.UTF-8"}
    # bash 가 잘린 변수명(비ASCII 바이트 일부)을 stderr 에 내보내므로 디코딩은 errors="replace"
    control = subprocess.run(["bash", "-u", "-c", 'NIND=0; echo "지표 $NIND행"'], capture_output=True,
                             encoding="utf-8", errors="replace", env=env)
    if control.returncode != 127:
        pytest.skip("이 호스트의 bash/로케일은 재현되지 않음(양성 대조 실패)")
    script = LAUNCHD / "evening_chain.sh"
    log_lines = [line.strip() for _n, line in _code_lines(script) if "NIND" in line and line.lstrip().startswith("log ")]
    assert len(log_lines) >= 3, log_lines
    body = "log() { echo \"$*\"; }; ELTD=2026-09-29; NIND=2552\n" + "\n".join(log_lines)
    r = subprocess.run(["bash", "-u", "-c", body], capture_output=True, encoding="utf-8", errors="replace", env=env)
    assert r.returncode == 0, r.stderr
    assert "2552행" in r.stdout, r.stdout
