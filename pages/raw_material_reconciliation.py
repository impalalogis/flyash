from __future__ import annotations

import streamlit as st

from views import raw_material_reconciliation as raw_material_reconciliation_view


def render() -> None:
    st.title("Raw Material Reconciliation")
    raw_material_reconciliation_view.render()
