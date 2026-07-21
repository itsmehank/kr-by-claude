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


def notify_stop_triggered(*, symbol: str, name: str, close: float,
                          effective_stop: float, binding: str,
                          eval_date=None) -> None:
    """(#47) 보유 포지션 매도 신호 알림 (일일 손절 평가 러너).

    eval_date 명시 — 과거일 재평가 알림이 실시간 신호로 오독되는 것 방지(리뷰).
    """
    when = f" [{eval_date}]" if eval_date else ""
    text = (
        f"🔴 *매도 신호*{when} `{symbol}` {name}\n"
        f"종가 ₩{close:,.0f} < 유효 손절선 ₩{effective_stop:,.0f} ({binding})"
    )
    _post({"text": text})


def notify_weekend_digest(*, entry_count: int, watch_count: int, ignore_count: int) -> None:
    """주말 (5) batch 다이제스트."""
    text = (
        f"📊 *주말 분류 완료*\n"
        f"Entry: {entry_count} · Watch: {watch_count} · Ignore: {ignore_count}"
    )
    _post({"text": text})
