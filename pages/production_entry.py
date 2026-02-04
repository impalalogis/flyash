from __future__ import annotations

import streamlit as st

from views import entry_production as entry_production_view


def render() -> None:
    st.title("Production Entry")
    entry_production_view.render()
