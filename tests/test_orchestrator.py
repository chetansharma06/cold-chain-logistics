import unittest
from unittest.mock import Mock, patch

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from src import orchestrator


class OrchestratorTests(unittest.TestCase):
    def test_system_prompt_is_added_for_ui_messages(self):
        llm = Mock()
        llm.invoke.return_value = AIMessage(content="reply")
        with patch("src.orchestrator.llm_with_tools", llm):
            orchestrator.reasoning_node(
                {"messages": [HumanMessage(content="hello")]}
            )

        messages = llm.invoke.call_args.args[0]
        self.assertIsInstance(messages[0], SystemMessage)
        self.assertEqual(messages[0].content, orchestrator.system_instructions)

    def test_existing_system_prompt_is_not_duplicated(self):
        system_message = SystemMessage(content="custom instructions")
        llm = Mock()
        llm.invoke.return_value = AIMessage(content="reply")
        with patch("src.orchestrator.llm_with_tools", llm):
            orchestrator.reasoning_node({"messages": [system_message]})

        messages = llm.invoke.call_args.args[0]
        self.assertEqual(messages.count(system_message), 1)

    def test_ollama_error_includes_setup_steps(self):
        with patch("src.orchestrator.AGENT_LLM_SETTING", "OLLAMA"):
            message = orchestrator.describe_agent_error(
                ConnectionError("connection refused")
            )

        self.assertIn("Start Ollama", message)
        self.assertIn("ollama pull qwen2.5:7b", message)
        self.assertIn("Agent_llm to GEMINI, OPENAI, or DEEPSEEK", message)

    def test_deepseek_insufficient_balance_error_is_actionable(self):
        error = Exception(
            "Error code: 402 - Insufficient Balance "
            "(request_id: safe-to-ignore)"
        )
        with patch("src.orchestrator.AGENT_LLM_SETTING", "DEEPSEEK"):
            message = orchestrator.describe_agent_error(error)

        self.assertIn("insufficient balance", message)
        self.assertIn("Add credits", message)
        self.assertNotIn("request_id", message)

    def test_gemini_client_uses_configured_model_and_api_key(self):
        client = Mock()
        with (
            patch.dict(
                orchestrator.os.environ,
                {
                    "GEMINI_API_KEY": "test-key",
                    "GEMINI_MODEL": "gemini-test",
                },
            ),
            patch(
                "langchain_google_genai.ChatGoogleGenerativeAI",
                return_value=client,
            ) as gemini,
        ):
            result = orchestrator.create_gemini_llm()

        self.assertIs(result, client)
        gemini.assert_called_once_with(
            model="gemini-test",
            api_key="test-key",
            temperature=0,
        )

    def test_gemini_client_requires_api_key(self):
        with (
            patch.dict(orchestrator.os.environ, {"GEMINI_API_KEY": ""}),
            self.assertRaisesRegex(ValueError, "GEMINI_API_KEY is required"),
        ):
            orchestrator.create_gemini_llm()

    def test_content_to_text_removes_gemini_signature_metadata(self):
        content = [
            {
                "type": "text",
                "text": "Tier 2 is triggered for high-risk delayed shipments.",
                "extras": {"signature": "opaque-model-signature"},
            },
            {"type": "thought_signature", "signature": "private-metadata"},
        ]

        result = orchestrator.content_to_text(content)

        self.assertEqual(
            result,
            "Tier 2 is triggered for high-risk delayed shipments.",
        )
        self.assertNotIn("signature", result)


if __name__ == "__main__":
    unittest.main()
