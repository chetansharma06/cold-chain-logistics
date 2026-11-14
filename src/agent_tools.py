import json
import os
import re
import sys
import requests
from pathlib import Path
from dotenv import load_dotenv

from langchain_core.tools import tool
from langchain_openai import OpenAIEmbeddings
from langchain_pinecone import PineconeVectorStore

# ==========================================
# 1. ENVIRONMENT & DYNAMIC INDEX ATTACHMENT
# ==========================================
script_dir = Path(__file__).resolve().parent
project_root = script_dir.parent  

if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

load_dotenv(dotenv_path=project_root / ".env")

from src.storage import read_telemetry

PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")


def get_cached_huggingface_embeddings(model_name: str):
    """
    Loads and locks the HuggingFace model weights into the machine's global RAM.
    If called again during any subsequent script rerun, it returns instantly.
    """
    import streamlit as st
    
    # We wrap the inner call with st.cache_resource dynamically 
    @st.cache_resource(show_spinner=False)
    def _load_model(name: str):
        print(f"MEMORY SEED: Permanently caching local model [{name}] in global RAM...")
        from langchain_huggingface import HuggingFaceEmbeddings
        return HuggingFaceEmbeddings(
            model_name=name,
            model_kwargs={'device': 'cpu'}
        )
    return _load_model(model_name)

EMBEDDINGS_MODEL_SETTING = os.getenv("Embeddings_model", "LOCAL").strip().upper()

if EMBEDDINGS_MODEL_SETTING == "OPENAI":
    print("[MODE] Connecting to Cloud OpenAI Index (1536 Dim Space)...")
    INDEX_NAME = "fde-sop-index-openai"
else :
    local_model_target = os.getenv("Local_Embedding_Model", "BAAI/bge-m3").strip()
    print(f"[MODE] Connecting to Local Fallback [{local_model_target}] Index (1024 Dim Space)...")
    INDEX_NAME = "fde-sop-index-local"


def get_sop_retriever():
    if not PINECONE_API_KEY:
        raise ValueError("PINECONE_API_KEY is required to search compliance SOPs.")

    if EMBEDDINGS_MODEL_SETTING == "OPENAI":
        embeddings = OpenAIEmbeddings()
    else:
        from langchain_huggingface import HuggingFaceEmbeddings

        model_name = os.getenv("Local_Embedding_Model", "BAAI/bge-m3").strip()
        try:
            import streamlit as st
            if st.runtime.exists():
                embeddings = get_cached_huggingface_embeddings(model_name)
            else:
                embeddings = HuggingFaceEmbeddings(
                    model_name=model_name,
                    model_kwargs={"device": "cpu"},
                )
        except ImportError:
            embeddings = HuggingFaceEmbeddings(
                model_name=model_name,
                model_kwargs={"device": "cpu"},
            )

    vector_store = PineconeVectorStore(index_name=INDEX_NAME, embedding=embeddings)
    return vector_store.as_retriever(search_kwargs={"k": 2})

# ==========================================
# 2. CORE FDE AGENT TOOLS
# ==========================================

@tool
def query_telemetry(
    filters: dict[str, str | float | int] | None = None,
    limit: int = 10,
) -> str:
    """
    Search local shipment telemetry using optional filters.
    Supported filters: risk_classification, min_latitude, max_latitude,
    min_longitude, max_longitude, min_temperature_c, max_temperature_c,
    min_delay_probability, and max_delay_probability. Limit results to 1-50.
    """
    try:
        rows = read_telemetry(filters=filters, limit=limit)
    except FileNotFoundError as exc:
        return str(exc)
    except (OSError, TypeError, ValueError) as exc:
        return f"Telemetry data error: {exc}"

    if not rows:
        return "No shipments matched the requested filters."
    return json.dumps(rows, ensure_ascii=False, indent=2)

@tool
def fetch_corridor_conditions(latitude: float, longitude: float) -> str:
    """
    Fetches real-time weather and corridor conditions from a live REST API for given GPS coordinates.
    Provides temperature, wind speed, and computed corridor congestion index.
    """
    try:
        url = f"https://api.open-meteo.com/v1/forecast?latitude={latitude}&longitude={longitude}&current_weather=true"
        response = requests.get(url, timeout=6)
        response.raise_for_status()
        
        payload = response.json().get("current_weather", {})
        temp = payload.get("temperature", "N/A")
        wind = payload.get("windspeed", 0.0)
        
        congestion_index = 8.5 if wind > 10.0 else 2.5
        status_note = "High Transit Disruption" if wind > 10.0 else "Corridor Normal"
        
        return (
            f"--- LIVE CORRIDOR TELEMETRY ---\n"
            f"Target GPS: {latitude}, {longitude}\n"
            f"External Temp: {temp}°C | Wind Speed: {wind} km/h\n"
            f"Corridor Risk: {status_note} (Congestion Index: {congestion_index}/10)\n"
            f"-------------------------------"
        )
    except Exception as e:
        return f"Corridor API Communication Failure: {str(e)}"

def _search_local_policy_files(query: str) -> str:
    """
    Offline fallback: search data/policy documents with a lightweight
    keyword scorer and return the same output format the Pinecone
    retriever produces. Used when the Pinecone index is unavailable.
    """
    policy_dir = project_root / "data" / "policy"
    if not policy_dir.exists():
        return "No matching compliance clauses found."

    terms = [t.lower() for t in re.findall(r"[a-z0-9]+", query) if len(t) > 2]
    stop = {"the", "and", "for", "with", "that", "this", "you", "your", "what", "are"}
    terms = [t for t in terms if t not in stop]
    if not terms:
        return "No matching compliance clauses found."

    scored = []  # (score, source_file, file_format, text)
    for file_path in sorted(policy_dir.glob("*")):
        if file_path.suffix.lower() not in {".md", ".txt"}:
            continue
        text = file_path.read_text(encoding="utf-8")
        lowered = text.lower()
        score = sum(lowered.count(term) for term in terms)
        if score > 0:
            scored.append((score, file_path.name, file_path.suffix.replace(".", "").upper(), text))

    if not scored:
        return "No matching compliance clauses found."

    scored.sort(key=lambda item: item[0], reverse=True)
    top = scored[:2]
    formatted_context = "\n\n".join(
        f"[Source: {source} | Format: {fmt}]\n{text}" for _, source, fmt, text in top
    )
    return f"--- COMPLIANCE SOP CONTEXT ---\n{formatted_context}\n------------------------------"


@tool
def search_compliance_sop(query: str) -> str:
    """
    Searches enterprise Standard Operating Procedures (SOPs) indexed in the Pinecone Vector DB.
    Use this to retrieve regulatory thresholds, cold-chain breach mitigations, and rerouting rules.
    """
    try:
        matched_docs = get_sop_retriever().invoke(query)
        if not matched_docs:
            return "No matching compliance clauses found."
            
        formatted_context = "\n\n".join(
            [f"[Source: {doc.metadata.get('source_file', 'SOP')} | Format: {doc.metadata.get('file_format', 'RAW')}]\n{doc.page_content}" for doc in matched_docs]
        )
        return f"--- COMPLIANCE SOP CONTEXT ---\n{formatted_context}\n------------------------------"
    except Exception as e:
        # Pinecone index unavailable (e.g. NOT_FOUND) -> fall back to local policy docs
        print(f"[SOP] Pinecone retrieval failed ({type(e).__name__}); using local policy fallback.")
        return _search_local_policy_files(query)

# ==========================================
# 3. LOCAL VERIFICATION
# ==========================================
if __name__ == "__main__":
    print("\n--- Testing Tool 1: Local Telemetry ---")
    print(query_telemetry.invoke({"filters": {}, "limit": 2}))
    
    print("\n--- Testing Tool 2: Live Corridor API ---")
    print(fetch_corridor_conditions.invoke({"latitude": 33.77, "longitude": -118.19}))
    
    print("\n--- Testing Tool 3: Pinecone Vector Retrieval ---")
    print(search_compliance_sop.invoke("What are the temperature rules for fresh perishables?"))
