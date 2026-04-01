from __future__ import annotations

import streamlit as st

from views import expenses as expenses_view


def render() -> None:
    st.title("Expenses")
    expenses_view.render()
