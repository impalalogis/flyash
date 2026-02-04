from __future__ import annotations

import streamlit as st

from views import payments as payments_view


def render() -> None:
    st.title("Payments")
    payments_view.render()
