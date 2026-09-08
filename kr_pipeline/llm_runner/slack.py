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


def notify_signal(*, symbol: str, name: str, entry_price: float, stop_loss: float,
                  size_pct: float | None = None) -> None:
    """매수 시그널 알림 (entry_params 생성 시). (#153) 비중 = 리스크 역산 파일럿 %."""
    text = f"🟢 *매수 시그널* `{symbol}` {name}\n진입가 ₩{entry_price:,.0f} · 손절가 ₩{stop_loss:,.0f}"
    if size_pct is not None:
        text += f" · 비중 {size_pct:.1f}%(파일럿)"
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


def notify_sell_into_strength(*, symbol: str, name: str, close: float, triggers: list[str],
                              anchor_week: str | None, weeks_since: int | None,
                              hold_days: int, eval_date=None) -> None:
    """(항목 ③) 보유 종목 climax 강세 매도 권고 — 전량 매도(수동 체결 모델). 자동 청산 없음."""
    when = f" ({eval_date})" if eval_date else ""
    text = (f"🔶 *강세 매도 권고(climax)*{when} `{symbol}` {name}\n"
            f"종가 ₩{close:,.0f} · 전량 매도 검토 — §6.1 P1∧P2∧scope + 트리거 {', '.join(triggers)}\n"
            f"앵커 {anchor_week or 'n/a'} · 앵커 후 {weeks_since if weeks_since is not None else 'n/a'}주 · 보유 {hold_days}일")
    _post({"text": text})


def notify_sell_half(*, symbol: str, name: str, close: float, entry_price: float,
                     hit20_date, hold_days: int, basis: str, eval_date=None) -> None:
    """(#166) 이익목표 절반매도(5B) 권고 — 플래그 ON 시에만 호출. 수량 변경 없음(전량 모델)."""
    when = f" ({eval_date})" if eval_date else ""
    gain = (close / entry_price - 1) * 100
    text = (f"🔷 *절반 매도 권고(5B)*{when} `{symbol}` {name}\n"
            f"종가 ₩{close:,.0f} (매입가 대비 {gain:+.1f}%) · +20% 도달일 {hit20_date} · 보유 {hold_days}일\n"
            f"근거: {basis} — HMMS 20~25% 일부 실현 / 8주 규칙")
    _post({"text": text})


def notify_weekend_digest(*, entry_count: int, watch_count: int, ignore_count: int) -> None:
    """주말 (5) batch 다이제스트."""
    text = (
        f"📊 *주말 분류 완료*\n"
        f"Entry: {entry_count} · Watch: {watch_count} · Ignore: {ignore_count}"
    )
    _post({"text": text})
