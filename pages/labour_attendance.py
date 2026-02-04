from __future__ import annotations

import streamlit as st

from views import labour_attendance as labour_attendance_view


def render() -> None:
    st.title("Labour Attendance")
    labour_attendance_view.render()
