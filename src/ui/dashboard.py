"""Dashboard: KPIs and charts computed from the database, plus recent activity."""

import html

import streamlit as st

from src import analytics, database
from src.query_service import QueryError
from src.ui import charts, components, session, theme


def _money(value: float) -> str:
    return f"${value:,.2f}"


def _mode_badge() -> str:
    if session.current_source() == "demo":
        return theme.badge("info", "Demo Mode · predefined SQL, works offline")
    return theme.badge("info", session.ai_mode_label())


def render() -> None:
    db_path = session.db_path()
    theme.page_header(
        "InsightSQL Dashboard",
        "Your Data, Intelligently Analyzed",
        "Ask questions about your sales data in plain English. Every answer comes from a "
        "validated, read-only SQL query against the live database.",
        _mode_badge(),
    )

    try:
        kpis = analytics.kpis(db_path)
    except QueryError as exc:
        st.error(f"**The dashboard could not be loaded:** {components.md_escape(exc.message)}")
        return

    if kpis.sales == 0:
        theme.empty_state("No sales data yet",
                          "Once the sales table has records, revenue, sales and charts appear here. "
                          "To load the sample data, run: python scripts/seed_database.py")
        _recent_activity(db_path)
        return

    _kpi_row(kpis)
    st.space("small")
    _charts(db_path)
    st.space("small")
    _recent_activity(db_path)


def _kpi_row(kpis: analytics.Kpis) -> None:
    cards = [
        ("revenue", "Total revenue", _money(kpis.revenue), "Sum of quantity × sale price over all sales."),
        ("sales", "Total sales", f"{kpis.sales:,}", f"Number of sale records ({kpis.units:,} units sold)."),
        ("products", "Products", f"{kpis.products:,}", "Products in the catalogue."),
        ("avg_sale", "Average sale value",
         _money(kpis.average_sale_value) if kpis.average_sale_value is not None else "—",
         "Total revenue ÷ number of sales."),
    ]
    for column, (key, label, value, help_text) in zip(st.columns(4), cards):
        with column, st.container(border=True, key=f"kpi_{key}"):
            st.metric(label, value, help=help_text)


def _charts(db_path) -> None:
    monthly = analytics.monthly_revenue(db_path)
    left, right = st.columns([3, 2])
    with left, st.container(border=True, key="chart_monthly"):
        st.markdown("**Revenue over time**")
        change = analytics.latest_month_change(monthly)
        if change and change.percent is not None:
            direction = "up" if change.percent >= 0 else "down"
            st.caption(components.md_escape(
                f"{change.month}: {_money(change.revenue)}, {direction} {abs(change.percent):.1f}% "
                f"from {change.previous_month} ({_money(change.previous_revenue)})."))
        charts.show(charts.line(monthly, "month", "revenue"), "Line chart of revenue by month", key="dash_monthly")
    with right, st.container(border=True, key="chart_region"):
        st.markdown("**Revenue by region**")
        st.caption("Total revenue per sales region.")
        charts.show(charts.bar(analytics.revenue_by_region(db_path), "region", "revenue", color="#22D3EE"),
                    "Bar chart of revenue by region", key="dash_region")

    left, right = st.columns(2)
    with left, st.container(border=True, key="chart_category"):
        st.markdown("**Revenue by product category**")
        st.caption("Total revenue per category.")
        charts.show(charts.bar(analytics.revenue_by_category(db_path), "category", "revenue"),
                    "Bar chart of revenue by product category", key="dash_category")
    with right, st.container(border=True, key="chart_products"):
        st.markdown("**Top products by revenue**")
        st.caption("The five products with the highest revenue.")
        charts.show(charts.bar(analytics.top_products(db_path), "product_name", "revenue", color="#A78BFA"),
                    "Bar chart of the five products with the highest revenue", key="dash_products")


def _recent_activity(db_path) -> None:
    head, action = st.columns([3, 1], vertical_alignment="bottom")
    head.subheader("Recent activity")
    if action.button("Ask the AI Analyst", key="cta_analyst", type="primary", icon=":material/forum:",
                     width="stretch"):
        st.switch_page(session.PAGES["analyst"])

    rows = database.recent_history(db_path, limit=5)
    if not rows:
        theme.empty_state("No questions asked yet", "Questions you ask in the AI Analyst will appear here.")
        return
    with st.container(key="recent_activity"):
        for row in rows:
            with st.container(border=True, key=f"card_recent_{row['history_id']}"):
                st.html(f'{theme.badge(row["status"])} '
                        f'<span class="isql-meta">&nbsp;{html.escape(components.format_time(row["created_at"]))}</span>')
                st.markdown(components.md_escape(row["question"]))
                if row["generated_sql"]:
                    with st.expander("SQL used"):
                        st.code(row["generated_sql"], language="sql", wrap_lines=True)
        if st.button("View full history", key="cta_history", icon=":material/history:"):
            st.switch_page(session.PAGES["history"])
