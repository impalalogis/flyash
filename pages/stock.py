from __future__ import annotations

import streamlit as st

from views import stock as stock_view


def render() -> None:
    st.title("Stock")
    stock_view.render()
