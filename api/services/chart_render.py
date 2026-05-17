"""matplotlib 차트 → PNG bytes. LLM 멀티모달 입력 + 사용자 PNG 다운로드용."""
import io

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.dates import DateFormatter
from matplotlib.figure import Figure
from matplotlib.patches import Rectangle
import pandas as pd
from psycopg import Connection

COLOR_UP_CANDLE = "#26a69a"
COLOR_DOWN_CANDLE = "#ef5350"
COLOR_SMA_50 = "#ff9800"
COLOR_SMA_150 = "#2196f3"
COLOR_SMA_200 = "#f44336"
COLOR_52W_HIGH = "#4caf50"
COLOR_52W_LOW = "#e91e63"
COLOR_VOLUME_AVG = "#757575"
COLOR_RS_LINE = "#9c27b0"


def render_daily_chart(conn: Connection, ticker: str, range_days: int = 365) -> bytes:
    """일봉 차트 PNG bytes. Main pane (candle + SMA50/150/200 + 52w + PP/Dist markers) + Volume pane + RS Line pane."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT p.date, p.open, p.high, p.low, p.close, p.adj_close, p.volume,
                   i.sma_50, i.sma_150, i.sma_200, i.w52_high, i.w52_low,
                   i.rs_line, i.rs_line_52w_high,
                   i.avg_volume_50d, i.pocket_pivot_flag, i.distribution_day_flag
              FROM daily_prices p
              LEFT JOIN daily_indicators i ON i.ticker = p.ticker AND i.date = p.date
             WHERE p.ticker = %s
             ORDER BY p.date DESC
             LIMIT %s
            """,
            (ticker, range_days),
        )
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]

    if not rows:
        return _render_empty_chart(f"{ticker} (no data)")

    df = pd.DataFrame(rows, columns=cols).sort_values("date").reset_index(drop=True)
    df = _coerce_numeric(df)
    return _render_ohlc_chart(df, title=f"{ticker} Daily", x_label="Date")


def render_weekly_chart(conn: Connection, ticker: str, range_weeks: int = 104) -> bytes:
    """주봉 차트 PNG bytes."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT p.week_end_date AS date, p.open, p.high, p.low, p.close, p.adj_close, p.volume,
                   i.sma_10w, i.sma_30w, i.sma_40w, i.w52_high, i.w52_low,
                   i.rs_line, i.rs_line_52w_high,
                   i.avg_volume_10w
              FROM weekly_prices p
              LEFT JOIN weekly_indicators i ON i.ticker = p.ticker AND i.week_end_date = p.week_end_date
             WHERE p.ticker = %s
             ORDER BY p.week_end_date DESC
             LIMIT %s
            """,
            (ticker, range_weeks),
        )
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]

    if not rows:
        return _render_empty_chart(f"{ticker} (no data)")

    df = pd.DataFrame(rows, columns=cols).sort_values("date").reset_index(drop=True)
    df = df.rename(columns={"sma_10w": "sma_50", "sma_30w": "sma_150", "sma_40w": "sma_200"})
    df["pocket_pivot_flag"] = False
    df["distribution_day_flag"] = False
    df["avg_volume_50d"] = df["avg_volume_10w"]
    df = _coerce_numeric(df)
    return _render_ohlc_chart(df, title=f"{ticker} Weekly", x_label="Week End")


def _coerce_numeric(df: pd.DataFrame) -> pd.DataFrame:
    """psycopg 의 Decimal/int 컬럼을 float 으로 일괄 변환.

    Decimal × float 연산 (예: low * 0.99) 시 TypeError 방지.
    """
    numeric_cols = [
        "open", "high", "low", "close", "adj_close", "volume",
        "sma_50", "sma_150", "sma_200",
        "w52_high", "w52_low",
        "rs_line", "rs_line_52w_high",
        "avg_volume_50d",
    ]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def _render_ohlc_chart(df: pd.DataFrame, title: str, x_label: str) -> bytes:
    fig: Figure = plt.figure(figsize=(14, 9), dpi=100)
    gs = fig.add_gridspec(3, 1, height_ratios=[7, 1.5, 1.5], hspace=0.1)
    ax_main = fig.add_subplot(gs[0, 0])
    ax_vol = fig.add_subplot(gs[1, 0], sharex=ax_main)
    ax_rs = fig.add_subplot(gs[2, 0], sharex=ax_main)

    dates = pd.to_datetime(df["date"])

    _draw_candlesticks(ax_main, dates, df)
    if "sma_50" in df.columns and df["sma_50"].notna().any():
        ax_main.plot(dates, df["sma_50"], color=COLOR_SMA_50, linewidth=1.0, label="SMA 50")
    if "sma_150" in df.columns and df["sma_150"].notna().any():
        ax_main.plot(dates, df["sma_150"], color=COLOR_SMA_150, linewidth=1.0, label="SMA 150")
    if "sma_200" in df.columns and df["sma_200"].notna().any():
        ax_main.plot(dates, df["sma_200"], color=COLOR_SMA_200, linewidth=1.0, label="SMA 200")
    if "w52_high" in df.columns and df["w52_high"].notna().any():
        ax_main.plot(dates, df["w52_high"], color=COLOR_52W_HIGH, linestyle="--", linewidth=0.8, alpha=0.7, label="52w high")
    if "w52_low" in df.columns and df["w52_low"].notna().any():
        ax_main.plot(dates, df["w52_low"], color=COLOR_52W_LOW, linestyle="--", linewidth=0.8, alpha=0.7, label="52w low")

    if "pocket_pivot_flag" in df.columns:
        pp_mask = df["pocket_pivot_flag"] == True
        if pp_mask.any():
            ax_main.scatter(dates[pp_mask], df.loc[pp_mask, "low"] * 0.99, marker="^", color="green", s=80, zorder=5, label="Pocket Pivot")
    if "distribution_day_flag" in df.columns:
        dist_mask = df["distribution_day_flag"] == True
        if dist_mask.any():
            ax_main.scatter(dates[dist_mask], df.loc[dist_mask, "high"] * 1.01, marker="v", color="red", s=80, zorder=5, label="Distribution")

    ax_main.set_title(title, fontsize=14, fontweight="bold")
    ax_main.grid(True, alpha=0.3)
    handles, labels = ax_main.get_legend_handles_labels()
    if handles:
        ax_main.legend(handles, labels, loc="upper left", fontsize=8, ncol=3)

    vol_colors = [COLOR_UP_CANDLE if c >= o else COLOR_DOWN_CANDLE for c, o in zip(df["close"], df["open"])]
    ax_vol.bar(dates, df["volume"], color=vol_colors, alpha=0.6, width=0.8)
    if "avg_volume_50d" in df.columns and df["avg_volume_50d"].notna().any():
        ax_vol.plot(dates, df["avg_volume_50d"], color=COLOR_VOLUME_AVG, linewidth=1.0, label="Avg Vol 50d")
        ax_vol.legend(loc="upper left", fontsize=8)
    ax_vol.set_ylabel("Volume", fontsize=9)
    ax_vol.grid(True, alpha=0.3)

    if "rs_line" in df.columns and df["rs_line"].notna().any():
        ax_rs.plot(dates, df["rs_line"], color=COLOR_RS_LINE, linewidth=1.0, label="RS Line")
        if "rs_line_52w_high" in df.columns and df["rs_line_52w_high"].notna().any():
            ax_rs.plot(dates, df["rs_line_52w_high"], color=COLOR_RS_LINE, linestyle="--", linewidth=0.8, alpha=0.5, label="RS Line 52w high")
        ax_rs.legend(loc="upper left", fontsize=8)
    ax_rs.set_ylabel("RS Line", fontsize=9)
    ax_rs.set_xlabel(x_label, fontsize=9)
    ax_rs.grid(True, alpha=0.3)

    ax_main.xaxis.set_major_formatter(DateFormatter("%Y-%m-%d"))

    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", dpi=100)
    plt.close(fig)
    return buf.getvalue()


def _draw_candlesticks(ax, dates, df) -> None:
    """간단한 캔들스틱."""
    width = 0.6
    for d, o, h, l, c in zip(dates, df["open"], df["high"], df["low"], df["close"]):
        color = COLOR_UP_CANDLE if c >= o else COLOR_DOWN_CANDLE
        ax.vlines(d, l, h, color=color, linewidth=0.5)
        body_height = abs(c - o)
        body_bottom = min(o, c)
        ax.add_patch(Rectangle(
            (d - pd.Timedelta(days=width / 2), body_bottom),
            pd.Timedelta(days=width),
            body_height,
            facecolor=color,
            edgecolor=color,
            alpha=0.8,
        ))


def _render_empty_chart(message: str) -> bytes:
    fig = plt.figure(figsize=(14, 9), dpi=100)
    ax = fig.add_subplot(1, 1, 1)
    ax.text(0.5, 0.5, message, ha="center", va="center", fontsize=20, transform=ax.transAxes)
    ax.axis("off")
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", dpi=100)
    plt.close(fig)
    return buf.getvalue()
