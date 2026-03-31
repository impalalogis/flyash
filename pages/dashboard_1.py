from __future__ import annotations

import streamlit as st

from views import dashboard_1 as dashboard_1_view


def render() -> None:
    st.title("Dashboard-1")
    dashboard_1_view.render()
