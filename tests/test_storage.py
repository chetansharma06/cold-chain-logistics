import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.storage import (
    append_audit_event,
    read_audit_events,
    read_telemetry,
    write_telemetry_documents,
)


def sample_telemetry(latitude: float, risk: str, delay: float) -> dict[str, object]:
    return {
        "timestamp": "2021-01-01T00:00:00",
        "latitude": latitude,
        "longitude": -118.1,
        "current_temperature_c": 4.5,
        "cargo_condition_code": 1.0,
        "risk_classification": risk,
        "delay_probability": delay,
        "port_congestion_level": 2.0,
        "route_risk_index": 1.5,
        "ingest_flag": "Y",
    }


class JsonLineStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.telemetry_path = root / "telemetry.jsonl"
        self.audit_path = root / "audit.jsonl"
        self.environment = patch.dict(
            os.environ,
            {
                "TELEMETRY_STORE_PATH": str(self.telemetry_path),
                "AUDIT_STORE_PATH": str(self.audit_path),
            },
        )
        self.environment.start()

    def tearDown(self):
        self.environment.stop()
        self.temp_dir.cleanup()

    def test_write_and_filter_telemetry_documents(self):
        documents = [
            sample_telemetry(33.8, "High Risk", 0.8),
            sample_telemetry(34.1, "Low Risk", 0.2),
            sample_telemetry(33.9, "High Risk", 0.7),
        ]
        self.assertEqual(write_telemetry_documents(documents), 3)

        results = read_telemetry(
            filters={
                "risk_classification": "high risk",
                "min_latitude": 33.85,
                "min_delay_probability": 0.65,
            },
            limit=1,
        )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["latitude"], 33.9)
        self.assertEqual(results[0]["risk_classification"], "High Risk")

    def test_existing_telemetry_file_is_never_overwritten(self):
        original = sample_telemetry(33.8, "High Risk", 0.8)
        write_telemetry_documents([original])

        with self.assertRaises(FileExistsError):
            write_telemetry_documents([sample_telemetry(0, "Other", 0)])

        self.assertEqual(read_telemetry(limit=1), [original])

    def test_invalid_filters_and_limits_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unsupported filter"):
            read_telemetry(filters={"unlisted_field": 1})
        with self.assertRaisesRegex(ValueError, "between 1 and 50"):
            read_telemetry(limit=0)

    def test_malformed_telemetry_is_reported_with_line_number(self):
        self.telemetry_path.parent.mkdir(parents=True, exist_ok=True)
        self.telemetry_path.write_text("{bad json}\n", encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "line 1"):
            read_telemetry()

    def test_audit_events_append_and_read_newest_first(self):
        first = append_audit_event("session-a", "reasoner", "tool-a", "first")
        second = append_audit_event("session-b", "tools", "tool-b", "second")

        events = read_audit_events()

        self.assertEqual(len(events), 2)
        timestamps = [str(event["created_at"]) for event in events]
        self.assertEqual(timestamps, sorted(timestamps, reverse=True))
        self.assertEqual(
            {event["log_id"] for event in events},
            {first["log_id"], second["log_id"]},
        )
        first_record = json.loads(
            self.audit_path.read_text(encoding="utf-8").splitlines()[0]
        )
        self.assertEqual(first_record["content"], "first")


if __name__ == "__main__":
    unittest.main()
