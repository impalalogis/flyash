from __future__ import annotations

import pandas as pd
import streamlit as st

DEFAULT_MAX_DISPLAY_ROWS = 500


def prepare_display_df(
    data_frame: pd.DataFrame,
    *,
    max_rows: int = DEFAULT_MAX_DISPLAY_ROWS,
) -> tuple[pd.DataFrame, bool]:
    if data_frame is None or data_frame.empty or len(data_frame) <= max_rows:
        return data_frame, False
    half = max_rows // 2
    sampled = pd.concat(
        [data_frame.head(half), data_frame.tail(max_rows - half)],
        ignore_index=True,
    )
    return sampled, True


def render_dataframe(
    data_frame: pd.DataFrame,
    *,
    max_rows: int = DEFAULT_MAX_DISPLAY_ROWS,
    **kwargs: object,
) -> None:
    display_df, sampled = prepare_display_df(data_frame, max_rows=max_rows)
    if sampled:
        st.caption(
            f"Showing {len(display_df):,} of {len(data_frame):,} rows (sampled for performance)."
        )
    st.dataframe(display_df, **kwargs)
