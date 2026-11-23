"""
CodingAgent - Provider-backed, text-only coding assistance.

This agent sends code-related text to a provider selected for Syntax. It has no
filesystem or process execution surface and never applies generated code.
"""

import logging

logger = logging.getLogger(__name__)


class CodingAgent:
    """Generate, debug, and refactor code through provider-backed text requests."""

    def __init__(self, api_manager=None):
        self.api_manager = api_manager
        self.available = True
        self.last_provider = None

    def generate_code(self, description: str, language: str = "python") -> str:
        """Generate code based on a textual description."""
        return self._request(
            "Write clear, correct code for the following request. Return code "
            "and concise implementation notes as text. Do not claim to have "
            "written or executed any files.",
            f"Language: {language}\nRequest: {description}",
        )

    def debug_code(self, code: str, error: str) -> str:
        """Explain and correct code given an error message."""
        return self._request(
            "Debug the supplied code. Explain the cause and return a corrected "
            "code example as text. Do not execute code or access files.",
            f"Code:\n{code}\n\nError:\n{error}",
        )

    def refactor_code(self, code: str, goal: str) -> str:
        """Refactor supplied code to meet a textual goal."""
        return self._request(
            "Refactor the supplied code for the stated goal. Return the refactored "
            "code and a brief rationale as text. Do not modify files.",
            f"Goal: {goal}\n\nCode:\n{code}",
        )

    def handle_request(
        self, task: str, original_request: str = "", language: str = "python"
    ) -> str:
        """Handle one coding task while retaining its original request context."""
        task_text = str(task or "").strip()
        original_text = str(original_request or "").strip() or task_text
        if not task_text:
            raise ValueError("Syntax requires a non-empty coding task")

        intent = self._classify_intent(task_text, original_text)
        instructions = {
            "generation": (
                "Write clear, correct code for the task. Return code and concise "
                "implementation notes as text. Do not claim to have written or "
                "executed any files."
            ),
            "debug": (
                "Debug the supplied code. Explain the cause and return a corrected "
                "code example as text. Do not execute code or access files."
            ),
            "refactor": (
                "Refactor the supplied code for the stated goal. Return the "
                "refactored code and a brief rationale as text. Do not modify files."
            ),
        }
        prompt = (
            f"Task: {task_text}\n"
            f"Language: {language}\n\n"
            "Original request:\n"
            f"{original_text}"
        )
        return self._request(instructions[intent], prompt)

    @staticmethod
    def _classify_intent(task: str, original_request: str):
        """Classify the coding intent without discarding the original context."""
        task_lower = task.lower()
        original_lower = original_request.lower()

        def contains(phrases, text):
            return any(phrase in text for phrase in phrases)

        if contains(("refactor", "simplify", "clean up", "readability"), original_lower):
            return "refactor"
        if contains(("debug", "fix", "error", "exception", "failing", "bug"), original_lower):
            return "debug"
        if contains(("refactor", "simplify", "clean up", "readability"), task_lower):
            return "refactor"
        if contains(("debug", "fix", "error", "exception", "failing", "bug"), task_lower):
            return "debug"
        if contains(("write", "generate", "create", "implement", "script"), task_lower):
            return "generation"
        return "generation"

    def _request(self, instruction: str, prompt: str) -> str:
        if self.api_manager is None:
            raise RuntimeError("Syntax requires a configured provider router")
        response = self.api_manager.route_request(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are Syntax, STEWARD's coding assistant. "
                        + instruction
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            agent_name="Syntax",
            require_tools=False,
        )
        content = self._validated_content(response)
        self.last_provider = response.get("_steward")
        return content

    @staticmethod
    def _validated_content(response):
        """Reject empty, malformed, or tool-bearing provider responses."""
        if not isinstance(response, dict):
            raise ValueError("Syntax provider returned a malformed response")
        choices = response.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ValueError("Syntax provider returned no response choices")
        choice = choices[0]
        if not isinstance(choice, dict):
            raise ValueError("Syntax provider returned a malformed response choice")
        message = choice.get("message")
        if not isinstance(message, dict):
            raise ValueError("Syntax provider returned a malformed response message")
        if message.get("tool_calls"):
            raise ValueError("Syntax provider returned an unsupported tool call")
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise ValueError("Syntax provider returned an empty response")
        return content.strip()
