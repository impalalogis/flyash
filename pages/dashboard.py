from __future__ import annotations

import streamlit as st

from views import dashboard as dashboard_view


def render() -> None:
    st.title("Dashboard")
    dashboard_view.render()
