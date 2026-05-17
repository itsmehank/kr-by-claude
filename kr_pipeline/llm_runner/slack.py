"""Slack webhook 알림 — SLACK_WEBHOOK_URL 없으면 skip."""
from __future__ import annotations

import json
import logging
import os
import urllib.request


log = logging.getLogger("kr_pipeline.llm_runner.slack")


def _post(payload: dict) -> None:
    url = os.environ.get("SLACK_WEBHOOK_URL")
    if not url:
        log.warning("SLACK_WEBHOOK_URL not set, skipping notification")
        return
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        log.warning("Slack post failed: %s", e)


def notify_signal(*, symbol: str, name: str, entry_price: float, stop_loss: float) -> None:
    """매수 시그널 알림 (entry_params 생성 시)."""
    text = f"🟢 *매수 시그널* `{symbol}` {name}\n진입가 ₩{entry_price:,.0f} · 손절가 ₩{stop_loss:,.0f}"
    _post({"text": text})


def notify_weekend_digest(*, entry_count: int, watch_count: int, ignore_count: int) -> None:
    """주말 (5) batch 다이제스트."""
    text = (
        f"📊 *주말 분류 완료*\n"
        f"Entry: {entry_count} · Watch: {watch_count} · Ignore: {ignore_count}"
    )
    _post({"text": text})
