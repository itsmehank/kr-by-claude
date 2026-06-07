# tests/test_corporate_actions_dart_client.py
from datetime import date
from unittest.mock import patch, MagicMock

import pytest

from kr_pipeline.corporate_actions.dart_client import fetch_disclosures, DartApiError


def _mock_response(json_data):
    m = MagicMock()
    m.status_code = 200
    m.json.return_value = json_data
    m.raise_for_status = MagicMock()
    return m


def test_fetch_disclosures_single_page():
    """page 1 응답에 total_page=1 → 결과 반환."""
    response = _mock_response({
        "status": "000", "message": "정상",
        "total_count": 2, "total_page": 1, "page_no": 1,
        "list": [
            {"corp_code": "00126380", "report_nm": "주식분할결정", "rcept_no": "20240312000123", "rcept_dt": "20240312"},
            {"corp_code": "00126380", "report_nm": "사업보고서",   "rcept_no": "20240315000456", "rcept_dt": "20240315"},
        ],
    })
    with patch("kr_pipeline.corporate_actions.dart_client._http_get", return_value=response):
        result = fetch_disclosures("KEY", "00126380", date(2024, 3, 1), date(2024, 3, 31))
    assert len(result) == 2
    assert result[0]["report_nm"] == "주식분할결정"


def test_fetch_disclosures_paginates():
    """total_page=2 → 두 페이지 호출 후 합치기."""
    p1 = _mock_response({
        "status": "000", "total_count": 3, "total_page": 2, "page_no": 1,
        "list": [{"rcept_no": "1"}, {"rcept_no": "2"}],
    })
    p2 = _mock_response({
        "status": "000", "total_count": 3, "total_page": 2, "page_no": 2,
        "list": [{"rcept_no": "3"}],
    })
    with patch("kr_pipeline.corporate_actions.dart_client._http_get", side_effect=[p1, p2]):
        result = fetch_disclosures("KEY", "00126380", date(2024, 1, 1), date(2024, 12, 31))
    assert len(result) == 3
    assert [r["rcept_no"] for r in result] == ["1", "2", "3"]


def test_fetch_disclosures_no_data():
    """status=013 (조회 결과 없음) → 빈 리스트."""
    response = _mock_response({"status": "013", "message": "조회된 데이터가 없습니다."})
    with patch("kr_pipeline.corporate_actions.dart_client._http_get", return_value=response):
        result = fetch_disclosures("KEY", "00126380", date(2024, 1, 1), date(2024, 1, 31))
    assert result == []


def test_fetch_disclosures_invalid_key_raises():
    """status=010 (등록되지 않은 키) → DartApiError."""
    response = _mock_response({"status": "010", "message": "등록되지 않은 키입니다."})
    with patch("kr_pipeline.corporate_actions.dart_client._http_get", return_value=response):
        with pytest.raises(DartApiError, match="010"):
            fetch_disclosures("BAD_KEY", "00126380", date(2024, 1, 1), date(2024, 1, 31))


def test_fetch_disclosures_defaults_to_major_matters_type_B():
    """기본 pblntf_ty='B'(주요사항보고). 분할·합병·감자 등 기업행위 공시는 정기공시(A)가
    아니라 주요사항보고(B)에 있다. A 로 잘못 설정돼 corporate_actions 가 매번 0건이던
    버그 수정 (실측: 최근 60일 A=매칭0, B=매칭12)."""
    response = _mock_response({"status": "013"})
    with patch(
        "kr_pipeline.corporate_actions.dart_client._http_get", return_value=response
    ) as mock_get:
        fetch_disclosures("KEY", "00126380", date(2024, 1, 1), date(2024, 1, 31))
    args, _ = mock_get.call_args
    params = args[1]  # _http_get(url, params)
    assert params["pblntf_ty"] == "B"


def test_fetch_disclosures_explicit_pblntf_ty_honored():
    """명시한 pblntf_ty 는 그대로 사용."""
    response = _mock_response({"status": "013"})
    with patch(
        "kr_pipeline.corporate_actions.dart_client._http_get", return_value=response
    ) as mock_get:
        fetch_disclosures("KEY", "00126380", date(2024, 1, 1), date(2024, 1, 31), pblntf_ty="C")
    args, _ = mock_get.call_args
    assert args[1]["pblntf_ty"] == "C"
