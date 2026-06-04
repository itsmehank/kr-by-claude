"""Tests for api/services/integrity_guard.py — adj_volume(보정) vs indicators.volume 비교."""
import pytest
from datetime import date

from api.services.integrity_guard import check_data_integrity, DataIntegrityError


def test_guard_compares_adj_volume_not_raw(db):
    """daily_prices.adj_volume == daily_indicators.volume 이면 통과(원시 volume 과 무관). 어긋나면 검출."""
    d = date(2023, 2, 1)  # 실데이터 이전(격리)
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker,name,market) VALUES ('IG1','I','KOSPI') ON CONFLICT DO NOTHING")
        cur.execute("DELETE FROM daily_prices WHERE ticker='IG1'")
        cur.execute("DELETE FROM daily_indicators WHERE ticker='IG1'")
        # raw volume 1000, adj_volume 5000(×5); indicators.volume 5000 → 보정끼리 일치
        cur.execute("""INSERT INTO daily_prices (ticker,date,open,high,low,close,adj_close,adj_high,adj_low,adj_open,adj_volume,volume,value)
                       VALUES ('IG1',%s,100,110,90,105,21,22,18,20,5000,1000,1)""", (d,))
        cur.execute("""INSERT INTO daily_indicators (ticker,date,adj_close,volume) VALUES ('IG1',%s,21,5000)""", (d,))
    db.commit()
    try:
        res = check_data_integrity(db, "IG1", d)
        assert res.ok
        with db.cursor() as cur:
            cur.execute("UPDATE daily_indicators SET volume=9999 WHERE ticker='IG1' AND date=%s", (d,))
        db.commit()
        with pytest.raises(DataIntegrityError):
            check_data_integrity(db, "IG1", d)
    finally:
        with db.cursor() as cur:
            cur.execute("DELETE FROM daily_prices WHERE ticker='IG1'")
            cur.execute("DELETE FROM daily_indicators WHERE ticker='IG1'")
        db.commit()
