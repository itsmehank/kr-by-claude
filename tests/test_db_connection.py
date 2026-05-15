from kr_pipeline.db.connection import connect


def test_connect_to_test_db(test_db_url):
    with connect(test_db_url) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
            assert cur.fetchone() == (1,)
