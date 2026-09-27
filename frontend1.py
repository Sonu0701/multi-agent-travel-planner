"""
Real-World Multi-Agent Travel Planner — Streamlit UI
======================================================
Modernized frontend with:
  - Persistent chat history (fixes "New Thread wipes previous chat")
  - Live agent execution trace via app.stream()
  - Card-based modern layout with tabs
  - Revision timeline for itinerary feedback loops
  - Markdown export of the final plan

Run with: streamlit run frontend1.py
"""

import json
import os
import uuid
from datetime import datetime

import streamlit as st
from langchain_core.messages import HumanMessage
from langgraph.types import Command

from graph import app
from budget_utils import parse_budget_breakdown
from pdf_export import generate_pdf, build_cost_chart_image

# --------------------------------------------------------------------------
# Config / constants
# --------------------------------------------------------------------------

HISTORY_FILE = "chat_sessions.json"

AGENT_ICON = {
    "flight_agent": "✈️",
    "hotel_agent": "🏨",
    "weather_agent": "🌦️",
    "budget_agent": "💰",
    "itinerary_agent": "📋",
    "supervisor": "🧭",
    "guardrail": "🛡️",
}

# --------------------------------------------------------------------------
# Page setup + styling
# --------------------------------------------------------------------------

st.set_page_config(
    page_title="Multi-Agent Travel Planner",
    page_icon="🧳",
    layout="wide",
)

st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap');

    html, body, [class*="css"] { font-family: 'Inter', sans-serif; }

    .app-header {
        background: linear-gradient(135deg, #6366f1 0%, #8b5cf6 50%, #ec4899 100%);
        padding: 28px 32px;
        border-radius: 16px;
        color: white;
        margin-bottom: 20px;
    }
    .app-header h1 { margin: 0; font-size: 1.8rem; }
    .app-header p { margin: 4px 0 0 0; opacity: 0.9; font-size: 0.95rem; }

    .card {
        background: var(--background-color, #ffffff0d);
        border: 1px solid rgba(128,128,128,0.25);
        border-radius: 14px;
        padding: 18px 20px;
        margin-bottom: 12px;
    }

    .badge {
        display: inline-block;
        padding: 4px 12px;
        border-radius: 999px;
        background: linear-gradient(135deg, #6366f1, #8b5cf6);
        color: white;
        font-size: 0.78rem;
        font-weight: 600;
        margin: 2px 4px 2px 0;
    }

    .metric-pill {
        display: inline-block;
        padding: 8px 16px;
        border-radius: 10px;
        border: 1px solid rgba(128,128,128,0.25);
        margin-right: 8px;
        font-size: 0.85rem;
    }

    .chat-history-item {
        padding: 8px 10px;
        border-radius: 8px;
        margin-bottom: 4px;
    }

    .revision-tag {
        font-size: 0.75rem;
        opacity: 0.7;
        font-style: italic;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    """
    <div class="app-header">
        <h1>🧳 Multi-Agent Travel Planner</h1>
        <p>Supervisor-routed specialist agents · real flight/hotel/weather data · human-in-the-loop approval</p>
    </div>
    """,
    unsafe_allow_html=True,
)

# --------------------------------------------------------------------------
# Persistent chat history helpers (local JSON — survives app restarts)
# --------------------------------------------------------------------------


def load_all_history() -> dict:
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save_all_history(history: dict) -> None:
    try:
        with open(HISTORY_FILE, "w") as f:
            json.dump(history, f, indent=2)
    except OSError:
        pass  # non-fatal — history just won't persist this run


def add_or_update_session(user_id: str, thread_id: str, title: str) -> None:
    history = load_all_history()
    user_sessions = history.setdefault(user_id, [])
    existing = next((s for s in user_sessions if s["thread_id"] == thread_id), None)
    if existing:
        if title:
            existing["title"] = title
        existing["updated_at"] = datetime.now().isoformat()
    else:
        user_sessions.append(
            {
                "thread_id": thread_id,
                "title": title or "New chat",
                "created_at": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat(),
            }
        )
    save_all_history(history)


def delete_session(user_id: str, thread_id: str) -> None:
    history = load_all_history()
    if user_id in history:
        history[user_id] = [s for s in history[user_id] if s["thread_id"] != thread_id]
        save_all_history(history)


def get_pending_interrupt(snapshot):
    """Pull the interrupt() payload back out of a LangGraph state snapshot, if any."""
    tasks = getattr(snapshot, "tasks", None) or []
    for task in tasks:
        interrupts = getattr(task, "interrupts", None)
        if interrupts:
            return interrupts[0].value
    return None


def load_thread_snapshot(thread_id: str):
    """Rehydrate a past thread's state from the Postgres checkpointer."""
    cfg = {"configurable": {"thread_id": thread_id}}
    try:
        snapshot = app.get_state(cfg)
    except Exception as e:  # checkpointer not configured, thread missing, etc.
        st.error(f"Couldn't load that chat's saved state: {e}")
        return None, False, None

    result = dict(snapshot.values) if snapshot.values else {}
    pending = get_pending_interrupt(snapshot)
    waiting = pending is not None
    if waiting:
        result["__interrupt__"] = [type("Interrupt", (), {"value": pending})()]
    return result, waiting, cfg


# --------------------------------------------------------------------------
# Session state bootstrap
# --------------------------------------------------------------------------

if "thread_id" not in st.session_state:
    st.session_state.thread_id = None
if "revision_history" not in st.session_state:
    st.session_state.revision_history = []  # list of past draft itineraries

# --------------------------------------------------------------------------
# Sidebar — session + chat history
# --------------------------------------------------------------------------

with st.sidebar:
    st.subheader("👤 Session")
    user_id = st.text_input("User ID", value=st.session_state.get("user_id", "demo_user"))
    st.session_state.user_id = user_id

    if st.button("➕ New Chat", use_container_width=True, type="primary"):
        new_thread = f"{user_id}_{uuid.uuid4().hex[:8]}"
        st.session_state.thread_id = new_thread
        st.session_state.pop("latest_result", None)
        st.session_state.pop("waiting_for_approval", None)
        st.session_state.revision_history = []
        add_or_update_session(user_id, new_thread, "New chat")
        st.rerun()

    st.divider()
    st.caption("📜 Chat history")

    all_history = load_all_history()
    user_sessions = sorted(
        all_history.get(user_id, []), key=lambda s: s["updated_at"], reverse=True
    )

    if not user_sessions:
        st.caption("No previous chats yet — start one above.")
    else:
        for sess in user_sessions:
            is_active = sess["thread_id"] == st.session_state.thread_id
            label = ("🟢 " if is_active else "") + sess["title"][:38]
            cols = st.columns([5, 1])
            with cols[0]:
                if st.button(label, key=f"open_{sess['thread_id']}", use_container_width=True):
                    st.session_state.thread_id = sess["thread_id"]
                    result, waiting, _ = load_thread_snapshot(sess["thread_id"])
                    st.session_state.latest_result = result
                    st.session_state.waiting_for_approval = waiting
                    st.session_state.revision_history = []
                    st.rerun()
            with cols[1]:
                if st.button("🗑️", key=f"del_{sess['thread_id']}"):
                    delete_session(user_id, sess["thread_id"])
                    if st.session_state.thread_id == sess["thread_id"]:
                        st.session_state.thread_id = None
                        st.session_state.pop("latest_result", None)
                    st.rerun()

    st.divider()
    if st.session_state.thread_id:
        st.caption(f"Active thread: `{st.session_state.thread_id}`")
    else:
        st.caption("No active chat — click **New Chat** to begin.")

# Make sure there is always a thread to work with
if st.session_state.thread_id is None:
    st.session_state.thread_id = f"{user_id}_{uuid.uuid4().hex[:8]}"

config = {"configurable": {"thread_id": st.session_state.thread_id}}

# --------------------------------------------------------------------------
# Query input
# --------------------------------------------------------------------------

query = st.text_area(
    "Travel request",
    placeholder="Plan a 7-day Japan trip under Rs. 2 lakh. I prefer budget hotels and no overnight flights.",
    height=110,
)

run_clicked = st.button("🚀 Create Draft Plan", type="primary")

if run_clicked:
    if not query.strip():
        st.warning("Enter a travel request first.")
    else:
        add_or_update_session(user_id, st.session_state.thread_id, query.strip()[:60])
        st.session_state.revision_history = []

        status_box = st.status("Agents are planning your trip...", expanded=True)
        accumulated_state = {
            "messages": [HumanMessage(content=query)],
            "user_id": user_id,
            "user_query": query,
            "flight_results": "",
            "hotel_results": "",
            "weather_results": "",
            "budget_results": "",
            "itinerary": "",
            "final_response": "",
            "llm_calls": 0,
            "revision_count": 0,
        }

        try:
            interrupt_payload = None
            for update in app.stream(dict(accumulated_state), config=config, stream_mode="updates"):
                for node_name, node_output in update.items():
                    if node_name == "__interrupt__":
                        # Capture it exactly as LangGraph gives it — this is the
                        # same tuple-of-Interrupt-objects shape app.invoke()
                        # returns under this key, so downstream .value.get(...)
                        # access works unchanged. (A previous version tried to
                        # rebuild this from get_state() afterward, which lost
                        # the actual payload and left the draft blank.)
                        interrupt_payload = node_output
                        continue
                    icon = AGENT_ICON.get(node_name, "⚙️")
                    status_box.write(f"{icon} **{node_name.replace('_', ' ').title()}** completed")
                    if isinstance(node_output, dict):
                        accumulated_state.update(node_output)

            final_snapshot = app.get_state(config)
            result = dict(final_snapshot.values) if final_snapshot.values else accumulated_state
            if interrupt_payload is not None:
                result["__interrupt__"] = interrupt_payload
            status_box.update(label="Draft ready ✅", state="complete", expanded=False)
        except Exception:
            # Fall back to a plain synchronous invoke if streaming isn't supported
            status_box.write("Streaming unavailable — running synchronously...")
            result = app.invoke(dict(accumulated_state), config=config)
            status_box.update(label="Draft ready ✅", state="complete", expanded=False)

        st.session_state.latest_result = result
        st.session_state.waiting_for_approval = "__interrupt__" in result

# --------------------------------------------------------------------------
# Results display
# --------------------------------------------------------------------------

result = st.session_state.get("latest_result")

if result:
    selected_agents = result.get("selected_agents", [])
    m1, m2, m3 = st.columns(3)
    m1.markdown(
        f"<div class='metric-pill'>🤖 LLM calls: <b>{result.get('llm_calls', 0)}</b></div>",
        unsafe_allow_html=True,
    )
    m2.markdown(
        f"<div class='metric-pill'>🔁 Revisions: <b>{result.get('revision_count', 0)}</b></div>",
        unsafe_allow_html=True,
    )
    m3.markdown(
        f"<div class='metric-pill'>🧩 Agents run: <b>{len(selected_agents)}</b></div>",
        unsafe_allow_html=True,
    )

    st.write("")
    tabs = st.tabs(["🧭 Overview", "✈️ Flights", "🏨 Hotels", "🌦️ Weather", "💰 Budget", "📋 Itinerary"])

    with tabs[0]:
        st.markdown("<div class='card'>", unsafe_allow_html=True)
        st.markdown("**Supervisor reasoning**")
        st.write(result.get("supervisor_reasoning", "—"))
        st.markdown("**Selected agents**")
        if selected_agents:
            badges = "".join(f"<span class='badge'>{AGENT_ICON.get(a, '')} {a}</span>" for a in selected_agents)
            st.markdown(badges, unsafe_allow_html=True)
        else:
            st.caption("No specialist agents were needed for this request.")
        st.markdown("</div>", unsafe_allow_html=True)

    def specialist_tab(tab, key, empty_msg):
        with tab:
            st.markdown("<div class='card'>", unsafe_allow_html=True)
            content = result.get(key, "")
            if content:
                st.markdown(content)
            else:
                st.caption(empty_msg)
            st.markdown("</div>", unsafe_allow_html=True)

    specialist_tab(tabs[1], "flight_results", "Flight agent wasn't needed for this request.")
    specialist_tab(tabs[2], "hotel_results", "Hotel agent wasn't needed for this request.")
    specialist_tab(tabs[3], "weather_results", "Weather agent wasn't needed for this request.")

    with tabs[4]:
        st.markdown("<div class='card'>", unsafe_allow_html=True)
        budget_text = result.get("budget_results", "")
        if budget_text:
            st.markdown(budget_text)
            breakdown = parse_budget_breakdown(budget_text)
            if breakdown:
                chart_col, _ = st.columns([1, 1])
                with chart_col:
                    st.markdown("**Cost breakdown**")
                    chart_buf = build_cost_chart_image(breakdown)
                    st.image(chart_buf, width=300)
            else:
                st.caption("Couldn't detect itemized cost categories in this text — chart skipped.")
        else:
            st.caption("Budget agent wasn't needed for this request.")
        st.markdown("</div>", unsafe_allow_html=True)

    with tabs[5]:
        st.markdown("<div class='card'>", unsafe_allow_html=True)
        if "__interrupt__" in result:
            draft = result["__interrupt__"][0].value.get("draft_itinerary", "")
        else:
            draft = result.get("itinerary", "")
        st.markdown(draft if draft else "_No draft yet._")
        st.markdown("</div>", unsafe_allow_html=True)

        if st.session_state.revision_history:
            with st.expander(f"📚 Revision history ({len(st.session_state.revision_history)} earlier draft(s))"):
                for i, rev in enumerate(st.session_state.revision_history, 1):
                    st.markdown(f"<span class='revision-tag'>Revision {i} — feedback: \"{rev['feedback']}\"</span>", unsafe_allow_html=True)
                    st.markdown(rev["draft"])
                    st.divider()

# --------------------------------------------------------------------------
# Human approval
# --------------------------------------------------------------------------

if st.session_state.get("waiting_for_approval"):
    st.divider()
    st.subheader("🧑‍⚖️ Human Approval")

    approved = st.radio("Approve this draft?", ["✅ Yes, looks good", "✏️ No, revise it"], horizontal=True)
    is_approved = approved.startswith("✅")
    feedback = st.text_area("Feedback for the itinerary agent", disabled=is_approved)

    if st.button("Submit Decision", type="primary"):
        if not is_approved:
            prior_draft = result["__interrupt__"][0].value.get("draft_itinerary", "") if result else ""
            st.session_state.revision_history.append({"draft": prior_draft, "feedback": feedback})

        with st.spinner("Updating plan..."):
            final_result = app.invoke(
                Command(resume={"approved": is_approved, "feedback": feedback}),
                config=config,
            )
        st.session_state.latest_result = final_result
        st.session_state.waiting_for_approval = "__interrupt__" in final_result
        add_or_update_session(user_id, st.session_state.thread_id, "")
        st.rerun()

# --------------------------------------------------------------------------
# Final response + export
# --------------------------------------------------------------------------

final_result = st.session_state.get("latest_result")
if final_result and final_result.get("final_response"):
    st.divider()
    st.subheader("🎉 Final Travel Plan")
    st.markdown("<div class='card'>", unsafe_allow_html=True)
    st.markdown(final_result["final_response"])
    st.markdown("</div>", unsafe_allow_html=True)

    dl_col1, dl_col2 = st.columns(2)
    with dl_col1:
        st.download_button(
            "⬇️ Download as Markdown",
            data=final_result["final_response"],
            file_name=f"travel_plan_{st.session_state.thread_id}.md",
            mime="text/markdown",
            use_container_width=True,
        )
    with dl_col2:
        try:
            pdf_bytes = generate_pdf(
                user_query=final_result.get("user_query", ""),
                final_response=final_result["final_response"],
                budget_results=final_result.get("budget_results", ""),
                selected_agents=final_result.get("selected_agents", []),
            )
            st.download_button(
                "📄 Download as PDF",
                data=pdf_bytes,
                file_name=f"travel_plan_{st.session_state.thread_id}.pdf",
                mime="application/pdf",
                use_container_width=True,
            )
        except Exception as e:
            st.caption(f"PDF export failed: {e}")