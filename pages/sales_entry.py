from __future__ import annotations

import streamlit as st

from views import entry_sales as entry_sales_view


def render() -> None:
    st.title("Sales Entry")
    entry_sales_view.render()
