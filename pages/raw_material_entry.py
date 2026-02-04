from __future__ import annotations

import streamlit as st

from views import entry_raw_material as entry_raw_material_view


def render() -> None:
    st.title("Raw Material Entry")
    entry_raw_material_view.render()
