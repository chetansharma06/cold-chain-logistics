import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from typing import Annotated, TypedDict

from langchain_core.messages import BaseMessage, SystemMessage
from langgraph.graph import StateGraph, START
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition
from langgraph.checkpoint.memory import MemorySaver

# ==========================================
# 1. SETUP & PATH RESOLUTION
# ==========================================
script_dir = Path(__file__).resolve().parent
project_root = script_dir.parents[0]

if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.agent_tools import query_telemetry, fetch_corridor_conditions, search_compliance_sop

load_dotenv(project_root / ".env")

prompt_path = project_root / "src" / "prompts" / "system_prompt.txt"
system_instructions = prompt_path.read_text(encoding="utf-8")

class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]

# ==========================================
# 2. FACTORY INITIALIZATION: AGENT REASONER LLM
# ==========================================

AGENT_LLM_SETTING = os.getenv("Agent_llm", "OLLAMA").strip().upper()


def create_gemini_llm():
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError(
            "GEMINI_API_KEY is required when Agent_llm=GEMINI."
        )

    from langchain_google_genai import ChatGoogleGenerativeAI

    model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()
    if not model:
        raise ValueError("GEMINI_MODEL must not be empty.")

    return ChatGoogleGenerativeAI(
        model=model,
        api_key=api_key,
        temperature=0,
    )


def content_to_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        text_parts = []
        for part in content:
            if isinstance(part, str):
                text_parts.append(part)
            elif isinstance(part, dict) and isinstance(part.get("text"), str):
                text_parts.append(part["text"])
        return "".join(text_parts)
    return ""


if AGENT_LLM_SETTING == "OPENAI":
    print("[BOT] Brain Mode: Utilizing Cloud OpenAI Reasoner (gpt-4o)...")
    from langchain_openai import ChatOpenAI
    llm = ChatOpenAI(model="gpt-4o", temperature=0)

elif AGENT_LLM_SETTING == "GEMINI":
    print("[BOT] Brain Mode: Utilizing Google Gemini Reasoner...")
    llm = create_gemini_llm()

elif AGENT_LLM_SETTING == "DEEPSEEK":
    print("[BOT] Brain Mode: Utilizing Flagship DeepSeek Cloud Reasoner (deepseek-v4-pro)...")
    from langchain_openai import ChatOpenAI
    
    # Fully updated to match 2026 DeepSeek API parameters and endpoint contracts
    llm = ChatOpenAI(
        model="deepseek-v4-flash",                           # deepseek-v4-flash, deepseek-v4-pro
        temperature=0,
        openai_api_key=os.getenv("DEEPSEEK_API_KEY"),
        base_url="https://api.deepseek.com",     # Fixed connection string url endpoint
        max_tokens=2048,                                   # Gives the deep reasoner plenty of output runway
        # extra_body={
        #     "thinking": {"type": "enabled"},              # Activates DeepSeek Deep-Thinking mode
        #     "reasoning_effort": "high"                     # Drives maximal reasoning depth for logic maps
        # }
    )

else:  # FALLBACK / DEFAULT RUNNER MODE
    print("[BOT] Brain Mode: Local Fallback Activated. Binding Local Ollama (qwen2.5:7b)...")
    from langchain_ollama import ChatOllama
    llm = ChatOllama(model="qwen2.5:7b", temperature=0, num_predict=1024)

fde_tools = [query_telemetry, fetch_corridor_conditions, search_compliance_sop]
llm_with_tools = llm.bind_tools(fde_tools)


def describe_agent_error(error: Exception) -> str:
    if AGENT_LLM_SETTING == "OLLAMA":
        return (
            "The local Ollama service is not reachable. Start Ollama, then run "
            "`ollama pull qwen2.5:7b` if the configured model is not installed. "
            "Alternatively, set Agent_llm to GEMINI, OPENAI, or DEEPSEEK in .env and "
            "configure that provider's API key."
        )
    error_message = str(error)
    if "402" in error_message or "insufficient_balance" in error_message.lower():
        return (
            f"{AGENT_LLM_SETTING} rejected the request because the API account "
            "has insufficient balance. Add credits or resolve billing with the "
            "provider, then retry. Alternatively, configure another provider "
            "with an active API key and available balance."
        )
    return f"{AGENT_LLM_SETTING} request failed: {error_message}"


# ==========================================
# 3. GRAPH ARCHITECTURE ASSEMBLY
# ==========================================
def reasoning_node(state: AgentState):
    messages = state["messages"]
    if not any(isinstance(message, SystemMessage) for message in messages):
        messages = [SystemMessage(content=system_instructions), *messages]
    response = llm_with_tools.invoke(messages)
    return {"messages": [response]}

print("[GEAR] Compiling LangGraph FDE Orchestrator...")
graph_builder = StateGraph(AgentState)
graph_builder.add_node("reasoner", reasoning_node)
graph_builder.add_node("tools", ToolNode(fde_tools))

graph_builder.add_edge(START, "reasoner")
graph_builder.add_conditional_edges("reasoner", tools_condition)
graph_builder.add_edge("tools", "reasoner")

fde_agent = graph_builder.compile(checkpointer=MemorySaver())

# ==========================================
# 4. CHAT LOOP TESTING PANEL
# ==========================================
if __name__ == "__main__":
    print("\n" + "="*55)
    print("[ROCKET] FDE Supply Chain Orchestrator State Machine Online")
    print(f"   Configured Execution: [LLM: {AGENT_LLM_SETTING}] -> [Embeddings: {os.getenv('Embeddings_model', 'LOCAL')}]")
    print("="*55 + "\n")
    
    thread_config = {"configurable": {"thread_id": "production_test_1"}}
    
    while True:
        user_input = input("\nDispatcher > ")
        if user_input.lower() in ['exit', 'quit']:
            break
            
        events = fde_agent.stream({"messages": [("user", user_input)]}, config=thread_config, stream_mode="updates")
        for event in events:
            for node_name, node_state in event.items():
                if node_name == "tools":
                    print("[SYSTEM] Retrieving external data elements via ToolNode...")
                elif node_name == "reasoner":
                    latest_msg = node_state["messages"][-1]
                    response_text = content_to_text(latest_msg.content)
                    if response_text:
                        print(f"\n[BOT] FDE Agent:\n{response_text}")