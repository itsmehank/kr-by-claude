# kr_pipeline/corporate_actions/corp_code_sync.py
"""DART corpCode.xml 다운로드 → 파싱 → dart_corp_codes UPSERT."""
import io
import logging
import zipfile
from datetime import date
from xml.etree import ElementTree as ET

import requests
from psycopg import Connection
from tenacity import retry, stop_after_attempt, wait_exponential_jitter

from kr_pipeline.corporate_actions.dart_client import BASE_URL


log = logging.getLogger("kr_pipeline.corporate_actions.corp_code_sync")


@retry(stop=stop_after_attempt(3), wait=wait_exponential_jitter(initial=1, max=8), reraise=True)
def download_dart_corp_code_xml(api_key: str) -> bytes:
    """ZIP 응답 다운로드. ZIP 안에 CORPCODE.xml 있음."""
    response = requests.get(
        f"{BASE_URL}/corpCode.xml",
        params={"crtfc_key": api_key},
        timeout=60,
    )
    response.raise_for_status()
    return response.content


def parse_corp_code_xml(zip_bytes: bytes) -> list[dict]:
    """ZIP bytes → CORPCODE.xml 파싱 → 상장 회사 목록 ({stock_code, corp_code, corp_name, modify_date})."""
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        xml_name = next(name for name in zf.namelist() if name.lower().endswith(".xml"))
        xml_bytes = zf.read(xml_name)

    tree = ET.fromstring(xml_bytes)
    result = []
    for item in tree.findall("list"):
        stock_code_el = item.find("stock_code")
        if stock_code_el is None or not stock_code_el.text or stock_code_el.text.strip() == "":
            continue   # 비상장 회사
        stock_code = stock_code_el.text.strip()
        corp_code = (item.find("corp_code").text or "").strip()
        corp_name = (item.find("corp_name").text or "").strip()
        modify_date_str = (item.find("modify_date").text or "").strip()
        try:
            modify_date = date(int(modify_date_str[:4]), int(modify_date_str[4:6]), int(modify_date_str[6:8])) if len(modify_date_str) >= 8 else None
        except (ValueError, IndexError):
            modify_date = None
        result.append({
            "stock_code": stock_code,
            "corp_code": corp_code,
            "corp_name": corp_name,
            "modify_date": modify_date,
        })
    return result


def upsert_dart_corp_codes(conn: Connection, rows: list[dict]) -> int:
    """UPSERT dart_corp_codes 테이블. 처리 행수 반환."""
    if not rows:
        return 0
    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO dart_corp_codes (stock_code, corp_code, corp_name, modify_date, updated_at)
            VALUES (%s, %s, %s, %s, NOW())
            ON CONFLICT (stock_code) DO UPDATE
               SET corp_code = EXCLUDED.corp_code,
                   corp_name = EXCLUDED.corp_name,
                   modify_date = EXCLUDED.modify_date,
                   updated_at = NOW()
            """,
            [(r["stock_code"], r["corp_code"], r["corp_name"], r["modify_date"]) for r in rows],
        )
        return cur.rowcount


def sync_corp_codes(conn: Connection, api_key: str) -> int:
    """다운로드 → 파싱 → UPSERT."""
    log.info("Downloading DART corpCode.xml...")
    zip_bytes = download_dart_corp_code_xml(api_key)
    log.info(f"Downloaded {len(zip_bytes)} bytes")

    rows = parse_corp_code_xml(zip_bytes)
    log.info(f"Parsed {len(rows)} listed companies")

    affected = upsert_dart_corp_codes(conn, rows)
    log.info(f"Upserted {affected} rows")
    return affected
