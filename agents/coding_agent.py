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
        self.last_provider = response.get("_steward")
        content = response["choices"][0]["message"].get("content", "")
        return str(content or "").strip()
