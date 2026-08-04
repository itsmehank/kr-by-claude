"""거래 캘린더 — 라이브 KRX 지수로 '기대 최신 거래일(ELTD)' 산출 + 신선도 단정.

pykrx 의존(get_index_ohlcv via fetch_index). 조회 실패는 fail-closed(예외 전파).
"""
from __future__ import annotations

import logging
import os
from datetime import date, datetime, time, timedelta
from pathlib import Path

from kr_pipeline.ohlcv.fetch import fetch_index

log = logging.getLogger("kr_pipeline.common.trading_calendar")

CLOSE_BUFFER = time(17, 0)   # KST. KRX 마감 15:30 후 pykrx EOD 안정화 시점.
_KOSPI_INDEX = "1001"
_LOOKBACK_DAYS = 14          # 최근 거래일 목록 확보(연휴 대비 충분).
_CACHE_DEFAULT = "~/.kr-by-claude/state/eltd.cache"


def eltd_cache_path() -> Path:
    """ELTD 캐시 파일 경로. env ELTD_CACHE 우선(테스트 격리용)."""
    return Path(os.environ.get("ELTD_CACHE") or _CACHE_DEFAULT).expanduser()


def cache_key(now: datetime) -> str:
    """캐시 키 = 날짜 + 마감버퍼 구간.

    17시 전후로 ELTD 가 달라지므로(아래 expected_latest_trading_day 분기) 날짜만으로는
    부족하다. 같은 키의 캐시값은 라이브 조회 결과와 정의상 동일하다.
    """
    return f"{now.date().isoformat()}:{'post' if now.time() >= CLOSE_BUFFER else 'pre'}"


def cached_eltd(now: datetime) -> date | None:
    """캐시된 ELTD 를 읽는다. **라이브 조회를 하지 않는다** — 미스면 None.

    #92: 시간당 도는 감시가 라이브를 부르면 차단 상태에서 매시간 재시도하게 되어
    재탐지를 유발한다(08-02 실측 15회/일 × 6요청). 감시(셸)는 이 규약의 캐시 파일을
    순수 bash 로 직접 읽는다 — 이 모듈을 import 하면 pykrx 가 로드되어 로그인이 나가므로.
    """
    try:
        text = eltd_cache_path().read_text()
    except (OSError, UnicodeDecodeError, ValueError):
        return None
    want = cache_key(now)
    for line in reversed(text.splitlines()):
        k, _, v = line.partition("|")
        if k == want and v:
            try:
                return date.fromisoformat(v)
            except ValueError:
                continue  # 손상 줄은 건너뛴다 — 같은 키의 앞선 유효 줄을 살린다(3차 검토)
    return None


def _write_cache(now: datetime, value: date) -> None:
    """캐시 갱신. 실패는 무시한다 — 캐시는 보조 수단이고 호출부는 fail-closed 경로다.

    기존 내용 읽기를 **안쪽 try** 로 감싼다: 파일이 비-UTF8 로 손상되면 read_text() 가
    UnicodeDecodeError 를 던지고, 그게 바깥 except 로 빠지면 쓰기 자체가 실행되지 않아
    캐시가 영구 손상 상태로 남는다(감시의 결측 판정이 죽는다). 손상 내용은 버리고 새로 쓴다.

    쓰기는 tmp → replace 로 원자 교체한다 — 감시(시간당)와 체인이 같은 파일을 다룬다.
    """
    try:
        p = eltd_cache_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        try:
            prev = p.read_text().splitlines() if p.exists() else []
        except (OSError, UnicodeDecodeError):
            prev = []
        want = cache_key(now)
        keep = [ln for ln in prev if not ln.startswith(f"{want}|")][-30:]
        # tmp 에 PID — 동시 writer(체인·llm_runner·weekly·웹 UI)가 같은 tmp 를 밟으면
        # 원자성이 깨진다(3차 검토). replace 는 rename 이라 원자적.
        tmp = p.with_name(f"{p.name}.{os.getpid()}.tmp")
        tmp.write_text("\n".join(keep + [f"{want}|{value.isoformat()}"]) + "\n")
        tmp.replace(p)
    except Exception as e:  # noqa: BLE001 — 캐시 실패가 ELTD 산출을 막아선 안 된다
        log.warning("ELTD 캐시 쓰기 실패(무시): %s", e)


class TradingCalendarUnavailable(RuntimeError):
    """거래 캘린더(라이브 KRX 지수) 조회 실패 — fail-closed."""


class StaleDataError(RuntimeError):
    """최신 완전 데이터가 기대 최신 거래일보다 뒤처짐 — 분석 중단."""


def expected_latest_trading_day(now: datetime) -> date:
    """기대 최신 거래일(ELTD).

    라이브 KRX 지수로 실제 거래일 목록을 얻고 마감버퍼로 오늘 포함 여부 결정:
    - 오늘이 거래일 & now.time() >= CLOSE_BUFFER → 오늘
    - 그 외 → 오늘 직전 거래일
    조회 실패/빈 결과/직전거래일 없음 → TradingCalendarUnavailable(fail-closed).
    """
    today = now.date()
    try:
        df = fetch_index(_KOSPI_INDEX, today - timedelta(days=_LOOKBACK_DAYS), today)
    except Exception as e:  # noqa: BLE001 — 모든 조회 실패를 fail-closed 로 수렴
        raise TradingCalendarUnavailable(f"거래 캘린더 조회 실패: {e}") from e
    if df is None or df.empty or "date" not in df.columns:
        raise TradingCalendarUnavailable("거래 캘린더 조회 결과 없음")
    trading_days = sorted({d for d in df["date"]})
    if today in trading_days and now.time() >= CLOSE_BUFFER:
        _write_cache(now, today)
        return today
    prior = [d for d in trading_days if d < today]
    if not prior:
        raise TradingCalendarUnavailable(
            f"직전 거래일 없음(lookback {_LOOKBACK_DAYS}d, today={today})"
        )
    result = max(prior)
    _write_cache(now, result)
    return result


def assert_data_fresh(as_of: date, now: datetime) -> None:
    """as_of(최신 완전 지표일)가 ELTD 보다 뒤처지면 StaleDataError.

    ELTD 산출 실패(pykrx) 시 TradingCalendarUnavailable 전파(fail-closed).

    #92: 캐시를 먼저 읽는다. 캐시 키가 (날짜 + 마감버퍼 구간)이므로 같은 키의 값은
    라이브 조회 결과와 정의상 동일하고(expected_latest_trading_day 의 분기가 그 두 축만
    사용), 따라서 판정력은 줄지 않는다. 저녁 체인은 직전에 eltd() 로 이미 라이브 조회를
    했으므로 여기서 또 묻는 것은 KRX 요청 낭비이며, 그 사이의 일시 장애가 그날 LLM
    분석을 통째로 취소시키는 취약점이기도 하다. 캐시 미스 시 라이브 폴백 → fail-closed 유지.
    """
    eltd = cached_eltd(now)
    if eltd is None:
        eltd = expected_latest_trading_day(now)
    if as_of < eltd:
        raise StaleDataError(
            f"최신 거래일 {eltd} 데이터 미적재 (현재 최신 {as_of}) — 분석 중단"
        )
    log.info("freshness OK: as_of=%s eltd=%s", as_of, eltd)
