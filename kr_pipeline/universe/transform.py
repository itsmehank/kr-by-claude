"""유니버스 적재 전 배제 — 축 2개의 책임 경계 (정본: kr_pipeline/common/security_group.py docstring).

① 이름 휴리스틱 3축(우선주·스팩·ETF): SECUGRP_NM 으로 판별 불가(005935·스팩 70종목 전부 '주권',
   ETF 는 공매도 API 모집단 부재)라 종목명으로만 걸러진다. 부분문자열 오탐 실패 모드가 그대로 남아 있음
   (2026-09-15 리츠축에서 실증 — 별건 점검 스크립트 scripts/secugrp_name_axis_audit.py).
② SECUGRP 축: 적재 전 배제는 `PRELOAD_EXCLUDED_SECURITY_GROUPS`(부동산투자회사)만. 사회간접자본투융자회사·
   투자회사는 여기서 배제하지 않는다 — stocks 행을 생성하고 자격 게이트(minervini_pass NULL)가 담당.

[제거 기록 2026-09-15] REIT_KEYWORDS=("리츠", "맥쿼리인프라") 삭제. 사유: (i) `"리츠" in name` 이 메리츠금융지주·
블리츠웨이엔터테인먼트를 오탐, (ii) 맥쿼리인프라 개별 하드코딩은 같은 구분(사회간접자본투융자회사)의
KB발해인프라를 놓친 땜질. 리츠 배제는 SECUGRP '부동산투자회사'로 이관(전문가 판정 Q-3, 회신 3·4).

왜 리츠는 행이 없고 투자회사는 있는가: "수집 비용 대비 감사 가치" 단일 기준의 증권구분 단위 판단
(security_group.py 참조). 종목별 사정이 아니다.
"""
import re

import pandas as pd

from kr_pipeline.common.security_group import PRELOAD_EXCLUDED_SECURITY_GROUPS, UNRESOLVED

PREFERRED_SUFFIX_RE = re.compile(r"(우|우[A-Z]|\(전환\)|\(우선\))$")

ETF_PREFIXES = (
    "KODEX", "TIGER", "KOSEF", "ARIRANG", "HANARO", "KINDEX",
    "SOL", "ACE", "KBSTAR", "KOACT", "RISE", "WOORI", "BNK",
    "PLUS", "TIMEFOLIO", "히어로즈", "마이티",
)

SPAC_KEYWORDS = ("스팩",)


def _is_preferred(name: str) -> bool:
    return bool(PREFERRED_SUFFIX_RE.search(name))


def _is_etf(name: str) -> bool:
    return any(name.startswith(p) for p in ETF_PREFIXES)


def _is_spac(name: str) -> bool:
    return any(k in name for k in SPAC_KEYWORDS)


def classify_exclusion_axis(name: str, security_group: str | None) -> str | None:
    """적재 전 배제 축 라벨. None = 적재 대상(자격 게이트 판단은 별개)."""
    if _is_preferred(name):
        return "preferred"
    if _is_spac(name):
        return "spac"
    if _is_etf(name):
        return "etf"
    if (security_group or UNRESOLVED) in PRELOAD_EXCLUDED_SECURITY_GROUPS:
        return "security_group"
    return None


def split_universe(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(적재 대상, 배제[+axis]) 분리. security_group 컬럼이 없으면 UNRESOLVED 로 간주(fail-open)."""
    if df.empty:
        return df.reset_index(drop=True), df.assign(axis=pd.Series(dtype=str))
    groups = df["security_group"] if "security_group" in df.columns else pd.Series(UNRESOLVED, index=df.index)
    axis = [classify_exclusion_axis(n, g) for n, g in zip(df["name"], groups)]
    mask = pd.Series([a is None for a in axis], index=df.index)
    kept = df[mask].reset_index(drop=True)
    excluded = df[~mask].assign(axis=[a for a in axis if a is not None]).reset_index(drop=True)
    return kept, excluded


def filter_common_stocks(df: pd.DataFrame) -> pd.DataFrame:
    """적재 대상만 반환(호환 API)."""
    return split_universe(df)[0]
