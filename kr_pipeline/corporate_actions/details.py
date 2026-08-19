# kr_pipeline/corporate_actions/details.py
"""(#114 경로B) DART 주요사항 구조화 상세 — 증자·감자 기준일/비율/방식 직취.

엔드포인트 4종(실검증 2026-08-19): 유상증자 piicDecsn(`ic_mthn` 으로 주주배정/
3자배정/일반공모 판별)·무상증자 fricDecsn(`nstk_asstd` 기준일, `nstk_ascnt_ps_ostk`
1주당 배정)·유무상 pifricDecsn·감자 crDecsn(`cr_std` 기준일, `cr_rt_ostk` 비율%).
액면분할/병합은 구조화 API 부재 — v2(가격 갭+주식수)가 담당(커버리지 표 참조).
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime

from psycopg import Connection
from psycopg.types.json import Jsonb

from kr_pipeline.corporate_actions.dart_client import BASE_URL, _http_get

ENDPOINTS = ("piicDecsn", "fricDecsn", "pifricDecsn", "crDecsn")


def parse_kr_date(s: str | None) -> date | None:
    """'2026년 07월 27일' → date. '-'·None·형식 불일치 → None."""
    if not s or not isinstance(s, str):
        return None
    m = re.search(r"(\d{4})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일", s)
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def parse_num(s: str | None) -> float | None:
    """'29,731,461' → 29731461.0. '-'·None·비수치 → None."""
    if s is None or not isinstance(s, str):
        return None
    t = s.replace(",", "").strip()
    if not t or t == "-":
        return None
    try:
        return float(t)
    except ValueError:
        return None


def normalize(endpoint: str, item: dict) -> dict:
    """응답 항목 → {record_date, ratio, method}. 실패 필드는 None(원문은 payload)."""
    rd = ratio = method = None
    if endpoint == "fricDecsn":
        rd = parse_kr_date(item.get("nstk_asstd"))
        ratio = parse_num(item.get("nstk_ascnt_ps_ostk"))
    elif endpoint == "piicDecsn":
        rd = parse_kr_date(item.get("nstk_asstd"))
        method = item.get("ic_mthn")
        new = parse_num(item.get("nstk_ostk_cnt"))
        base = parse_num(item.get("bfic_tisstk_ostk"))
        if new is not None and base:
            ratio = new / base
    elif endpoint == "crDecsn":
        rd = parse_kr_date(item.get("cr_std"))
        method = item.get("cr_mth")
        pct = parse_num(item.get("cr_rt_ostk"))
        if pct is not None:
            ratio = pct / 100.0
    elif endpoint == "pifricDecsn":
        # 유무상 병행 — 필드 접두가 문서마다 달라 payload 우선, 공통 후보만 시도
        rd = (parse_kr_date(item.get("nstk_asstd"))
              or parse_kr_date(item.get("piic_nstk_asstd"))
              or parse_kr_date(item.get("fric_nstk_asstd")))
        method = item.get("ic_mthn")
    return {"record_date": rd, "ratio": ratio, "method": method}


def fetch_details(api_key: str, corp_code: str, endpoint: str,
                  bgn_de: str, end_de: str) -> list[dict]:
    """단일 엔드포인트 조회. status 013(없음) → []. 그 외 비정상 → raise."""
    resp = _http_get(f"{BASE_URL}/{endpoint}.json", {
        "crtfc_key": api_key, "corp_code": corp_code,
        "bgn_de": bgn_de, "end_de": end_de})
    d = resp.json()
    status = d.get("status")
    if status == "013":
        return []
    if status != "000":
        raise RuntimeError(f"DART {endpoint} status={status} {d.get('message')}")
    return d.get("list", [])


def upsert_details(conn: Connection, ticker: str, endpoint: str,
                   items: list[dict]) -> int:
    """멱등 적재 — (ticker, rcept_no, endpoint) 충돌 시 무시. 반환 = 신규 수."""
    n = 0
    with conn.cursor() as cur:
        for it in items:
            rcept = it.get("rcept_no")
            if not rcept:
                continue
            norm = normalize(endpoint, it)
            cur.execute(
                "INSERT INTO corp_action_details "
                "(ticker, rcept_no, endpoint, record_date, ratio, method, payload) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
                (ticker, rcept, endpoint, norm["record_date"], norm["ratio"],
                 (norm["method"] or "")[:200] or None, Jsonb(it)),
            )
            n += cur.rowcount
    return n
