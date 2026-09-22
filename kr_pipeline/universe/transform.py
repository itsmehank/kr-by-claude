"""유니버스 적재 전 배제 — 축 2개의 책임 경계 (정본: kr_pipeline/common/security_group.py docstring).

① 비-SECUGRP 2축 — 우선주(종목코드 말미 규칙, #195 커밋1)·스팩(이름 키워드): SECUGRP_NM 으로 판별 불가
   (005935·스팩 70종목 전부 '주권'). 스팩 축은 이름 부분문자열이라 오탐 실패 모드가 남아 있음(2026-09-21 점검 오탐 0)
   (2026-09-15 리츠축에서 실증 — 별건 점검 스크립트 scripts/secugrp_name_axis_audit.py).
② SECUGRP 축: 적재 전 배제는 `PRELOAD_EXCLUDED_SECURITY_GROUPS`(부동산투자회사)만. 사회간접자본투융자회사·
   투자회사는 여기서 배제하지 않는다 — stocks 행을 생성하고 자격 게이트(minervini_pass NULL)가 담당.

[제거 기록 2026-09-15] REIT_KEYWORDS=("리츠", "맥쿼리인프라") 삭제. 사유: (i) `"리츠" in name` 이 메리츠금융지주·
블리츠웨이엔터테인먼트를 오탐, (ii) 맥쿼리인프라 개별 하드코딩은 같은 구분(사회간접자본투융자회사)의
KB발해인프라를 놓친 땜질. 리츠 배제는 SECUGRP '부동산투자회사'로 이관(전문가 판정 Q-3, 회신 3·4).

[제거 기록 2026-09-21, #195 커밋2] ETF_PREFIXES 16종·_is_etf 삭제(대체 아님). governance 1-1 4조건:
(a) 제약형 필터 — 제거 후 파이프라인 정상. (b) 커버리지 손실 없음 — 유니버스 원본 = pykrx 전종목시세(STK/KSQ)
= 주식 전용이라 ETF 구조적 부재 + SECUGRP 화이트리스트 fail-closed(미해결 → 자격 NULL)가 후방 방어.
(c) book-mandated 와 방향 충돌 — 접두사 'BNK' 가 실적 있는 KOSPI 금융지주(138930)를 ETF 로 오분류·배제(진양성 0, 오탐 1).
(d) 산출(_is_etf)·소비(axis 'etf'·가드 b) 동시 제거. 기존 스냅샷의 axis='etf' 1행은 원시 기록으로 보존(1-2).

왜 리츠는 행이 없고 투자회사는 있는가: "수집 비용 대비 감사 가치" 단일 기준의 증권구분 단위 판단
(security_group.py 참조). 종목별 사정이 아니다.
"""
import pandas as pd

from kr_pipeline.common.security_group import PRELOAD_EXCLUDED_SECURITY_GROUPS, UNRESOLVED

# [#195 커밋1, 2026-09-21] 우선주 판별 = 6자리 종목코드 끝자리 ≠ '0' (이름 정규식 `(우|우[A-Z]|\(전환\)|\(우선\))$` 대체).
# 태그: 배제 = book-mandated(HMMS Ch.20 규칙 17), 판별 규칙 = measurement-based(2026-09-11 저장본 전수 2×2
# 114/3/0/2,648 로 검증. KRX 코드 부여 규정 자체는 미확인). 이름 정규식은 '우'로 끝나는 보통주(성우·에코글로우·
# 이오플로우)를 오탐했다. 드리프트 감시는 기존 배제 집합 스냅샷 가드로 갈음 — 신규 장치 없음.
_PREFERRED_CODE_COMMON_SUFFIX = "0"

SPAC_KEYWORDS = ("스팩",)


def _is_preferred_code(ticker: str) -> bool:
    """우선주 = 종목코드 끝자리 ≠ '0' (보통주 관례 = '0'). 저장본 실측 끝자리 집합 {0,5,7,9,K,L}."""
    return len(ticker) == 6 and ticker[-1] != _PREFERRED_CODE_COMMON_SUFFIX


def _is_spac(name: str) -> bool:
    return any(k in name for k in SPAC_KEYWORDS)


def classify_exclusion_axis(ticker: str, name: str, security_group: str | None) -> str | None:
    """적재 전 배제 축 라벨. None = 적재 대상(자격 게이트 판단은 별개)."""
    if _is_preferred_code(ticker):
        return "preferred"
    if _is_spac(name):
        return "spac"
    if (security_group or UNRESOLVED) in PRELOAD_EXCLUDED_SECURITY_GROUPS:
        return "security_group"
    return None


def split_universe(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(적재 대상, 배제[+axis]) 분리. security_group 컬럼이 없으면 UNRESOLVED 로 간주(fail-open)."""
    if df.empty:
        return df.reset_index(drop=True), df.assign(axis=pd.Series(dtype=str))
    groups = df["security_group"] if "security_group" in df.columns else pd.Series(UNRESOLVED, index=df.index)
    axis = [classify_exclusion_axis(t, n, g) for t, n, g in zip(df["ticker"], df["name"], groups)]
    mask = pd.Series([a is None for a in axis], index=df.index)
    kept = df[mask].reset_index(drop=True)
    excluded = df[~mask].assign(axis=[a for a in axis if a is not None]).reset_index(drop=True)
    return kept, excluded


def filter_common_stocks(df: pd.DataFrame) -> pd.DataFrame:
    """적재 대상만 반환(호환 API)."""
    return split_universe(df)[0]
