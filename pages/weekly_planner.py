from __future__ import annotations

import streamlit as st

from views import weekly_planner as weekly_planner_view


def render() -> None:
    st.title("Weekly Planner")
    weekly_planner_view.render()
