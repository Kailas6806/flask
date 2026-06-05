"""
V12 PRO MAX — Analytics Dashboard Tab
Streamlit tab rendering trade analytics with Plotly charts
and KPI cards using the TradeJournal instance.
"""

import logging
from typing import Any, Dict, List

import streamlit as st
import plotly.express as px
import pandas as pd

logger = logging.getLogger("v12.analytics_dashboard")

# ── Colour palette ────────────────────────────────────────────────────
_GREEN = "#00c853"
_RED = "#ff1744"
_CARD_CSS = """
<style>
.analytics-card {
    background: linear-gradient(135deg, #1a1a2e 60%, #16213e);
    border-radius: 12px;
    padding: 18px 22px;
    margin: 6px 0;
    box-shadow: 0 2px 8px rgba(0,0,0,0.25);
    text-align: center;
}
.analytics-card .label {
    font-size: 0.85rem;
    color: #8892b0;
    margin-bottom: 4px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}
.analytics-card .value {
    font-size: 1.6rem;
    font-weight: 700;
}
.analytics-card .value.green { color: #00c853; }
.analytics-card .value.red   { color: #ff1744; }
.analytics-card .value.neutral { color: #e0e0e0; }
</style>
"""


def _kpi_card(label: str, value: str, color: str = "neutral") -> str:
    """Return an HTML snippet for a single KPI card."""
    return (
        f'<div class="analytics-card">'
        f'<div class="label">{label}</div>'
        f'<div class="value {color}">{value}</div>'
        f'</div>'
    )


def _pnl_color(value: float) -> str:
    """Return CSS class name based on P&L sign."""
    if value > 0:
        return "green"
    if value < 0:
        return "red"
    return "neutral"


def _safe_float(val: Any) -> float:
    """Silently convert *val* to float, returning 0.0 on failure."""
    try:
        return float(val)
    except (ValueError, TypeError):
        return 0.0


# ====================================================================
#  Main entry point — called from the Streamlit app
# ====================================================================

def render_analytics_tab(journal: Any) -> None:
    """Render the full analytics dashboard inside a Streamlit tab/container.

    Args:
        journal: A ``TradeJournal`` instance (from
                 ``analytics.trade_journal``).
    """
    st.markdown(_CARD_CSS, unsafe_allow_html=True)

    # ── Header row with title + reset button ──
    hdr_col, days_col, reset_col = st.columns([3, 1, 1])
    with hdr_col:
        st.markdown("## 📊 Trade Analytics")
    with days_col:
        timeframe = st.selectbox(
            "Timeframe",
            ["7 Days", "30 Days", "All Time"],
            index=2,
            label_visibility="collapsed"
        )
        if timeframe == "7 Days":
            days = 7
        elif timeframe == "30 Days":
            days = 30
        else:
            days = 36500  # practically all time
    with reset_col:
        if st.button("🗑️ Reset", key="reset_journal", use_container_width=True,
                      help="Clear all trade journal entries"):
            st.session_state["_confirm_reset_journal"] = True

    # Confirmation dialog
    if st.session_state.get("_confirm_reset_journal", False):
        st.warning("⚠️ **This will permanently delete ALL trade journal entries.** Are you sure?")
        c1, c2, c3 = st.columns([1, 1, 3])
        with c1:
            if st.button("✅ Yes, Reset", key="confirm_reset_journal", type="primary",
                          use_container_width=True):
                journal.trades = []
                journal._save()
                st.session_state["_confirm_reset_journal"] = False
                st.success("✅ Trade journal cleared!")
                st.rerun()
        with c2:
            if st.button("❌ Cancel", key="cancel_reset_journal", use_container_width=True):
                st.session_state["_confirm_reset_journal"] = False
                st.rerun()

    analytics: Dict[str, Any] = journal.get_analytics(days=days)
    
    if days < 36500:
        import datetime
        from config import IST
        cutoff = datetime.datetime.now(tz=IST) - datetime.timedelta(days=days)
        all_trades = journal._filter_since(cutoff)
    else:
        all_trades: List[Dict[str, Any]] = journal.get_all_trades()

    if not all_trades:
        st.info(
            "🗒️ **No trades recorded yet.**\n\n"
            "Once your first trade is executed and journaled, "
            "analytics will appear here automatically."
        )
        return

    # ── 1. Summary KPI Cards ──────────────────────────────────────────
    _render_kpi_row(analytics)

    st.markdown("---")

    # ── 2. Cumulative P&L Chart ───────────────────────────────────────
    _render_cumulative_pnl(all_trades)

    # ── 3 & 4. Side-by-side: P&L by Index  |  Performance by Hour ─────
    col_left, col_right = st.columns(2)
    with col_left:
        _render_pnl_by_index(analytics)
    with col_right:
        _render_pnl_by_hour(analytics)

    # ── 5 & 6. Side-by-side: Win/Loss Pie  |  Signal Type Cards ──────
    col_pie, col_signal = st.columns(2)
    with col_pie:
        _render_win_loss_pie(analytics)
    with col_signal:
        _render_signal_type_cards(analytics)

    st.markdown("---")

    # ── 7. Recent Trades Table ────────────────────────────────────────
    _render_recent_trades(all_trades)


# ====================================================================
#  Section renderers
# ====================================================================

def _render_kpi_row(analytics: Dict[str, Any]) -> None:
    """Top row of KPI cards."""
    total = analytics.get("total_trades", 0)
    win_rate = analytics.get("win_rate", 0.0)
    total_pnl = analytics.get("total_pnl", 0.0)
    max_dd = analytics.get("max_drawdown", 0.0)
    rr = analytics.get("risk_reward_ratio", 0.0)
    streak = analytics.get("current_streak", {"type": "NONE", "count": 0})
    streak_text = f"{streak['type']} ×{streak['count']}"
    streak_color = "green" if streak["type"] == "WIN" else ("red" if streak["type"] == "LOSS" else "neutral")

    cols = st.columns(6)
    cards = [
        ("Total Trades", str(total), "neutral"),
        ("Win Rate", f"{win_rate:.1f}%", "green" if win_rate >= 50 else "red"),
        ("Total P&L", f"₹{total_pnl:,.0f}", _pnl_color(total_pnl)),
        ("Max Drawdown", f"₹{max_dd:,.0f}", "red" if max_dd > 0 else "neutral"),
        ("Risk : Reward", f"{rr:.2f}", "green" if rr >= 1.0 else "red"),
        ("Streak", streak_text, streak_color),
    ]
    for col, (label, value, color) in zip(cols, cards):
        col.markdown(_kpi_card(label, value, color), unsafe_allow_html=True)


def _render_cumulative_pnl(trades: List[Dict[str, Any]]) -> None:
    """Cumulative P&L line chart."""
    st.subheader("Cumulative P&L")
    cumulative: List[float] = []
    running = 0.0
    labels: List[str] = []

    for i, t in enumerate(trades, start=1):
        pnl = _safe_float(t.get("Actual P&L ₹", 0))
        running += pnl
        cumulative.append(running)
        entry_time = t.get("Entry Time", "")
        label = str(entry_time)[:16] if entry_time else f"Trade {i}"
        labels.append(label)

    df = pd.DataFrame({"Trade": labels, "Cumulative P&L (₹)": cumulative})

    # Colour the line based on sign at each point
    colors = [_GREEN if v >= 0 else _RED for v in cumulative]
    last_color = colors[-1] if colors else _GREEN

    fig = px.line(
        df,
        x="Trade",
        y="Cumulative P&L (₹)",
        markers=True,
    )
    fig.update_traces(line_color=last_color, marker_color=colors)
    fig.update_layout(
        template="plotly_dark",
        height=350,
        margin=dict(l=40, r=20, t=30, b=40),
        xaxis_title="",
        yaxis_title="₹",
    )
    st.plotly_chart(fig, use_container_width=True)


def _render_pnl_by_index(analytics: Dict[str, Any]) -> None:
    """Grouped bar chart of P&L by index."""
    st.subheader("P&L by Index")
    by_index = analytics.get("by_index", {})

    if not by_index:
        st.caption("No index-level data yet.")
        return

    rows = []
    for idx, stats in by_index.items():
        rows.append({"Index": idx, "Category": "Wins", "Count": stats.get("wins", 0)})
        rows.append({"Index": idx, "Category": "Losses", "Count": stats.get("losses", 0)})

    df = pd.DataFrame(rows)
    fig = px.bar(
        df,
        x="Index",
        y="Count",
        color="Category",
        barmode="group",
        color_discrete_map={"Wins": _GREEN, "Losses": _RED},
    )
    fig.update_layout(
        template="plotly_dark",
        height=320,
        margin=dict(l=40, r=20, t=30, b=40),
        legend_title_text="",
    )
    st.plotly_chart(fig, use_container_width=True)

    # Also show P&L numbers below
    pnl_rows = []
    for idx, stats in by_index.items():
        pnl_rows.append({"Index": idx, "Trades": stats["trades"], "P&L (₹)": round(stats["pnl"], 2)})
    st.dataframe(pd.DataFrame(pnl_rows), hide_index=True, use_container_width=True)


def _render_pnl_by_hour(analytics: Dict[str, Any]) -> None:
    """Bar chart of P&L by hour of entry."""
    st.subheader("Performance by Hour")
    by_hour = analytics.get("by_hour", {})

    if not by_hour:
        st.caption("No hourly data yet.")
        return

    rows = []
    for hour, stats in sorted(by_hour.items(), key=lambda x: int(x[0])):
        pnl = stats.get("pnl", 0.0)
        rows.append({"Hour": f"{int(hour):02d}:00", "P&L (₹)": round(pnl, 2)})

    df = pd.DataFrame(rows)
    colors = [_GREEN if v >= 0 else _RED for v in df["P&L (₹)"]]

    fig = px.bar(df, x="Hour", y="P&L (₹)")
    fig.update_traces(marker_color=colors)
    fig.update_layout(
        template="plotly_dark",
        height=320,
        margin=dict(l=40, r=20, t=30, b=40),
        xaxis_title="Hour of Day",
        yaxis_title="₹",
    )
    st.plotly_chart(fig, use_container_width=True)


def _render_win_loss_pie(analytics: Dict[str, Any]) -> None:
    """Pie chart: wins vs losses."""
    st.subheader("Win / Loss Distribution")
    wins = analytics.get("wins", 0)
    losses = analytics.get("losses", 0)

    if wins == 0 and losses == 0:
        st.caption("No completed trades yet.")
        return

    df = pd.DataFrame({
        "Result": ["Wins", "Losses"],
        "Count": [wins, losses],
    })
    fig = px.pie(
        df,
        values="Count",
        names="Result",
        color="Result",
        color_discrete_map={"Wins": _GREEN, "Losses": _RED},
        hole=0.45,
    )
    fig.update_layout(
        template="plotly_dark",
        height=320,
        margin=dict(l=20, r=20, t=30, b=20),
        legend=dict(orientation="h", y=-0.1),
    )
    st.plotly_chart(fig, use_container_width=True)


def _render_signal_type_cards(analytics: Dict[str, Any]) -> None:
    """Show cards for BUY CE vs BUY PE performance."""
    st.subheader("Signal Type Performance")
    by_signal = analytics.get("by_signal_type", {})

    if not by_signal:
        st.caption("No signal-level data yet.")
        return

    for signal_name in ("BUY CE", "BUY PE"):
        stats = by_signal.get(signal_name)
        if stats is None:
            continue
        trades = stats.get("trades", 0)
        wins = stats.get("wins", 0)
        pnl = stats.get("pnl", 0.0)
        wr = round((wins / trades) * 100, 1) if trades else 0.0
        color = _pnl_color(pnl)

        card_html = (
            f'<div class="analytics-card" style="text-align:left;">'
            f'<div class="label">{signal_name}</div>'
            f'<div style="display:flex; justify-content:space-between; margin-top:8px;">'
            f'  <span class="value {color}" style="font-size:1.2rem;">₹{pnl:,.0f}</span>'
            f'  <span style="color:#8892b0; font-size:0.9rem;">'
            f'    {trades} trades · {wr:.0f}% WR'
            f'  </span>'
            f'</div>'
            f'</div>'
        )
        st.markdown(card_html, unsafe_allow_html=True)

    # Show any other signal types that aren't BUY CE / BUY PE
    other_signals = {k: v for k, v in by_signal.items() if k not in ("BUY CE", "BUY PE")}
    for signal_name, stats in other_signals.items():
        trades = stats.get("trades", 0)
        wins = stats.get("wins", 0)
        pnl = stats.get("pnl", 0.0)
        wr = round((wins / trades) * 100, 1) if trades else 0.0
        color = _pnl_color(pnl)

        card_html = (
            f'<div class="analytics-card" style="text-align:left;">'
            f'<div class="label">{signal_name}</div>'
            f'<div style="display:flex; justify-content:space-between; margin-top:8px;">'
            f'  <span class="value {color}" style="font-size:1.2rem;">₹{pnl:,.0f}</span>'
            f'  <span style="color:#8892b0; font-size:0.9rem;">'
            f'    {trades} trades · {wr:.0f}% WR'
            f'  </span>'
            f'</div>'
            f'</div>'
        )
        st.markdown(card_html, unsafe_allow_html=True)


def _render_recent_trades(trades: List[Dict[str, Any]], count: int = 20) -> None:
    """Table of the last *count* trades with colour-coded P&L."""
    st.subheader(f"Recent Trades (last {count})")
    recent = trades[-count:] if len(trades) > count else list(trades)
    recent = list(reversed(recent))  # newest first

    if not recent:
        st.caption("No trades recorded.")
        return

    display_cols = [
        "trade_id", "Entry Time", "Index", "Signal", "Strike",
        "Entry Price", "Exit Price", "Actual P&L ₹", "Result",
    ]
    rows = []
    for t in recent:
        row: Dict[str, Any] = {}
        for col in display_cols:
            val = t.get(col, "—")
            row[col] = val
        rows.append(row)

    df = pd.DataFrame(rows, columns=display_cols)

    # Convert P&L column to numeric for colour formatting
    df["Actual P&L ₹"] = df["Actual P&L ₹"].apply(_safe_float)

    def _color_pnl(val: float) -> str:
        if val > 0:
            return f"color: {_GREEN}; font-weight: 600"
        if val < 0:
            return f"color: {_RED}; font-weight: 600"
        return "color: #e0e0e0"

    styled = df.style.map(_color_pnl, subset=["Actual P&L ₹"])  # type: ignore[arg-type]
    st.dataframe(styled, hide_index=True, use_container_width=True, height=500)
