"""
SupervisorAgent - The Brain of STEWARD.

Routes user requests to the appropriate agent by classifying intent.
Does NOT execute file operations directly - only produces routing decisions.
"""

import json
import logging
from typing import Dict, Any
from core.router import APIManager

logger = logging.getLogger(__name__)

# Routing categories
AGENT_FILE_OP = "FILE_OP"
AGENT_PC_CONTROL = "PC_CONTROL"
AGENT_RAG = "RAG"
AGENT_CODING = "CODING"
AGENT_UNKNOWN = "UNKNOWN"

VALID_AGENT_TYPES = frozenset({
    AGENT_FILE_OP,
    AGENT_PC_CONTROL,
    AGENT_RAG,
    AGENT_CODING,
    AGENT_UNKNOWN,
})

SUPERVISOR_SYSTEM_PROMPT = """You are the STEWARD Supervisor. Your job is to classify user requests and route them to the appropriate specialist agent.

Available agents:
- FILE_OP: File operations (move, rename, delete, read, list, create folder, organize, undo, redo)
- PC_CONTROL: PC control / desktop automation (mouse, keyboard, screen, launch apps)
- RAG: Semantic search / document Q&A over stored knowledge
- CODING: Code generation, debugging, refactoring
- UNKNOWN: Cannot classify / general conversation

Classify the user's input into exactly one of these categories.
Output STRICT JSON only, no markdown, no explanation:
{"agent": "FILE_OP", "action": "brief description of what the user wants"}
{"agent": "PC_CONTROL", "action": "brief description"}
{"agent": "RAG", "action": "brief description"}
{"agent": "CODING", "action": "brief description"}
{"agent": "UNKNOWN", "action": "general conversation or unrecognized request"}

Examples:
User: "move file report.pdf to Sorted/Finance"
Output: {"agent": "FILE_OP", "action": "move report.pdf to Sorted/Finance"}

User: "organize my Incoming folder"
Output: {"agent": "FILE_OP", "action": "organize Incoming folder"}

User: "search for documents about project X"
Output: {"agent": "RAG", "action": "semantic search for project X documents"}

User: "write a Python script to scrape a website"
Output: {"agent": "CODING", "action": "write Python web scraper"}

User: "open Chrome and navigate to google.com"
Output: {"agent": "PC_CONTROL", "action": "open Chrome and navigate to google.com"}

User: "hello"
Output: {"agent": "UNKNOWN", "action": "greeting"}
"""


class SupervisorAgent:
    """
    Routes user input to the appropriate agent.
    Returns a strict JSON classification dict.
    """

    def __init__(self, api_manager: APIManager):
        self.api_manager = api_manager
        self._system_prompt = SUPERVISOR_SYSTEM_PROMPT
        self.last_provider = None
        # Instance-local, bounded context. Keep only recent user/assistant
        # turns and the latest file intent needed for short follow-ups.
        self._conversation = []
        self._last_file_action = None

    def route(self, user_input: str) -> Dict[str, Any]:
        """
        Classify user input and return routing decision.

        Returns:
            Dict with keys: agent (str), action (str)
            Example: {"agent": "FILE_OP", "action": "move file.txt to Sorted/Docs"}
        """
        messages = [
            {"role": "system", "content": self._system_prompt},
            *self._conversation,
            {"role": "user", "content": user_input},
        ]

        self.last_provider = None
        try:
            response = self.api_manager.route_request(
                messages=messages, agent_name="Cortex"
            )
            self.last_provider = response.get("_steward")
            content = response["choices"][0]["message"]["content"].strip()

            # Parse JSON from response
            # Handle potential markdown wrapping
            json_str = content
            if "```json" in content:
                start = content.find("```json") + 7
                end = content.find("```", start)
                json_str = content[start:end].strip()
            elif "```" in content:
                start = content.find("```") + 3
                end = content.find("```", start)
                json_str = content[start:end].strip()

            # Find JSON object
            start = json_str.find("{")
            end = json_str.rfind("}")
            if start != -1 and end != -1 and start < end:
                json_str = json_str[start : end + 1]

            parsed = json.loads(json_str)

            # Validate both the routing key and task text before either reaches
            # a specialist agent. An unknown category must never be allowed to
            # fall through as an actionable FILE_OP request.
            if not isinstance(parsed, dict):
                logger.warning(f"Invalid supervisor response: {parsed!r}")
                return {"agent": AGENT_UNKNOWN, "action": user_input}
            agent_type = parsed.get("agent")
            action = parsed.get("action")
            if (
                agent_type not in VALID_AGENT_TYPES
                or not isinstance(action, str)
                or not action.strip()
            ):
                logger.warning(f"Invalid supervisor response: {parsed!r}")
                return {"agent": AGENT_UNKNOWN, "action": user_input}

            decision = {"agent": agent_type, "action": action.strip()}
            if agent_type == AGENT_FILE_OP:
                decision["action"] = self._merge_file_follow_up(
                    user_input, decision["action"]
                )
                self._last_file_action = decision["action"]
            elif self._is_actionable_request(user_input):
                self._last_file_action = None
            self._remember(user_input, decision["action"])
            return decision

        except (json.JSONDecodeError, KeyError, IndexError) as e:
            logger.error(f"Failed to parse supervisor response: {e}")
            return {"agent": AGENT_UNKNOWN, "action": user_input}
        except Exception as e:
            logger.error(f"Supervisor routing failed: {e}")
            return {"agent": AGENT_UNKNOWN, "action": user_input}

    def _remember(self, user_input, action):
        """Append one bounded user/assistant turn to this supervisor's context."""
        self._conversation.extend([
            {"role": "user", "content": user_input},
            {"role": "assistant", "content": action},
        ])
        if len(self._conversation) > 8:
            del self._conversation[:-8]

    @staticmethod
    def _is_actionable_request(text):
        """Return whether text is a complete request rather than a noun phrase."""
        stripped = text.strip().lower()
        if not stripped:
            return False
        operation_words = {
            "create", "delete", "list", "move", "open", "organize", "read",
            "redo", "rename", "search", "sort", "undo", "write",
        }
        return any(
            word.strip(".,!?;:").strip('"') in operation_words
            for word in stripped.split()
        )

    def _merge_file_follow_up(self, user_input, action):
        """Merge an unambiguous short follow-up into the latest file intent."""
        if self._last_file_action is None:
            return action
        if self._is_actionable_request(user_input):
            return action
        if len(user_input.strip().split()) > 3:
            return action

        prior = self._last_file_action.strip()
        follow_up = action.strip()
        if not follow_up or follow_up.lower() == prior.lower():
            return action
        if prior.lower() in follow_up.lower():
            return follow_up
        return f"{prior} in {follow_up}"
