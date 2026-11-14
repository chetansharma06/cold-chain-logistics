import json
import math
import os
import threading
import uuid
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
_TELEMETRY_FIELDS = {
    "timestamp",
    "latitude",
    "longitude",
    "current_temperature_c",
    "cargo_condition_code",
    "risk_classification",
    "delay_probability",
    "port_congestion_level",
    "route_risk_index",
    "ingest_flag",
}
_RANGE_FILTERS = {
    "min_latitude": ("latitude", "min"),
    "max_latitude": ("latitude", "max"),
    "min_longitude": ("longitude", "min"),
    "max_longitude": ("longitude", "max"),
    "min_temperature_c": ("current_temperature_c", "min"),
    "max_temperature_c": ("current_temperature_c", "max"),
    "min_delay_probability": ("delay_probability", "min"),
    "max_delay_probability": ("delay_probability", "max"),
}
_ALLOWED_FILTERS = {"risk_classification", *_RANGE_FILTERS}
_TELEMETRY_LOCK = threading.Lock()
_AUDIT_LOCK = threading.Lock()
FilterValue = str | float


def _store_path(environment_variable: str, default_relative_path: str) -> Path:
    configured_path = os.getenv(environment_variable, "").strip()
    path = Path(configured_path) if configured_path else Path(default_relative_path)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path


def get_telemetry_path() -> Path:
    return _store_path("TELEMETRY_STORE_PATH", "data/telemetry.jsonl")


def get_audit_path() -> Path:
    return _store_path("AUDIT_STORE_PATH", "data/audit_log.jsonl")


def _json_safe(value: object) -> object:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if hasattr(value, "item"):
        return _json_safe(value.item())
    if hasattr(value, "isoformat"):
        return value.isoformat()
    raise TypeError(f"Unsupported telemetry value type: {type(value).__name__}")


def write_telemetry_documents(documents: Iterable[Mapping[str, object]]) -> int:
    path = get_telemetry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    written = 0

    with _TELEMETRY_LOCK:
        with path.open("x", encoding="utf-8", newline="\n") as output:
            try:
                for document in documents:
                    if not isinstance(document, Mapping):
                        raise TypeError("Each telemetry document must be an object.")
                    missing_fields = _TELEMETRY_FIELDS.difference(document)
                    if missing_fields:
                        names = ", ".join(sorted(missing_fields))
                        raise ValueError(f"Telemetry document is missing fields: {names}.")
                    safe_document = {
                        key: _json_safe(value) for key, value in document.items()
                    }
                    output.write(
                        json.dumps(
                            safe_document,
                            ensure_ascii=False,
                            allow_nan=False,
                            separators=(",", ":"),
                        )
                    )
                    output.write("\n")
                    written += 1
                if written == 0:
                    raise ValueError("No telemetry documents were provided.")
                output.flush()
                os.fsync(output.fileno())
            except Exception:
                output.close()
                path.unlink(missing_ok=True)
                raise

    return written


def _read_document(line: str, path: Path, line_number: int) -> dict[str, object]:
    try:
        document = json.loads(line)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"{path} contains invalid data on line {line_number}."
        ) from exc
    if not isinstance(document, dict):
        raise ValueError(f"{path} contains a non-object record on line {line_number}.")
    return document


def _validate_filters(
    filters: Mapping[str, object] | None,
) -> dict[str, FilterValue]:
    if filters is None:
        return {}
    if not isinstance(filters, Mapping):
        raise ValueError("Filters must be an object.")

    unknown_filters = set(filters).difference(_ALLOWED_FILTERS)
    if unknown_filters:
        names = ", ".join(sorted(unknown_filters))
        raise ValueError(f"Unsupported filter(s): {names}.")

    validated: dict[str, FilterValue] = {}
    if "risk_classification" in filters:
        risk = filters["risk_classification"]
        if not isinstance(risk, str) or not risk.strip():
            raise ValueError("risk_classification must be a non-empty string.")
        validated["risk_classification"] = risk.strip().casefold()

    for key in _RANGE_FILTERS:
        if key not in filters:
            continue
        value = filters[key]
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
        ):
            raise ValueError(f"{key} must be a finite number.")
        validated[key] = float(value)

    return validated


def _matches_filters(
    document: Mapping[str, object],
    filters: Mapping[str, FilterValue],
) -> bool:
    risk = filters.get("risk_classification")
    if isinstance(risk, str):
        value = document.get("risk_classification")
        if not isinstance(value, str) or value.casefold() != risk:
            return False

    for filter_name, (field_name, direction) in _RANGE_FILTERS.items():
        if filter_name not in filters:
            continue
        value = document.get(field_name)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return False
        threshold = filters[filter_name]
        if not isinstance(threshold, float):
            raise TypeError(f"{filter_name} must be a number.")
        if direction == "min" and value < threshold:
            return False
        if direction == "max" and value > threshold:
            return False

    return True


def read_telemetry(
    filters: Mapping[str, object] | None = None,
    limit: int = 10,
) -> list[dict[str, object]]:
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 50:
        raise ValueError("limit must be an integer between 1 and 50.")

    validated_filters = _validate_filters(filters)
    path = get_telemetry_path()
    if not path.is_file():
        raise FileNotFoundError(
            f"Telemetry data is not initialized at {path}. "
            "Run scripts/ingest_legacy_data.py first."
        )

    results = []
    with path.open("r", encoding="utf-8") as source:
        for line_number, line in enumerate(source, start=1):
            document = _read_document(line, path, line_number)
            missing_fields = _TELEMETRY_FIELDS.difference(document)
            if missing_fields:
                raise ValueError(
                    f"{path} is missing telemetry fields on line {line_number}."
                )
            if _matches_filters(document, validated_filters):
                results.append(document)
                if len(results) >= limit:
                    break
    return results


def append_audit_event(
    session_id: str,
    node_name: str,
    tool_name: str,
    content: str,
) -> dict[str, str]:
    event = {
        "log_id": uuid.uuid4().hex,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "session_id": session_id,
        "node_executed": node_name,
        "tool_name": tool_name,
        "content": content,
    }
    if not all(isinstance(value, str) for value in event.values()):
        raise TypeError("Audit event values must be strings.")

    path = get_audit_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with _AUDIT_LOCK, path.open("a", encoding="utf-8", newline="\n") as output:
        output.write(json.dumps(event, ensure_ascii=False, allow_nan=False) + "\n")
        output.flush()
        os.fsync(output.fileno())
    return event


def read_audit_events() -> list[dict[str, object]]:
    path = get_audit_path()
    if not path.is_file():
        return []

    required_fields = {
        "log_id",
        "created_at",
        "session_id",
        "node_executed",
        "tool_name",
        "content",
    }
    with path.open("r", encoding="utf-8") as source:
        events = []
        for line_number, line in enumerate(source, start=1):
            event = _read_document(line, path, line_number)
            if not required_fields.issubset(event):
                raise ValueError(
                    f"{path} is missing audit fields on line {line_number}."
                )
            events.append(event)
    return sorted(
        events,
        key=lambda event: str(event.get("created_at", "")),
        reverse=True,
    )
