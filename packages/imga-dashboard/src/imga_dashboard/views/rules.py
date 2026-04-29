"""Smart Rules editor tab — CRUD over cx_rules.json."""

from __future__ import annotations

from typing import Any

import streamlit as st

from imga_dashboard.services import load_rules, reset_pipeline_cache, save_rules


def render() -> None:
    st.header("🧠 Smart Rules")
    st.markdown(
        "Add keyword-based rules to override the default perspective classifier. "
        "Saved rules apply to the next analysis."
    )

    rules = load_rules()
    col1, col2 = st.columns(2)
    with col1:
        _render_section(rules, "customer_rules", "Customer Perspective")
    with col2:
        _render_section(rules, "company_rules", "Company Root Cause")


def _render_section(
    rules: dict[str, list[dict[str, Any]]],
    key: str,
    title: str,
) -> None:
    st.subheader(title)
    st.caption("Any matching keyword (lowercase substring) -> Assign label.")

    with st.form(f"add_{key}"):
        kw = st.text_input("Keywords (comma separated)", key=f"kw_{key}")
        label = st.text_input("Label", key=f"lbl_{key}")
        submitted = st.form_submit_button("➕ Add")
        if submitted and kw and label:
            new_rule = {
                "keywords": [k.strip().lower() for k in kw.split(",") if k.strip()],
                "label": label,
            }
            rules[key].append(new_rule)
            save_rules(rules)
            reset_pipeline_cache()
            st.success(f"Added: {label}")
            st.rerun()

    if not rules.get(key):
        return
    st.markdown("**Active rules:**")
    for i, rule in enumerate(rules[key]):
        c1, c2 = st.columns([5, 1])
        c1.code(f"IF any of {rule['keywords']} THEN '{rule['label']}'")
        if c2.button("🗑️", key=f"del_{key}_{i}"):
            rules[key].pop(i)
            save_rules(rules)
            reset_pipeline_cache()
            st.rerun()
