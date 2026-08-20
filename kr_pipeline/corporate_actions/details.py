# kr_pipeline/corporate_actions/details.py
"""(#114 경로B) DART 주요사항 구조화 상세 — 증자·감자 기준일/비율/방식 직취.

엔드포인트 4종(실검증 2026-08-19): 유상증자 piicDecsn(`ic_mthn` 으로 주주배정/
3자배정/일반공모 판별)·무상증자 fricDecsn(`nstk_asstd` 기준일, `nstk_ascnt_ps_ostk`
1주당 배정)·유무상 pifricDecsn·감자 crDecsn(`cr_std` 기준일, `cr_rt_ostk` 비율%).
액면분할/병합은 구조화 API 부재 — v2(가격 갭+주식수)가 담당(커버리지 표 참조).
"""
from __future__ import annotations

import json
import math
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


def fetch_document_text(api_key: str, rcept_no: str) -> str:
    """공시 원문(document API, zip→XML) 텍스트. 실패 시 raise."""
    import io
    import zipfile

    import requests

    r = requests.get("https://opendart.fss.or.kr/api/document.xml",
                     params={"crtfc_key": api_key, "rcept_no": rcept_no},
                     timeout=60)
    r.raise_for_status()
    z = zipfile.ZipFile(io.BytesIO(r.content))
    names = z.namelist()
    if not names:
        raise RuntimeError("empty document zip")
    raw = z.read(names[0])
    for enc in ("utf-8", "cp949"):   # 구형 공시 = EUC-KR (v4 게이트 실측)
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def parse_rights_record_date(text: str) -> date | None:
    """원문에서 신주배정기준일 추출 — 라벨 뒤 첫 구간의 날짜 중 **마지막**
    (정정 공시는 변경 전/후 병기 — 변경 후 값) [v4, 프로토타입 실검증 규칙]."""
    i = text.find("신주배정기준일")
    if i < 0:
        i = text.find("신주 배정기준일")
    if i < 0:
        return None
    seg = re.sub(r"<[^>]+>", " ", text[i:i + 500])
    dates = re.findall(r"\d{4}\s*년\s*\d{1,2}\s*월\s*\d{1,2}\s*일", seg)
    return parse_kr_date(dates[-1]) if dates else None


def parse_stkdp(text: str) -> dict | None:
    """주식배당결정 수시공시 원문 파싱 (v5, #114 11차).

    반환 {record_date, ratio, div_total, outstanding, per_share} 또는 None.
    ratio = 배당주식총수/발행주식총수 (KRX 기준가 조정 실측과 정합 — 자기주식
    제외 효과 내재). 총수 미제공 시 1주당 배당주식수 fallback.
    """
    plain = re.sub(r"<[^>]+>", " ", text)
    plain = re.sub(r"\s+", " ", plain)

    def num_after(label: str) -> float | None:
        i = plain.find(label)
        if i < 0:
            return None
        m = re.search(r"보통주식\s*([\d,.]+)", plain[i:i + 200])
        return parse_num(m.group(1)) if m else None

    rd = None
    i = plain.find("배당기준일")
    if i >= 0:
        seg = plain[i:i + 120]
        m = re.search(r"(\d{4})-(\d{2})-(\d{2})", seg)
        if m:
            try:
                rd = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except ValueError:
                rd = None
        if rd is None:
            rd = parse_kr_date(seg)
    if rd is None:
        return None
    div_total = num_after("배당주식총수")
    outstanding = num_after("발행주식총수")
    per_share = num_after("1주당 배당주식수")
    # 타당성 한계 — 기재정정 2단 표(변경 전/후)에서 라벨-값 오정렬로 발행총수가
    # 비율 자리에 오는 실사례(ratio 1.0·7.48e6) 차단. 주식배당은 0 < r ≤ 0.5.
    ps_ok = per_share is not None and 0 < per_share <= 0.5
    tot_ok = (div_total is not None and outstanding is not None
              and div_total >= 1 and outstanding >= 1000
              and div_total < outstanding)
    ratio = None
    if tot_ok:
        r = div_total / outstanding
        if 0 < r <= 0.5 and (not ps_ok or abs(math.log(r / per_share)) < math.log(2)):
            ratio = r                       # 총수 기반(자기주식 제외 효과 내재)
    if ratio is None and ps_ok:
        ratio = per_share                   # fallback — 자기주식 보정 없는 근사
    if ratio is None:
        return None
    return {"record_date": rd, "ratio": ratio, "div_total": div_total,
            "outstanding": outstanding, "per_share": per_share}


def parse_new_share_count(text: str) -> float | None:
    """교차 검증 게이트(8차 ①)용 — 원문의 보통주 신주 수."""
    plain = re.sub(r"<[^>]+>", " ", text)
    anchor = plain.find("신주의 종류와 수")
    seg = plain[anchor:anchor + 1500] if anchor >= 0 else plain[:6000]
    m = re.search(r"보통주식[^\d]{0,80}?([\d,]{4,})", seg)
    if not m:
        return None
    return parse_num(m.group(1))
