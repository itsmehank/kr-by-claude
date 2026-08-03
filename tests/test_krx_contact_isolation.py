"""pytest 실행이 KRX 로 나가지 않음을 고정 (#92 차단 재발 방지).

pykrx 는 import 시점에 build_krx_session() 을 실행해 KRX_ID/KRX_PW 로 로그인
POST 를 보낸다(pykrx/website/comm/webio.py:12). 자격증명이 falsy 면 HTTP 없이
None 을 반환하므로(comm/auth.py:176-181) conftest 가 pykrx import 전에 값을 비운다.

pop 이 아니라 빈 문자열이어야 한다 — kr_pipeline/common/config.py:5 의 load_dotenv()
가 "키가 없으면" 복원하기 때문(dotenv/main.py:105).

이 파일이 지키는 계약이 깨지면 `uv run pytest tests/` 를 돌릴 때마다 실제 KRX 로그인
요청이 나가고, 그것이 08-01 IP 차단의 접촉원 중 하나였다.
"""
import os
import tomllib
from pathlib import Path

import pytest

PYPROJECT = Path(__file__).parent.parent / "pyproject.toml"

# KR_ALLOW_KRX=1 은 격리를 의도적으로 해제한 세션이므로 전부 skip.
# 특히 마지막 테스트는 get_auth_session() 이 호출 시점에 os.getenv 를 다시 읽어
# build_krx_session 을 재시도하므로(auth.py:208-223), 해제 세션에서 돌리면
# 실제 로그인 POST 가 나간다.
pytestmark = pytest.mark.skipif(
    os.environ.get("KR_ALLOW_KRX") == "1", reason="KR_ALLOW_KRX=1 — 격리 해제 세션"
)


def _ini() -> dict:
    with PYPROJECT.open("rb") as f:
        return tomllib.load(f)["tool"]["pytest"]["ini_options"]


def test_krx_credentials_are_blank():
    """자격증명이 빈 값이다 — import 시 로그인 요청이 나가지 않는다."""
    assert not os.environ.get("KRX_ID"), "KRX_ID 가 살아 있다 — 로그인 요청이 나간다"
    assert not os.environ.get("KRX_PW"), "KRX_PW 가 살아 있다 — 로그인 요청이 나간다"


def test_krx_keys_still_present_so_dotenv_cannot_restore():
    """키 자체는 남아 있어야 한다 — 없으면 load_dotenv() 가 되살린다."""
    assert "KRX_ID" in os.environ, "키가 제거됨 — config.py 의 load_dotenv 가 복원한다"
    assert "KRX_PW" in os.environ, "키가 제거됨 — config.py 의 load_dotenv 가 복원한다"


def test_dotenv_reload_does_not_restore_credentials():
    """config 를 import 해 load_dotenv 가 다시 돌아도 자격증명이 비어 있다."""
    from dotenv import load_dotenv

    from kr_pipeline.common import config  # noqa: F401 — import 부작용 확인용

    load_dotenv()
    assert not os.environ.get("KRX_ID"), "load_dotenv 가 KRX_ID 를 복원했다"
    assert not os.environ.get("KRX_PW"), "load_dotenv 가 KRX_PW 를 복원했다"


def test_krx_marker_declared_and_excluded_by_default():
    """krx 마커가 선언되고 기본 제외된다."""
    ini = _ini()
    assert any(m.startswith("krx:") for m in ini["markers"]), f"markers={ini['markers']}"
    assert "not krx" in ini["addopts"], f"addopts={ini['addopts']!r}"


def test_krx_marker_actually_applied_to_this_session(request):
    """설정 파일이 아니라 **실행 중인 세션**에 실제로 적용됐는지 확인.

    TOML 만 읽으면 CLI 오버라이드나 잔존 pytest.ini 를 못 잡는다.
    """
    assert "not krx" in (request.config.getoption("-m") or ""), (
        f"-m={request.config.getoption('-m')!r} — krx 제외가 세션에 적용되지 않았다"
    )


def test_integration_db_tests_not_excluded():
    """DB 전용 integration 테스트 13개는 기본 실행에서 제외되지 않는다."""
    ini = _ini()
    assert "not integration" not in ini["addopts"], (
        "integration 통째 제외는 Postgres 전용 테스트 13개를 죽인다 — krx 마커만 제외할 것"
    )


def test_pykrx_session_is_none_after_import():
    """pykrx 를 import 해도 세션이 없다(= 로그인 요청 없음)."""
    from pykrx.website.comm.auth import get_auth_session

    assert get_auth_session() is None
