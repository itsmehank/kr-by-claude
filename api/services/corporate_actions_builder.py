"""corporate_actions → payload.price_data_notes dict."""
from datetime import date, timedelta
from psycopg import Connection


def build_corporate_actions(
    conn: Connection,
    ticker: str,
    lookback_years: int = 5,
    as_of_date: date | None = None,
) -> dict:
    """corporate_actions 조회 + 12w reverse/forward split flag 계산.

    Return: payload.price_data_notes 형식.
    """
    if as_of_date is None:
        as_of_date = date.today()

    start_date = as_of_date - timedelta(days=lookback_years * 365)
    twelve_weeks_ago = as_of_date - timedelta(weeks=12)

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT event_date, event_type, ratio, note, raw_disclosure_title
              FROM corporate_actions
             WHERE ticker = %s AND event_date >= %s
             ORDER BY event_date DESC
            """,
            (ticker, start_date),
        )
        rows = cur.fetchall()

    actions = []
    reverse_recent = False
    forward_recent = False

    for event_date, event_type, ratio, note, title in rows:
        actions.append({
            "date": event_date.isoformat(),
            "type": event_type,
            "ratio": ratio,
            "note": note or title,
        })
        if event_date >= twelve_weeks_ago:
            if event_type == "reverse_split":
                reverse_recent = True
            elif event_type == "stock_split":
                forward_recent = True

    return {
        "known_corporate_actions": actions,
        "reverse_split_within_12w": reverse_recent,
        "forward_split_within_12w": forward_recent,
    }
