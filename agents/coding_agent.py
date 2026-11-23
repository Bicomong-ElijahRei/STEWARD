"""
CodingAgent - Provider-backed, text-only coding assistance.

This agent sends code-related text to a provider selected for Syntax. It has no
filesystem or process execution surface and never applies generated code.
"""

import logging
import re

logger = logging.getLogger(__name__)


class CodingAgent:
    """Provide review, explanation, and code-change assistance as text."""

    INTENT_GENERATION = "generation"
    INTENT_DEBUGGING = "debugging"
    INTENT_REFACTORING = "refactoring"
    INTENT_REVIEW = "review"
    INTENT_EXPLANATION = "explanation"
    MAX_CODE_CONTEXT_RESULTS = 5
    MAX_CODE_CONTEXT_CHARS = 8000
    MAX_CODE_SNIPPET_CHARS = 2000

    _INTENT_INSTRUCTIONS = {
        INTENT_GENERATION: (
            "Write clear, correct code for the task. Return code and concise "
            "implementation notes as text. Do not claim to have written or "
            "executed any files."
        ),
        INTENT_DEBUGGING: (
            "Debug the supplied code. Explain the cause and return a corrected "
            "code example as text. Do not execute code or access files."
        ),
        INTENT_REFACTORING: (
            "Refactor the supplied code for the stated goal. Return the "
            "refactored code and a brief rationale as text. Do not modify files."
        ),
        INTENT_REVIEW: (
            "Review the supplied code as requested. Identify concrete defects, "
            "security concerns, maintainability issues, and improvements with "
            "file/line references when available. Do not rewrite the code and "
            "do not claim to have modified files."
        ),
        INTENT_EXPLANATION: (
            "Explain the supplied code's behavior, structure, logic, or purpose. "
            "Do not assume that code changes are requested, do not rewrite the "
            "code, and do not claim to have modified or executed files."
        ),
    }

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
        self,
        task: str,
        original_request: str = "",
        language: str = "python",
        provider_callback=None,
        code_context=None,
    ) -> str:
        """Handle one coding task while retaining its original request context.

        ``provider_callback`` optionally receives this request's provider
        metadata so callers do not need to read shared agent state.
        """
        task_text = str(task or "").strip()
        original_text = str(original_request or "").strip() or task_text
        if not task_text:
            raise ValueError("Syntax requires a non-empty coding task")

        intent = self._classify_intent(task_text, original_text)
        prompt = (
            f"Task: {task_text}\n"
            f"Language: {language}\n\n"
            "Original request:\n"
            f"{original_text}"
        )
        context_text = self._format_code_context(code_context)
        if context_text:
            prompt += "\n\nRetrieved code context:\n" + context_text
        return self._request(
            self._INTENT_INSTRUCTIONS[intent], prompt,
            provider_callback=provider_callback,
        )

    @classmethod
    def _format_code_context(cls, code_context):
        """Format a bounded number of retrieved snippets for the provider prompt."""
        if not isinstance(code_context, (list, tuple)):
            return ""
        sections = []
        remaining = cls.MAX_CODE_CONTEXT_CHARS
        for result in list(code_context)[:cls.MAX_CODE_CONTEXT_RESULTS]:
            if not isinstance(result, dict) or remaining <= 0:
                continue
            path = str(result.get("relative_path") or "unknown")
            start = result.get("start_line", 1)
            end = result.get("end_line", start)
            symbol = str(result.get("symbol") or "")
            content = str(result.get("content") or "").strip()
            if not content:
                continue
            snippet = content[:min(len(content), cls.MAX_CODE_SNIPPET_CHARS, remaining)]
            remaining -= len(snippet)
            header = f"--- {path}:{start}-{end}"
            if symbol:
                header += f" ({symbol})"
            sections.append(f"{header} ---\n{snippet}")
        return "\n\n".join(sections)

    @classmethod
    def _classify_intent(cls, task: str, original_request: str):
        """Classify explicit coding intent without losing request context.

        The original request is authoritative when it contains an explicit
        intent.  The delegated task is considered second so a review or
        explanation cannot be silently turned into code generation merely
        because it mentions a bug or because the task text is terse.
        """
        texts = [str(original_request or "").strip(), str(task or "").strip()]
        texts = [text for text in texts if text]

        def matches(patterns, text):
            return any(re.search(pattern, text, re.IGNORECASE) for pattern in patterns)

        review_patterns = (
            r"\b(?:code\s+)?review\b",
            r"\breview\s+(?:this|the|my)\b",
            r"\baudit\b",
            r"\binspect\s+(?:this|the|my)\b",
            r"\bassess\s+(?:this|the|my)\b",
        )
        explanation_patterns = (
            r"\bexplain\b",
            r"\bwhat\s+(?:does|is)\b",
            r"\bhow\s+(?:does|do)\b",
            r"\bwalk\s+me\s+through\b",
            r"\bdescribe\s+(?:this|the|how|what)\b",
            r"\bexplain\s+why\b",
        )
        debugging_patterns = (
            r"\bdebug\b",
            r"\bfix\b",
            r"\bcorrect\b",
            r"\btroubleshoot\b",
            r"\bdiagnose\b",
            r"\b(?:bug|error|exception|traceback|failing|broken|malfunction|not\s+working)\b",
        )
        refactoring_patterns = (
            r"\brefactor\b",
            r"\bsimplif(?:y|ied|ication)\b",
            r"\bclean\s+up\b",
            r"\brestructur(?:e|ing)\b",
            r"\breorganize\b",
            r"\bimprove\s+(?:readability|maintainability|structure)\b",
        )
        generation_patterns = (
            r"\bwrite\b",
            r"\bgenerate\b",
            r"\bcreate\b",
            r"\bimplement\b",
            r"\bbuild\b",
            r"\badd\b",
        )

        # Explicit inspection and explanation intents take precedence over
        # incidental defect vocabulary such as "bug" in a review request.
        for patterns, intent in (
            (review_patterns, cls.INTENT_REVIEW),
            (explanation_patterns, cls.INTENT_EXPLANATION),
            (debugging_patterns, cls.INTENT_DEBUGGING),
            (refactoring_patterns, cls.INTENT_REFACTORING),
            (generation_patterns, cls.INTENT_GENERATION),
        ):
            if any(matches(patterns, text) for text in texts):
                return intent
        return cls.INTENT_GENERATION

    def _request(self, instruction: str, prompt: str, provider_callback=None) -> str:
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
        provider_info = response.get("_steward")
        self.last_provider = provider_info
        if provider_callback is not None and provider_info:
            try:
                provider_callback(dict(provider_info))
            except Exception as exc:
                logger.warning("Syntax provider callback failed: %s", exc)
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
