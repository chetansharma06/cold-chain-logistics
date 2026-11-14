from pathlib import Path
import sys

import pandas as pd
from dotenv import load_dotenv

script_dir = Path(__file__).resolve().parent
project_root = script_dir.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

load_dotenv(project_root / ".env")

from src.storage import get_telemetry_path, write_telemetry_documents


data_path = project_root / "data" / "raw" / "dynamic_supply_chain_logistics_dataset.csv"

column_mapping = {
    "timestamp": "timestamp",
    "vehicle_gps_latitude": "latitude",
    "vehicle_gps_longitude": "longitude",
    "iot_temperature": "current_temperature_c",
    "cargo_condition_status": "cargo_condition_code",
    "risk_classification": "risk_classification",
    "delay_probability": "delay_probability",
    "port_congestion_level": "port_congestion_level",
    "route_risk_level": "route_risk_index",
}

print(f"Loading telemetry from {data_path}...")
source = pd.read_csv(data_path)
telemetry = source[list(column_mapping)].rename(columns=column_mapping)
telemetry["timestamp"] = pd.to_datetime(
    telemetry["timestamp"], errors="raise"
).map(lambda value: value.isoformat())
telemetry["ingest_flag"] = "Y"

try:
    count = write_telemetry_documents(telemetry.to_dict(orient="records"))
except FileExistsError as exc:
    raise SystemExit(
        f"Telemetry file already exists at {get_telemetry_path()}; import stopped to avoid "
        "overwriting existing data. Choose a new TELEMETRY_STORE_PATH to import a "
        "separate copy."
    ) from exc

print(f"Stored {count} telemetry documents in {get_telemetry_path()}.")
