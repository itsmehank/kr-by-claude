import re
import pandas as pd


PREFERRED_SUFFIX_RE = re.compile(r"(우|우[A-Z]|\(전환\)|\(우선\))$")

ETF_PREFIXES = (
    "KODEX", "TIGER", "KOSEF", "ARIRANG", "HANARO", "KINDEX",
    "SOL", "ACE", "KBSTAR", "KOACT", "RISE", "WOORI", "BNK",
    "PLUS", "TIMEFOLIO", "히어로즈", "마이티",
)

REIT_KEYWORDS = ("리츠", "맥쿼리인프라")
SPAC_KEYWORDS = ("스팩",)


def _is_preferred(name: str) -> bool:
    return bool(PREFERRED_SUFFIX_RE.search(name))


def _is_etf(name: str) -> bool:
    return any(name.startswith(p) for p in ETF_PREFIXES)


def _is_reit(name: str) -> bool:
    return any(k in name for k in REIT_KEYWORDS)


def _is_spac(name: str) -> bool:
    return any(k in name for k in SPAC_KEYWORDS)


def filter_common_stocks(df: pd.DataFrame) -> pd.DataFrame:
    """name 컬럼 기준으로 우선주/ETF/리츠/스팩 제외."""
    mask = ~df["name"].apply(
        lambda n: _is_preferred(n) or _is_etf(n) or _is_reit(n) or _is_spac(n)
    )
    return df[mask].reset_index(drop=True)
