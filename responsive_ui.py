from __future__ import annotations

from typing import Sequence

import streamlit as st
import streamlit.components.v1 as components


class ResponsiveUI:
    def __init__(
        self,
        *,
        default_width: int = 420,
        tablet_width: int = 300,
        mobile_width: int = 220,
        small_mobile_width: int = 180,
    ) -> None:
        self._default_width = default_width
        self._tablet_width = tablet_width
        self._mobile_width = mobile_width
        self._small_mobile_width = small_mobile_width
        self._inject_css()
        self._detect_screen_width()

    @property
    def screen_width(self) -> int:
        value = st.session_state.get("screen_width")
        try:
            return int(value)
        except (TypeError, ValueError):
            return 1200

    def _inject_css(self) -> None:
        if st.session_state.get("_responsive_ui_css"):
            return
        css = f"""
        <style>
        :root {{
            --responsive-input-width: {self._default_width}px;
        }}
        @media (max-width: 900px) {{
            :root {{
                --responsive-input-width: {self._tablet_width}px;
            }}
        }}
        @media (max-width: 600px) {{
            :root {{
                --responsive-input-width: {self._mobile_width}px;
            }}
        }}
        @media (max-width: 400px) {{
            :root {{
                --responsive-input-width: {self._small_mobile_width}px;
            }}
        }}
        div[data-testid="stTextInput"],
        div[data-testid="stNumberInput"],
        div[data-testid="stSelectbox"],
        div[data-testid="stMultiSelect"],
        div[data-testid="stDateInput"],
        div[data-testid="stTextArea"] {{
            width: 100%;
            max-width: var(--responsive-input-width);
        }}
        </style>
        """
        st.markdown(css, unsafe_allow_html=True)
        st.session_state["_responsive_ui_css"] = True

    def _detect_screen_width(self) -> None:
        st.markdown(
            """
            <script>
            try {
                const width = window.innerWidth || 1200;
                window.localStorage.setItem("screen_width", String(width));
            } catch (e) {}
            </script>
            """,
            unsafe_allow_html=True,
        )
        width = components.html(
            """
            <script>
            const sendWidth = () => {
                const width = window.innerWidth || 1200;
                const message = {
                    isStreamlitMessage: true,
                    type: "streamlit:setComponentValue",
                    value: width,
                };
                window.parent.postMessage(message, "*");
            };
            sendWidth();
            window.addEventListener("resize", sendWidth);
            </script>
            """,
            height=0,
        )
        if width:
            try:
                st.session_state["screen_width"] = int(width)
            except (TypeError, ValueError):
                st.session_state.setdefault("screen_width", 1200)
        else:
            st.session_state.setdefault("screen_width", 1200)

    def columns_for_screen(
        self,
        count_desktop: int,
        count_tablet: int,
        count_mobile: int,
    ) -> list[st.delta_generator.DeltaGenerator]:
        width = self.screen_width
        if width > 1000:
            count = count_desktop
        elif width >= 600:
            count = count_tablet
        else:
            count = count_mobile
        cols = st.columns(count)
        max_count = max(count_desktop, count_tablet, count_mobile)
        if count < max_count and cols:
            cols = cols + [cols[-1]] * (max_count - count)
        return cols

    def _widget_container(self, width: int | None) -> st.delta_generator.DeltaGenerator | None:
        if width is None or self.screen_width < 600:
            return None
        width_px = max(int(width), 160)
        ratio = min(width_px / max(self.screen_width, 1), 1.0)
        ratio = max(ratio, 0.2)
        cols = st.columns([ratio, 1 - ratio])
        return cols[0]

    def responsive_text_input(
        self,
        label: str,
        key: str,
        *,
        width: int | None = None,
        **kwargs,
    ) -> str:
        container = self._widget_container(width)
        if container:
            return container.text_input(label, key=key, **kwargs)
        return st.text_input(label, key=key, **kwargs)

    def responsive_number_input(
        self,
        label: str,
        key: str,
        *,
        width: int | None = None,
        **kwargs,
    ):
        container = self._widget_container(width)
        if container:
            return container.number_input(label, key=key, **kwargs)
        return st.number_input(label, key=key, **kwargs)

    def responsive_selectbox(
        self,
        label: str,
        options: Sequence,
        key: str,
        *,
        width: int | None = None,
        **kwargs,
    ):
        container = self._widget_container(width)
        if container:
            return container.selectbox(label, options, key=key, **kwargs)
        return st.selectbox(label, options, key=key, **kwargs)

    def responsive_multiselect(
        self,
        label: str,
        options: Sequence,
        key: str,
        *,
        width: int | None = None,
        **kwargs,
    ):
        container = self._widget_container(width)
        if container:
            return container.multiselect(label, options, key=key, **kwargs)
        return st.multiselect(label, options, key=key, **kwargs)

    def responsive_date_input(
        self,
        label: str,
        key: str,
        *,
        width: int | None = None,
        **kwargs,
    ):
        container = self._widget_container(width)
        if container:
            return container.date_input(label, key=key, **kwargs)
        return st.date_input(label, key=key, **kwargs)

    def responsive_text_area(
        self,
        label: str,
        key: str,
        *,
        width: int | None = None,
        **kwargs,
    ) -> str:
        container = self._widget_container(width)
        if container:
            return container.text_area(label, key=key, **kwargs)
        return st.text_area(label, key=key, **kwargs)
