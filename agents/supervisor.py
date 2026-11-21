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

    def route(self, user_input: str) -> Dict[str, Any]:
        """
        Classify user input and return routing decision.

        Returns:
            Dict with keys: agent (str), action (str)
            Example: {"agent": "FILE_OP", "action": "move file.txt to Sorted/Docs"}
        """
        messages = [
            {"role": "system", "content": self._system_prompt},
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

            # Validate required fields
            if "agent" not in parsed or "action" not in parsed:
                logger.warning(f"Invalid supervisor response: {parsed}")
                return {"agent": AGENT_UNKNOWN, "action": user_input}

            return parsed

        except (json.JSONDecodeError, KeyError, IndexError) as e:
            logger.error(f"Failed to parse supervisor response: {e}")
            return {"agent": AGENT_UNKNOWN, "action": user_input}
        except Exception as e:
            logger.error(f"Supervisor routing failed: {e}")
            return {"agent": AGENT_UNKNOWN, "action": user_input}