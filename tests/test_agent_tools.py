import unittest
from unittest.mock import Mock, patch

from src.agent_tools import (
    fetch_corridor_conditions,
    query_telemetry,
    search_compliance_sop,
)


class AgentToolTests(unittest.TestCase):
    def test_corridor_conditions_formats_weather_and_risk(self):
        response = Mock()
        response.json.return_value = {
            "current_weather": {"temperature": 14.2, "windspeed": 12.0}
        }
        with patch("src.agent_tools.requests.get", return_value=response):
            result = fetch_corridor_conditions.invoke(
                {"latitude": 33.77, "longitude": -118.19}
            )

        self.assertIn("14.2°C", result)
        self.assertIn("High Transit Disruption", result)
        response.raise_for_status.assert_called_once()

    def test_telemetry_tool_reports_missing_store(self):
        with patch(
            "src.agent_tools.read_telemetry",
            side_effect=FileNotFoundError("Run scripts/ingest_legacy_data.py first."),
        ):
            result = query_telemetry.invoke({"filters": {}, "limit": 1})

        self.assertIn("Run scripts/ingest_legacy_data.py first", result)

    def test_telemetry_tool_passes_structured_filters(self):
        expected = [{"latitude": 33.8, "risk_classification": "High Risk"}]
        with patch("src.agent_tools.read_telemetry", return_value=expected) as read:
            result = query_telemetry.invoke(
                {
                    "filters": {"risk_classification": "High Risk"},
                    "limit": 3,
                }
            )

        self.assertIn("High Risk", result)
        read.assert_called_once_with(
            filters={"risk_classification": "High Risk"},
            limit=3,
        )

    def test_sop_tool_falls_back_to_local_policy_without_pinecone_key(self):
        with patch("src.agent_tools.PINECONE_API_KEY", None):
            result = search_compliance_sop.invoke({"query": "temperature limits"})

        self.assertIn("COMPLIANCE SOP CONTEXT", result)
        self.assertIn("Cold_Chain_Incident_SOP_v2.md", result)
        self.assertNotIn("PINECONE_API_KEY is required", result)


if __name__ == "__main__":
    unittest.main()
