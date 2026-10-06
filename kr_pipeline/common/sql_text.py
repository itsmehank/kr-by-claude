"""SQL 텍스트 헬퍼 — 사용자 입력을 LIKE/ILIKE 패턴에 넣을 때 와일드카드를 리터럴로(#189, PR #187 trade_api 에서 승격)."""


def escape_like(q: str) -> str:
    """LIKE/ILIKE 와일드카드(`\\ % _`)를 리터럴로 이스케이프 — SQL 에서 반드시 `ESCAPE '\\'` 와 짝지어 쓴다."""
    return q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
