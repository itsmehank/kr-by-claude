from datetime import date


def test_resolve_as_of_uses_max_indicator_date(db):
    from kr_pipeline.llm_runner.load import resolve_as_of

    # 미래 날짜를 사용해 다른 행의 MAX 에 오염되지 않도록 격리.
    # daily_indicators 에는 이미 2026-xx 행이 있을 수 있으므로
    # 2099년 sentinel 날짜를 삽입해 MAX 가 항상 우리 행임을 보장.
    d_max = date(2099, 12, 31)
    d_earlier = date(2099, 12, 29)

    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO stocks (ticker,name,market) VALUES ('RAO1','x','KOSPI') ON CONFLICT DO NOTHING"
        )
        for d in (d_earlier, d_max):
            cur.execute(
                "INSERT INTO daily_indicators (ticker,date,adj_close,volume,sma_50,avg_volume_50d,w52_high,w52_low) "
                "VALUES ('RAO1',%s,100,1000,90,1000,120,60) ON CONFLICT DO NOTHING",
                (d,),
            )
    db.commit()

    assert resolve_as_of(db) == d_max
    assert resolve_as_of(db, date(2026, 6, 6)) == date(2026, 6, 6)
