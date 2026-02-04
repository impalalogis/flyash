from __future__ import annotations

import streamlit as st

from views import master_data as master_data_view


def render() -> None:
    st.title("Master Data")
    master_data_view.render()
