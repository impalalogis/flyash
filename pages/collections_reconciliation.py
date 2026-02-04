from __future__ import annotations

import streamlit as st

from views import reconciliation as reconciliation_view


def render() -> None:
    st.title("Collections & Reconciliation")
    reconciliation_view.render()
