"""(#68 2단계) OpenDART API 호출 — 재무 주요계정·주식총수·공시목록(원공시)."""
from __future__ import annotations

import json
import urllib.parse
import urllib.request

_BASE = "https://opendart.fss.or.kr/api"


def _get(endpoint: str, **params) -> dict:
    q = urllib.parse.urlencode(params)
    with urllib.request.urlopen(f"{_BASE}/{endpoint}.json?{q}", timeout=20) as r:
        return json.load(r)


def fetch_single_account(key: str, corp_code: str, year: int, reprt: str) -> dict:
    """fnlttSinglAcnt — {status, list}."""
    return _get("fnlttSinglAcnt", crtfc_key=key, corp_code=corp_code,
                bsns_year=str(year), reprt_code=reprt)


def fetch_shares(key: str, corp_code: str, year: int, reprt: str) -> float | None:
    """stockTotqySttus — 보통주(주식 종류에 '보통' 포함) 발행총수. 실패 시 None."""
    resp = _get("stockTotqySttus", crtfc_key=key, corp_code=corp_code,
                bsns_year=str(year), reprt_code=reprt)
    if resp.get("status") != "000":
        return None
    rows = resp.get("list") or []
    pick = next((r for r in rows if "보통" in (r.get("se") or "")), None) or \
        (rows[0] if rows else None)
    if not pick:
        return None
    t = str(pick.get("istc_totqy") or "").replace(",", "").strip()
    try:
        v = float(t)
        return v if v > 0 else None
    except ValueError:
        return None


def fetch_disclosures(key: str, corp_code: str, bgn: str, end: str) -> list[dict]:
    """list — 정기공시(A) 전 항목 (페이지네이션 처리). 원공시 매칭 재료."""
    items: list[dict] = []
    page = 1
    while True:
        resp = _get("list", crtfc_key=key, corp_code=corp_code, bgn_de=bgn,
                    end_de=end, pblntf_ty="A", page_no=str(page), page_count="100")
        if resp.get("status") != "000":
            break
        items.extend(resp.get("list") or [])
        if page >= int(resp.get("total_page") or 1):
            break
        page += 1
    return items
