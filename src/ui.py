import os
import sys
import uuid
import json
import hmac
from pathlib import Path
from dotenv import load_dotenv
import streamlit as st
import pandas as pd
from langchain_core.messages import HumanMessage, ToolMessage

# ==========================================
# 1. IMMEDIATE PATH & ENVIRONMENT RESOLUTION
# ==========================================
script_dir = Path(__file__).resolve().parent  # points to src/
project_root = script_dir.parent              # climbs to project root

if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

load_dotenv(project_root / ".env")

from src.storage import append_audit_event, read_audit_events

# Import the compiled graph and tools list dynamically
from src.orchestrator import (
    AGENT_LLM_SETTING,
    content_to_text,
    describe_agent_error,
    fde_agent,
)

# ==========================================
# 2. LOCAL AUDIT STORAGE
# ==========================================
def write_audit_log(session_id, node_name, tool_name, content):
    """Persist agent execution traces to the local audit file."""
    try:
        append_audit_event(session_id, node_name, tool_name, content)
    except (OSError, TypeError, ValueError) as exc:
        st.warning(f"Audit logging unavailable: {exc}")


def stream_agent_events(user_input, config):
    try:
        yield from fde_agent.stream(
            {"messages": [HumanMessage(content=user_input)]},
            config=config,
            stream_mode="updates",
        )
    except Exception as exc:
        yield {"_error": exc}


# ==========================================
# 3. PAGE CONFIGURATION & ENTERPRISE THEME
# ==========================================
st.set_page_config(
    page_title="FDE Supply Chain Dispatch Console",
    page_icon="🧊",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
<style>
    .stApp { background-color: #0B0E14; color: #E2E8F0; }
    div[data-testid="stSidebar"] { background-color: #111622; border-right: 1px solid #1E293B; }
    .stMarkdown code { background-color: #1E293B !important; color: #38BDF8 !important; }
</style>
""", unsafe_allow_html=True)

# ==========================================
# 4. MULTI-USER STATE & THREAD MANAGEMENT
# ==========================================
if "thread_id" not in st.session_state:
    st.session_state.thread_id = str(uuid.uuid4())

if "ui_messages" not in st.session_state:
    st.session_state.ui_messages = []

thread_config = {"configurable": {"thread_id": st.session_state.thread_id}}

# ==========================================
# 5. SIDEBAR NAVIGATION & METADATA
# ==========================================
with st.sidebar:
    st.image(str(script_dir / "image_L25X5q.png") if (script_dir / "image_L25X5q.png").exists() else "https://cdn-icons-png.flaticon.com/512/2830/2830305.png", width=65)
    st.title("FDE Command Center")
    
    app_mode = st.radio("System Mode", ["🧊 Dispatch Console", "🛡️ Security & Audit Logs"])
    
    st.markdown("---")
    st.caption(f"Session Token: `{st.session_state.thread_id[:8]}...`")
    st.markdown(f"**Reasoning Architecture:** `{AGENT_LLM_SETTING}`")
    
    st.markdown("---")
    if st.button("🗑️ Purge Dispatch Workspace Session", use_container_width=True):
        st.session_state.ui_messages = []
        st.session_state.thread_id = str(uuid.uuid4())
        st.rerun()

# ==========================================
# 6. VIEW ROUTING (DISPATCH VS AUDIT)
# ==========================================

if app_mode == "🧊 Dispatch Console":
    # ------------------------------------------
    # TAB 1: CHAT UI & AGENT EXECUTION
    # ------------------------------------------
    st.title("Cold-Chain Incident Control Dashboard")
    st.caption("Production Data Engineering Pipeline • Real-Time Decision Optimization Platform")

    for entry in st.session_state.ui_messages:
        with st.chat_message(entry["role"], avatar="👤" if entry["role"] == "user" else "🤖"):
            if "traces" in entry:
                for trace in entry["traces"]:
                    if trace["type"] == "tool_input":
                        st.markdown(f"**⚡ Intent Recognized:** `{trace['name']}`")
                        with st.expander(f"📥 View Generated Input ({trace['name']})", expanded=False):
                            st.json(trace["args"])
                    elif trace["type"] == "tool_output":
                        with st.expander(f"📤 View Raw Output ({trace['name']})", expanded=False):
                            st.code(trace["content"], language="text")
            st.markdown(content_to_text(entry["content"]))

    if user_input := st.chat_input("Query fleet telemetry, corridor updates, or compliance thresholds..."):
        
        st.session_state.ui_messages.append({"role": "user", "content": user_input})
        with st.chat_message("user", avatar="👤"):
            st.markdown(user_input)

        with st.chat_message("assistant", avatar="🤖"):
            final_response = ""
            execution_error = None
            current_traces = [] 
            
            with st.status("🧠 Initializing Core Reasoner Node...", expanded=True) as status:
                for event in stream_agent_events(user_input, thread_config):
                    if "_error" in event:
                        execution_error = describe_agent_error(event["_error"])
                        status.update(label="Agent execution failed", state="error", expanded=True)
                        break

                    for node_name, node_state in event.items():
                        
                        if node_name == "reasoner":
                            latest_msg = node_state["messages"][-1]
                            
                            # A. Intercept Tool Call Requests (Inputs)
                            if hasattr(latest_msg, "tool_calls") and latest_msg.tool_calls:
                                status.update(label="🧠 Agent generated tool parameters...")
                                for tool_call in latest_msg.tool_calls:
                                    st.markdown(f"**⚡ Intent Recognized:** `{tool_call['name']}`")
                                    with st.expander(f"📥 View Generated Input ({tool_call['name']})", expanded=False):
                                        st.json(tool_call['args'])
                                    
                                    current_traces.append({
                                        "type": "tool_input",
                                        "name": tool_call['name'],
                                        "args": tool_call['args']
                                    })
                                    
                                    write_audit_log(
                                        session_id=st.session_state.thread_id,
                                        node_name="reasoner",
                                        tool_name=tool_call['name'],
                                        content=json.dumps(tool_call['args'])
                                    )
                            
                            # B. Intercept Final Generation
                            response_text = content_to_text(latest_msg.content)
                            if response_text:
                                final_response = response_text
                                status.update(label="📝 Generating Operational Resolution Report...")
                                
                                write_audit_log(
                                    session_id=st.session_state.thread_id,
                                    node_name="reasoner_final",
                                    tool_name="LLM Text Synthesis",
                                    content=final_response
                                )
                                
                        elif node_name == "tools":
                            status.update(label="🔧 Executing Enterprise Subsystem Tools...")
                            for msg in node_state.get("messages", []):
                                if isinstance(msg, ToolMessage):
                                    with st.expander(f"📤 View Raw Output ({msg.name})", expanded=False):
                                        st.code(msg.content, language="text")
                                        
                                    current_traces.append({
                                        "type": "tool_output",
                                        "name": msg.name,
                                        "content": msg.content
                                    })
                                    
                                    write_audit_log(
                                        session_id=st.session_state.thread_id,
                                        node_name="tools",
                                        tool_name=msg.name,
                                        content=msg.content
                                    )
                
                if execution_error is None:
                    status.update(label="Incident Matrix Evaluation Complete", state="complete", expanded=False)
                
            if final_response:
                st.markdown(final_response)
                st.session_state.ui_messages.append({
                    "role": "assistant",
                    "content": final_response,
                    "traces": current_traces
                })
            elif execution_error is not None:
                error_message = f"Agent execution failed: {execution_error}"
                st.error(error_message)
                st.session_state.ui_messages.append({
                    "role": "assistant",
                    "content": error_message,
                })
            else:
                st.error("Agent completed without returning a response.")


elif app_mode == "🛡️ Security & Audit Logs":
    # ------------------------------------------
    # TAB 2: AUDIT LOG VIEWER (REQUIRES ADMIN CREDENTIALS FROM .ENV OR INPUT)
    # ------------------------------------------
    st.title("🛡️ Enterprise Agent Audit Trail")
    st.caption("Secure inspection of the local agent audit file")
    
    st.markdown("### Audit Authorization Gate")
    st.markdown(
        "Enter the audit credentials configured in `.env` as "
        "`AUDIT_ADMIN_USERNAME` and `AUDIT_ADMIN_PASSWORD`."
    )
    
    with st.form("admin_auth_form"):
        col1, col2 = st.columns(2)
        with col1:
            input_user = st.text_input(
                "Admin Username", value=os.getenv("AUDIT_ADMIN_USERNAME", "")
            )
        with col2:
            input_pass = st.text_input("Admin Password", type="password", value="")
            
        submit_admin = st.form_submit_button("Authenticate & Load Logs", use_container_width=True)

    if submit_admin:
        expected_admin_user = os.getenv("AUDIT_ADMIN_USERNAME")
        expected_admin_pass = os.getenv("AUDIT_ADMIN_PASSWORD")
        if not expected_admin_user or not expected_admin_pass:
            st.error(
                "Audit credentials are not configured. Set "
                "AUDIT_ADMIN_USERNAME and AUDIT_ADMIN_PASSWORD in .env."
            )
        elif (
            hmac.compare_digest(input_user, expected_admin_user)
            and hmac.compare_digest(input_pass, expected_admin_pass)
        ):
            try:
                events = read_audit_events()
                df = pd.DataFrame(events).rename(
                    columns={
                        "log_id": "LogID",
                        "created_at": "Timestamp",
                        "session_id": "SessionID",
                        "node_executed": "NodeExecuted",
                        "tool_name": "ToolName",
                        "content": "Content",
                    }
                )
                if not df.empty:
                    df["Timestamp"] = pd.to_datetime(df["Timestamp"], errors="raise")
                
                st.success("✅ Authenticated successfully as Admin.")
                
                if not df.empty:
                    st.dataframe(
                        df,
                        column_config={
                            "LogID": st.column_config.NumberColumn("ID", format="%d"),
                            "Timestamp": st.column_config.DatetimeColumn("Execution Time", format="DD/MM/YYYY-h:mm a"),
                            "SessionID": "Session Token",
                            "NodeExecuted": "Graph Node",
                            "ToolName": "Tool Triggered",
                            "Content": "Raw Payload Data"
                        },
                        hide_index=True,
                        use_container_width=True,
                        height=600
                    )
                else:
                    st.info("No audit logs found. Run a dispatch request first.")
                    
            except (OSError, TypeError, ValueError) as exc:
                st.error(f"Could not read the audit file: {exc}")
        else:
            st.error("❌ Invalid or unconfigured Administrator Credentials.")