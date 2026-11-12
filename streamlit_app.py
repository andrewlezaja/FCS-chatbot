"""
Streamlit chat UI for the maintenance chatbot.

Local: streamlit run streamlit_app.py (keys from .env)
Cloud: set ANTHROPIC_API_KEY, and optionally MAINTAINX_API_KEY for live
refresh, in the app's Secrets.
"""

import datetime
import os
import shutil
import sqlite3
import tempfile
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

# chatbot.py reads the API key at import, so copy secrets into the env first.
try:
    for key in ("ANTHROPIC_API_KEY", "MAINTAINX_API_KEY"):
        if key in st.secrets:
            os.environ[key] = st.secrets[key]
except Exception:
    pass  # no secrets file locally

if not os.environ.get("ANTHROPIC_API_KEY"):
    st.error(
        "**ANTHROPIC_API_KEY is not set.**\n\n"
        "On Streamlit Community Cloud: open **Manage app → Settings → Secrets**, "
        "add the line below (top-level, with quotes), **Save**, then **Reboot**:\n\n"
        "```toml\nANTHROPIC_API_KEY = \"sk-ant-...\"\n```\n\n"
        "Running locally: put the same line (without quotes) in a `.env` file."
    )
    st.stop()

import chatbot  # noqa: E402
import sync  # noqa: E402

REFRESH_TTL_SECONDS = 15 * 60
WORK_DB = Path(tempfile.gettempdir()) / "mx_data_working.db"
CAN_REFRESH = bool(os.environ.get("MAINTAINX_API_KEY")) and not chatbot.USING_DEMO_DB


@st.cache_resource
def _init_working_db():
    """Once per process, copy the committed DB to a writable temp file."""
    shutil.copyfile(chatbot.DB_PATH, WORK_DB)
    chatbot.reload_db(WORK_DB)
    return str(WORK_DB)


def _work_conn():
    """Write connection to the working DB."""
    conn = sqlite3.connect(WORK_DB)
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


@st.cache_data(ttl=REFRESH_TTL_SECONDS, show_spinner=False)
def _refresh_from_maintainx():
    """Fast refresh, at most once per TTL. Failures aren't cached, so the
    next rerun retries."""
    conn = _work_conn()
    try:
        summary = sync.refresh_work_orders(conn)
    finally:
        conn.close()
    return {"at": datetime.datetime.now(), **summary}


@st.cache_resource
def _full_refresh_state():
    """Summary of the last full refresh, shared across sessions."""
    return {}


st.set_page_config(page_title="MaintainX History Assistant", page_icon="🔧")

_init_working_db()

refresh_info = None
refresh_error = None
if CAN_REFRESH:
    try:
        with st.spinner("Refreshing MaintainX data…"):
            refresh_info = _refresh_from_maintainx()
    except Exception as e:
        refresh_error = str(e)

st.title("🔧 MaintainX History Assistant")
st.caption(
    "Ask about a machine's repair history, reliability patterns, or what the "
    "equipment manuals say. Answers are grounded in the MaintainX records — "
    "if it's not in the data, the assistant will say so."
)

# API message history and the visible transcript.
if "messages" not in st.session_state:
    st.session_state.messages = []
    st.session_state.transcript = []

for role, text in st.session_state.transcript:
    with st.chat_message(role):
        st.markdown(text)

prompt = st.chat_input("e.g. When was the DeviceNet card on M1 last replaced?")
if prompt:
    st.session_state.transcript.append(("user", prompt))
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("Checking the maintenance records…"):
            try:
                answer = chatbot.ask(prompt, st.session_state.messages)
            except Exception as e:
                answer = f"Sorry — something went wrong reaching the assistant: {e}"
        st.markdown(answer)

    st.session_state.transcript.append(("assistant", answer))

with st.sidebar:
    st.subheader("Data")
    if chatbot.USING_DEMO_DB:
        st.info(
            "Demo mode: answering from a small fictional dataset "
            "(demo/build_demo_db.py), not real MaintainX records."
        )
    elif not CAN_REFRESH:
        st.caption(
            "Live refresh is off — add MAINTAINX_API_KEY to the app's Secrets "
            "to pull MaintainX changes without a redeploy."
        )
    else:
        if refresh_error:
            st.warning(f"MaintainX refresh failed — answering from the last good data. ({refresh_error})")
        elif refresh_info:
            st.caption(
                f"Work orders refreshed {refresh_info['at'].strftime('%H:%M')} · "
                f"{refresh_info['work_orders']} on file · auto-refreshes every "
                f"{REFRESH_TTL_SECONDS // 60} min"
            )
        if st.button("Refresh data (~5 sec)"):
            _refresh_from_maintainx.clear()
            st.rerun()
        with st.expander("Equipment or manuals changed?"):
            st.caption(
                "Work orders refresh automatically. Use this only when "
                "machines, locations, or manual PDFs were added, renamed, or "
                "removed in MaintainX — it re-pulls everything, including "
                "manual text extraction."
            )
            if st.button("Full refresh (~2 min)"):
                try:
                    with st.spinner("Running full refresh — takes a minute or two…"):
                        conn = _work_conn()
                        try:
                            summary = sync.refresh_full(conn)
                        finally:
                            conn.close()
                    _full_refresh_state().update(
                        {"at": datetime.datetime.now(), **summary}
                    )
                except Exception as e:
                    st.warning(f"Full refresh failed — data unchanged. ({e})")
            full = _full_refresh_state()
            if full:
                st.caption(
                    f"Last full refresh {full['at'].strftime('%H:%M')} · "
                    f"{full['assets']} assets · {full['locations']} locations · "
                    f"{full['manuals_indexed']} manual(s) newly indexed"
                )

    st.subheader("Session usage")
    st.metric("Estimated API cost", f"${chatbot.usage_cost_usd():.3f}")
    u = chatbot.USAGE
    in_tokens = (
        u["input_tokens"]
        + u["cache_read_input_tokens"]
        + u["cache_creation_input_tokens"]
    )
    st.caption(f"{in_tokens:,} input tokens · {u['output_tokens']:,} output tokens")
    st.caption("Estimate only, at standard Sonnet 5 rates.")
    if st.button("Clear conversation"):
        st.session_state.messages = []
        st.session_state.transcript = []
        st.rerun()
