"""Executive summary + detailed analysis tab."""

from __future__ import annotations

import pandas as pd
import streamlit as st
from imga_core import AnalysisResult
from imga_core.metrics import calculate_executive_metrics, is_alert_state

from imga_dashboard.services import (
    analyze_dataframe,
    append_corrections,
    category_distribution,
    detect_text_column,
    load_dataframe,
    reset_pipeline_cache,
    results_to_dataframe,
)


def render(uploaded_file: object | None) -> None:
    if "results" not in st.session_state:
        if uploaded_file is None:
            _landing()
            return
        _process_upload(uploaded_file)
        return

    _executive_section(st.session_state["results"])
    st.divider()
    _detail_section(st.session_state["results"], st.session_state["dataframe"])
    st.divider()
    if st.button("🔄 New Analysis (Clear Data)", type="secondary"):
        for key in ("results", "dataframe", "text_col", "last_uploaded_name"):
            st.session_state.pop(key, None)
        st.rerun()


def _landing() -> None:
    st.header("CX Sentiment Dashboard 👋")
    st.markdown("**Upload a customer-review file (xlsx or csv) from the sidebar to begin.**")
    st.info(
        "File must contain a column named `Müşteri Yorumu`, `Review`, `Yorum`, or `comments`."
    )


def _process_upload(uploaded_file: object) -> None:
    try:
        df = load_dataframe(uploaded_file)
    except Exception as exc:
        st.error(f"Failed to read file: {exc}")
        return

    text_col = detect_text_column(df)
    if text_col is None:
        st.error("No supported text column found.")
        st.dataframe(df.head(3))
        return

    with st.spinner(f"Analyzing {len(df)} reviews..."):
        results = analyze_dataframe(df, text_col)

    st.session_state["dataframe"] = df
    st.session_state["text_col"] = text_col
    st.session_state["results"] = results
    st.rerun()


def _executive_section(results: list[AnalysisResult]) -> None:
    st.header("👔 Executive Summary")
    metrics = calculate_executive_metrics(results)

    c1, c2, c3 = st.columns(3)
    c1.metric("❤️ Sentiment Health Index", f"{metrics.shi_score}/100",
              delta=f"{metrics.shi_score - 50} vs baseline")
    c2.metric("🚨 Crisis Incidents", metrics.crisis_count, delta="critical",
              delta_color="inverse")
    c3.metric("📉 Total Reviews", metrics.total)

    if is_alert_state(results):
        st.warning(
            f"⚠️ Negative rate is {metrics.negative_rate:.1%} — above the 20% alert threshold."
        )

    st.subheader("🔥 Top Bottlenecks")
    if metrics.top_bottlenecks:
        chart_df = pd.DataFrame(metrics.top_bottlenecks, columns=["Category", "Count"])
        st.bar_chart(chart_df.set_index("Category"), color="#ff4b4b")
    else:
        st.info("No negative-side bottlenecks detected.")

    # --- Sprint 6: business-unit (category) distribution ----------------
    st.subheader("🏷️ Şikayet Birimleri Dağılımı")
    cat_df = category_distribution(results)
    if cat_df.empty:
        st.info("Kategori sınıflandırması bu çalıştırmada üretilmedi.")
    else:
        st.bar_chart(cat_df.set_index("Birim"), color="#4b9eff")
        manual_review_count = sum(
            1
            for r in results
            if r.categorization is not None and r.categorization.requires_manual_review
        )
        if manual_review_count:
            st.warning(
                f"⚠️ {manual_review_count} şikayet düşük güvenle sınıflandırıldı; "
                "manuel inceleme önerilir."
            )


def _detail_section(results: list[AnalysisResult], original_df: pd.DataFrame) -> None:
    st.header("🔍 Detailed Analysis & Correction")
    text_col: str = st.session_state["text_col"]
    enriched = results_to_dataframe(original_df, text_col, results)
    enriched["Fix This"] = False

    columns = [
        text_col, "Risk", "Sentiment", "Score",
        "Birim", "Güven", "Diğer İlgili Birimler",
        "Customer Perspective", "Company Perspective", "Summary", "SLA", "Fix This",
    ]
    columns = [c for c in columns if c in enriched.columns]

    edited = st.data_editor(
        enriched[columns],
        column_config={
            "Fix This": st.column_config.CheckboxColumn("Fix This", default=False),
        },
        disabled=[c for c in columns if c != "Fix This"],
        use_container_width=True,
        hide_index=True,
        key="detail_editor",
    )

    selected = edited[edited["Fix This"]]
    if selected.empty:
        return

    st.subheader("✏️ Corrections")
    correction_input = selected[[text_col, "Sentiment"]].rename(
        columns={"Sentiment": "Current Prediction"}
    )
    correction_input["Best Label"] = correction_input["Current Prediction"]
    correction_input["Reason"] = ""

    corrected = st.data_editor(
        correction_input,
        column_config={
            "Best Label": st.column_config.SelectboxColumn(
                "Correct Label",
                options=["POZITIF", "NÖTR", "NEGATIF"],
                required=True,
            ),
            "Current Prediction": st.column_config.TextColumn("Predicted", disabled=True),
            "Reason": st.column_config.TextColumn("Reason (optional)", width="large"),
        },
        disabled=[text_col, "Current Prediction"],
        use_container_width=True,
        hide_index=True,
        key="correction_editor",
    )

    if st.button("🚀 Save corrections", type="primary"):
        try:
            append_corrections(corrected, text_col)
            reset_pipeline_cache()
            st.success("Corrections saved. Future analyses will use these labels.")
            st.balloons()
        except Exception as exc:
            st.error(f"Save failed: {exc}")
