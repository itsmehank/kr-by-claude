"""조정 드리프트(분할 등) 감지 + 단일종목 전 기간 재적재.

detect 는 ohlcv 증분 전에 실행해야 한다(증분이 adj_close 를 덮어쓰기 전 DB vs KRX 비교).
스펙: docs/superpowers/specs/2026-06-04-pipeline-integration-drift-reload-design.md §2.
"""
from __future__ import annotations
import logging
from datetime import date, timedelta

from psycopg import Connection

log = logging.getLogger("kr_pipeline.pipeline.drift")


def is_drift(
    db_adj: dict[date, float],
    krx_adj: dict[date, float],
    rel_tol: float,
) -> bool:
    """DB 저장 adj_close vs KRX 재조회 adj_close 비교.

    겹치는 날짜(둘 다 존재)에서 상대차 |db-krx|/|krx| 가 rel_tol 초과면 True.
    겹침이 없으면 False(호출부가 기간 확대를 책임진다).
    """
    overlap = db_adj.keys() & krx_adj.keys()
    for d in overlap:
        k = krx_adj[d]
        if k == 0:
            continue
        if abs(db_adj[d] - k) / abs(k) > rel_tol:
            return True
    return False
