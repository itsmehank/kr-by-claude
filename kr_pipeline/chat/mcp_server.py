"""(#281) 채팅 전문가용 DB 조회 MCP 서버(stdio). 도구는 describe·query 2개뿐이다.

실행: python -m kr_pipeline.chat.mcp_server  (claude CLI 가 --mcp-config 로 띄운다)
접속 주소: CHAT_DATABASE_URL(없으면 DATABASE_URL 의 계정을 kr_chat_ro 로 바꾼 주소).
"""
from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from kr_pipeline.chat import dbtool

SERVER_NAME = "krdb"
TOOL_NAMES = ("describe", "query")

server = MCPServer(SERVER_NAME)


@server.tool()
def describe(table: str | None = None) -> str:
    """테이블 구조를 본다. table 을 비우면 전체 테이블 목록과 대략의 행 수, 주면 그 테이블의 열·형태·기본 키."""
    return dbtool.describe(table)


@server.tool()
def query(sql: str) -> str:
    """조회 전용 SQL(SELECT 또는 WITH 한 문장)을 실행한다. 결과는 200행·20,000자에서 잘린다. 시간 상한 5초."""
    return dbtool.run_query(sql)


if __name__ == "__main__":
    server.run("stdio")
