"""Operational SLA-parameter tab."""

from __future__ import annotations

import streamlit as st

from imga_dashboard.services import load_params, reset_pipeline_cache, save_params


def render() -> None:
    st.header("⚙️ Operational SLA Parameters")
    st.markdown(
        "Define maximum allowed durations. The pipeline detects phrases like "
        "'5 gün' / '1 hafta' in shipping or warehouse context and emits a "
        "compliant or breach override accordingly."
    )

    current = load_params()

    c1, c2 = st.columns(2)
    with c1:
        st.subheader("📦 Shipping")
        shipping = st.number_input(
            "Max shipping days",
            min_value=1, max_value=30,
            value=int(current.get("max_shipping_days", 3)),
            help="Customer-facing delivery limit. Above this -> NEGATIF (-0.60).",
        )
    with c2:
        st.subheader("🏭 Warehouse")
        warehouse = st.number_input(
            "Max warehouse days",
            min_value=1, max_value=15,
            value=int(current.get("max_warehouse_days", 2)),
            help="Internal pick-and-pack limit. Above this -> NEGATIF (-0.60).",
        )

    if st.button("💾 Save parameters", type="primary"):
        save_params({"max_shipping_days": int(shipping), "max_warehouse_days": int(warehouse)})
        reset_pipeline_cache()
        st.success("SLA parameters saved. Next analysis will use these.")
