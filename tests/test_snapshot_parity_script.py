"""#94 — scripts/verify_snapshot_parity.py 의 compare_rows 단위 테스트.

스크립트는 pykrx/config import 를 main() 안에 가둬 뒀으므로(모듈 import 시
KRX 접촉 0 — #92 격리) importlib 로 파일을 직접 로드해 순수 함수만 검증한다.
"""
import importlib.util
from pathlib import Path

import pandas as pd

_SPEC = importlib.util.spec_from_file_location(
    "verify_snapshot_parity",
    Path(__file__).resolve().parent.parent / "scripts" / "verify_snapshot_parity.py",
)
parity = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(parity)


def _snap(rows: dict) -> pd.DataFrame:
    return pd.DataFrame(rows)


def test_compare_rows_all_match():
    db = {"A": (1, 2, 1, 2, 10, 100), "B": (5, 6, 5, 6, 20, 200)}
    snap = _snap({
        "ticker": ["A", "B"], "open": [1, 5], "high": [2, 6], "low": [1, 5],
        "close": [2, 6], "volume": [10, 20], "value": [100, 200],
    })
    r = parity.compare_rows(db, snap)
    assert r["matched"] == 2
    assert r["mismatches"] == [] and r["missing_in_snapshot"] == []


def test_compare_rows_detects_mismatch_and_missing():
    db = {"A": (1, 2, 1, 2, 10, 100), "B": (5, 6, 5, 6, 20, 200)}
    snap = _snap({
        "ticker": ["A"], "open": [1], "high": [2], "low": [1],
        "close": [999], "volume": [10], "value": [100],   # A 종가 불일치, B 미출현
    })
    r = parity.compare_rows(db, snap)
    assert r["matched"] == 0
    assert r["mismatches"][0][0] == "A"
    assert r["missing_in_snapshot"] == ["B"]


def test_compare_rows_extra_ticker_is_informational():
    """universe 밖 티커(신규상장 등)는 불일치가 아니라 extra 로만 보고."""
    db = {"A": (1, 2, 1, 2, 10, 100)}
    snap = _snap({
        "ticker": ["A", "NEWIPO"], "open": [1, 9], "high": [2, 9], "low": [1, 9],
        "close": [2, 9], "volume": [10, 9], "value": [100, 9],
    })
    r = parity.compare_rows(db, snap)
    assert r["matched"] == 1 and r["mismatches"] == []
    assert r["extra_in_snapshot"] == ["NEWIPO"]
