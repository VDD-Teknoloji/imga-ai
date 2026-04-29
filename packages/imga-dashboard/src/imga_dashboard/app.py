"""Streamlit entry point. Run with `streamlit run src/imga_dashboard/app.py`."""

from __future__ import annotations

import streamlit as st

from imga_dashboard import __version__
from imga_dashboard.views import dashboard as dashboard_view
from imga_dashboard.views import rules as rules_view
from imga_dashboard.views import sla as sla_view

st.set_page_config(
    page_title="imga CX Dashboard",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    .block-container { padding-top: 2.5rem; padding-bottom: 4rem; }
    .stMetric { background:#f8f9fa; border:1px solid #e9ecef; padding:14px; border-radius:6px; }
    </style>
    """,
    unsafe_allow_html=True,
)


def _sidebar() -> object | None:
    with st.sidebar:
        st.title("📊 imga CX")
        st.caption(f"v{__version__}")
        st.markdown("Upload customer reviews to analyze.")
        uploaded = st.file_uploader(
            "Excel or CSV",
            type=["xlsx", "csv"],
            key="main_upload",
        )

        if uploaded is not None:
            last = st.session_state.get("last_uploaded_name")
            if last != uploaded.name:
                for key in ("results", "dataframe", "text_col"):
                    st.session_state.pop(key, None)
                st.session_state["last_uploaded_name"] = uploaded.name

        st.markdown("---")
        st.caption(
            "Required column: `Müşteri Yorumu`, `Review`, `Yorum`, or `comments`."
        )
        return uploaded


def main() -> None:
    uploaded = _sidebar()
    tab_main, tab_rules, tab_sla = st.tabs(
        ["📊 Dashboard", "🧠 Smart Rules", "⚙️ SLA Parameters"]
    )
    with tab_main:
        dashboard_view.render(uploaded)
    with tab_rules:
        rules_view.render()
    with tab_sla:
        sla_view.render()


main()
