# kr_pipeline/corporate_actions/dart_client.py
"""DART API HTTP wrapper. retry 포함, 페이지네이션 자동 처리."""
from datetime import date
import logging

import requests
from tenacity import retry, stop_after_attempt, wait_exponential_jitter


log = logging.getLogger("kr_pipeline.corporate_actions.dart_client")

BASE_URL = "https://opendart.fss.or.kr/api"
DEFAULT_PAGE_COUNT = 100   # DART 최대


class DartApiError(Exception):
    """DART API 에서 에러 status 반환 시."""
    pass


@retry(stop=stop_after_attempt(3), wait=wait_exponential_jitter(initial=1, max=8), reraise=True)
def _http_get(url: str, params: dict, timeout: int = 30) -> requests.Response:
    """HTTP GET with retry. raise_for_status 호출."""
    response = requests.get(url, params=params, timeout=timeout)
    response.raise_for_status()
    return response


def fetch_disclosures(
    api_key: str,
    corp_code: str | None,
    start_date: date,
    end_date: date,
    pblntf_ty: str = "B",
) -> list[dict]:
    """[start_date..end_date] 공시 목록 조회. 페이지네이션 자동.

    corp_code=None 이면 파라미터 자체를 생략 — DART 가 전 회사의 공시를 반환한다
    (기간 일괄 조회). 종목별 반복 호출(N+1) 대신 이 모드로 한 번에 받아
    corp_code→ticker 역매핑하는 것이 정상 경로.

    pblntf_ty 기본값 'B'(주요사항보고): 분할·병합·합병·감자 등 기업행위 공시는
    정기공시('A': 사업/분기보고서)가 아니라 주요사항보고('B')에 실린다. 과거 'A' 기본값
    탓에 parser 가 찾을 공시가 안 들어와 corporate_actions 가 매번 0건이었음
    (2026-06-07 확인: 최근 60일 A=parser매칭 0, B=12). 따라서 'B' 가 정본.

    Return: DART 응답의 list 항목들 (corp_code, rcept_no, report_nm, rcept_dt 등).
    Empty list 인 경우: 응답 status=013 (조회 결과 없음).
    Raise DartApiError if status not in ("000", "013").
    """
    all_items = []
    page_no = 1
    while True:
        params = {
            "crtfc_key": api_key,
            "bgn_de": start_date.strftime("%Y%m%d"),
            "end_de": end_date.strftime("%Y%m%d"),
            "pblntf_ty": pblntf_ty,
            "page_no": page_no,
            "page_count": DEFAULT_PAGE_COUNT,
        }
        if corp_code is not None:
            params["corp_code"] = corp_code
        response = _http_get(f"{BASE_URL}/list.json", params)
        data = response.json()
        status = data.get("status")

        if status == "013":
            # 조회 결과 없음
            return all_items

        if status != "000":
            raise DartApiError(f"DART API error status={status} message={data.get('message')}")

        items = data.get("list", [])
        all_items.extend(items)

        total_page = data.get("total_page", 1)
        if page_no >= total_page:
            break
        page_no += 1

    return all_items
