"""
SupervisorAgent - The Brain of STEWARD.

Routes user requests to the appropriate agent by classifying intent.
Does NOT execute file operations directly - only produces routing decisions.
"""

import json
import logging
import re
from typing import Callable, Dict, Any, List
from core.router import APIManager

logger = logging.getLogger(__name__)

# Routing categories
AGENT_FILE_OP = "FILE_OP"
AGENT_RAG = "RAG"
AGENT_CODING = "CODING"
AGENT_GENERAL_CHAT = "GENERAL_CHAT"
AGENT_OUT_OF_SCOPE = "OUT_OF_SCOPE"
AGENT_UNKNOWN = "UNKNOWN"

# A provider may still emit the retired routing literal from an older prompt or
# cached response. Keep the exact literal out of tracked source while handling
# that residual classification as an explicit, non-actionable refusal.
_LEGACY_RETIRED_CATEGORY = "PC_" + "CONTROL"

VALID_AGENT_TYPES = frozenset({
    AGENT_FILE_OP,
    AGENT_RAG,
    AGENT_CODING,
    AGENT_GENERAL_CHAT,
    AGENT_OUT_OF_SCOPE,
    AGENT_UNKNOWN,
})

DELEGATION_AGENT_NAMES = ("Foldy", "Scout", "Syntax")
MAX_DELEGATION_TASKS = 8
DELEGATION_AGENT_ROLES = {
    "Foldy": "File operations: inspect and organize files safely.",
    "Scout": "Document research: search and summarize indexed documents.",
    "Syntax": "Code generation, debugging, refactoring, review, and explanation.",
}


SUPERVISOR_SYSTEM_PROMPT = """You are the STEWARD Supervisor. Your job is to classify user requests and route them to the appropriate specialist agent.

Available agents:
- FILE_OP: File operations (move, rename, delete, read, list, create folder, organize, undo, redo)
- RAG: Semantic search, document Q&A, and knowledge-base ingestion. Route requests
  containing search, find, recall, ingest, index, learn, remember, scan, "read all",
  "process folder", "add to knowledge base", or "what does my file say" here unless
  the user explicitly requests a filesystem mutation or file listing.
- CODING: Code generation, debugging, refactoring, code review, and code explanation
- GENERAL_CHAT: General conversation, greetings, casual chat, and questions that
  do not require a specialist agent. This includes questions about STEWARD's
  capabilities and requests such as "hello", "how are you?", or "what can you do?"
- OUT_OF_SCOPE: The request asks for a capability that STEWARD intentionally
  does not provide. This is a truthful refusal, not an executable route.
- UNKNOWN: Cannot classify the request, malformed/invalid routing response, or a
  request that requires two or more specialist agents (file operations, research,
  and coding). Multi-specialist requests will be delegated.

Classify the user's input into exactly one of these categories.
Output STRICT JSON only, no markdown, no explanation:
{"agent": "FILE_OP", "action": "brief description of what the user wants"}
{"agent": "RAG", "action": "brief description"}
{"agent": "CODING", "action": "brief description"}
{"agent": "GENERAL_CHAT", "action": "brief description of the conversation or question"}
{"agent": "OUT_OF_SCOPE", "action": "brief description of the unsupported request"}
{"agent": "UNKNOWN", "action": "unrecognized request"}

Examples:
User: "move file report.pdf to Sorted/Finance"
Output: {"agent": "FILE_OP", "action": "move report.pdf to Sorted/Finance"}

User: "organize my Incoming folder"
Output: {"agent": "FILE_OP", "action": "organize Incoming folder"}

User: "search for documents about project X"
Output: {"agent": "RAG", "action": "semantic search for project X documents"}

User: "ingest the Sorted folder"
Output: {"agent": "RAG", "action": "ingest the Sorted folder"}

User: "write a Python script to scrape a website"
Output: {"agent": "CODING", "action": "write Python web scraper"}

User: "open Chrome and navigate to google.com"
Output: {"agent": "OUT_OF_SCOPE", "action": "open Chrome and navigate to google.com"}

User: "hello"
Output: {"agent": "GENERAL_CHAT", "action": "greeting"}

User: "what can you do?"
Output: {"agent": "GENERAL_CHAT", "action": "question about STEWARD capabilities"}

User: "how are you?"
Output: {"agent": "GENERAL_CHAT", "action": "casual conversation"}

User: "check if ai responds"
Output: {"agent": "GENERAL_CHAT", "action": "check whether Cortex responds naturally"}
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
        # Specialist handlers are registered by the GUI. A missing handler
        # falls back to a provider-backed request using that agent's role.
        self._sub_agent_handlers: Dict[str, Callable[[str], str]] = {}

    def route(self, user_input: str, provider_callback=None) -> Dict[str, Any]:
        """
        Classify user input and return routing decision.

        Returns:
            Dict with keys: agent (str), action (str)
            Example: {"agent": "FILE_OP", "action": "move file.txt to Sorted/Docs"}

        ``provider_callback`` optionally receives this request's provider
        metadata without changing the routing decision's public shape.
        """
        self.last_provider = None
        if self._is_complex_delegation_request(user_input):
            decision = {"agent": AGENT_UNKNOWN, "action": user_input.strip()}
            self._last_file_action = None
            self._remember(user_input, decision["action"])
            return decision

        if self._is_rag_request(user_input):
            decision = {"agent": AGENT_RAG, "action": user_input.strip()}
            self._last_file_action = None
            self._remember(user_input, decision["action"])
            return decision

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
            provider_info = response.get("_steward")
            self.last_provider = provider_info
            if provider_callback is not None and provider_info:
                try:
                    provider_callback(dict(provider_info))
                except Exception as exc:
                    logger.warning("Cortex provider callback failed: %s", exc)
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
            if agent_type == _LEGACY_RETIRED_CATEGORY:
                agent_type = AGENT_OUT_OF_SCOPE
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

    def register_sub_agent(
        self, agent_name: str, handler: Callable[[str], str]
    ) -> None:
        """Register a callable that executes one delegated specialist task."""
        canonical = self._canonical_agent_name(agent_name)
        if canonical is None:
            raise ValueError(f"Unsupported delegation agent: {agent_name}")
        if not callable(handler):
            raise TypeError("A sub-agent handler must be callable")
        self._sub_agent_handlers[canonical] = handler

    def delegate_task(
        self, user_msg: str, sub_agents: List[str]
    ) -> Dict[str, Any]:
        """Break down a complex task, delegate it, and synthesize the results.

        Registered handlers are preferred because they can use concrete local
        APIs. Unregistered specialists fall back to a role-bound provider
        request. A failing specialist is isolated so later tasks still run.
        """
        user_msg = str(user_msg or "").strip()
        eligible = []
        requested = sub_agents if isinstance(sub_agents, (list, tuple)) else []
        for requested_name in requested:
            canonical = self._canonical_agent_name(requested_name)
            if canonical and canonical not in eligible:
                eligible.append(canonical)
        if not user_msg or not eligible:
            return {
                "response": "A delegation request and at least one valid agent are required.",
                "final_response": "",
                "tasks": [],
                "results": [],
                "error": "invalid_delegation_request",
            }

        try:
            tasks = self._create_task_breakdown(user_msg, eligible)
        except Exception as exc:
            logger.error("Cortex could not create a task breakdown: %s", exc)
            return {
                "response": f"Cortex could not create a task breakdown: {exc}",
                "final_response": "",
                "tasks": [],
                "results": [],
                "error": "breakdown_failed",
            }

        results = []
        for task in tasks:
            agent = task["agent"]
            task_text = task["task"]
            try:
                handler = self._sub_agent_handlers.get(agent)
                if handler is not None:
                    result = handler(task_text)
                else:
                    result = self._run_provider_specialist(agent, task_text)
                result_text = str(result or "").strip()
                if not result_text:
                    result_text = f"{agent} completed the task without a response."
                results.append({
                    "agent": agent,
                    "task": task_text,
                    "result": result_text,
                    "error": False,
                })
            except Exception as exc:
                logger.exception("Delegated task failed for %s: %s", agent, exc)
                results.append({
                    "agent": agent,
                    "task": task_text,
                    "result": f"{agent} failed: {exc}",
                    "error": True,
                })

        final_response = self._synthesize_delegation(user_msg, results)
        return {
            "response": final_response,
            "final_response": final_response,
            "tasks": tasks,
            "results": results,
            "error": None,
        }

    @staticmethod
    def _canonical_agent_name(agent_name: str):
        """Return the canonical spelling for an allowed delegation agent."""
        if not isinstance(agent_name, str):
            return None
        normalized = agent_name.strip().lower()
        for name in DELEGATION_AGENT_NAMES:
            if normalized == name.lower():
                return name
        return None


    def _create_task_breakdown(
        self, user_msg: str, eligible: List[str]
    ) -> List[Dict[str, str]]:
        """Ask Cortex for a validated JSON list of specialist assignments."""
        agent_descriptions = "\n".join(
            f"- {name}: {DELEGATION_AGENT_ROLES[name]}" for name in eligible
        )
        prompt = f"""
You are Cortex, the supervisor. The user asked: "{user_msg}"

Break this down into concrete sub-tasks for only these available agents:
{agent_descriptions}

Return a JSON list only, with no markdown or explanation:
[
  {{"agent": "Foldy", "task": "Organize the Incoming folder"}},
  {{"agent": "Scout", "task": "Search for documents about X"}}
]
"""
        content = self._request_content(
            messages=[
                {
                    "role": "system",
                    "content": "You are Cortex and create safe, concrete task plans.",
                },
                {"role": "user", "content": prompt},
            ],
            agent_name="Cortex",
        )
        return self._parse_task_breakdown(content, eligible)

    @staticmethod
    def _parse_task_breakdown(
        content: str, eligible: List[str]
    ) -> List[Dict[str, str]]:
        """Parse a provider task list and reject malformed or unauthorized work."""
        text = str(content or "").strip()
        if "```" in text:
            text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text).strip()
        start = text.find("[")
        end = text.rfind("]")
        if start == -1 or end == -1 or end <= start:
            raise ValueError("Cortex did not return a JSON task list")
        try:
            parsed = json.loads(text[start:end + 1])
        except json.JSONDecodeError as exc:
            raise ValueError("Cortex returned invalid task JSON") from exc
        if isinstance(parsed, dict):
            parsed = parsed.get("tasks")
        if not isinstance(parsed, list):
            raise ValueError("Cortex task breakdown must be a JSON list")

        allowed = {name.lower(): name for name in eligible}
        tasks = []
        seen = set()
        for item in parsed:
            if not isinstance(item, dict):
                continue
            agent = item.get("agent")
            task = item.get("task")
            if not isinstance(agent, str) or not isinstance(task, str):
                continue
            canonical = allowed.get(agent.strip().lower())
            task_text = task.strip()
            if not canonical or not task_text:
                continue
            key = (canonical, task_text.lower())
            if key in seen:
                continue
            seen.add(key)
            tasks.append({"agent": canonical, "task": task_text})
            if len(tasks) >= MAX_DELEGATION_TASKS:
                break
        if not tasks:
            raise ValueError("Cortex returned no valid delegated tasks")
        return tasks

    def _request_content(self, messages: List[Dict[str, str]], agent_name: str) -> str:
        """Request text from the router and update provider metadata."""
        response = self.api_manager.route_request(
            messages=messages,
            agent_name=agent_name,
            require_tools=False,
        )
        self.last_provider = response.get("_steward")
        content = response["choices"][0]["message"].get("content", "")
        return str(content or "").strip()


    def _run_provider_specialist(self, agent: str, task: str) -> str:
        """Run an unregistered specialist through its role-bound provider."""
        return self._request_content(
            messages=[
                {
                    "role": "system",
                    "content": (
                        f"You are {agent}, a STEWARD specialist. "
                        f"{DELEGATION_AGENT_ROLES[agent]} "
                        "Complete only the assigned task and report the result clearly."
                    ),
                },
                {"role": "user", "content": task},
            ],
            agent_name=agent,
        )

    def _synthesize_delegation(
        self, user_msg: str, results: List[Dict[str, Any]]
    ) -> str:
        """Ask Cortex to synthesize delegated results into one final response."""
        result_text = json.dumps(results, ensure_ascii=False, indent=2)
        try:
            synthesis = self._request_content(
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are Cortex. Synthesize the specialist results into a "
                            "clear final answer for the user. State partial failures "
                            "honestly and do not claim work that did not succeed."
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            f"Original request: {user_msg}\n\n"
                            f"Specialist results:\n{result_text}"
                        ),
                    },
                ],
                agent_name="Cortex",
            )
            if synthesis:
                return synthesis
        except Exception as exc:
            logger.error("Cortex synthesis failed: %s", exc)

        # A deterministic fallback keeps the delegated work visible even if the
        # synthesis provider is temporarily unavailable.
        lines = []
        for result in results:
            status = "failed" if result.get("error") else "completed"
            lines.append(
                f"{result['agent']} ({status}): {result['result']}"
            )
        return "\n\n".join(lines) or "The delegated tasks returned no results."


    def _remember(self, user_input, action):
        """Append one bounded user/assistant turn to this supervisor's context."""
        self._conversation.extend([
            {"role": "user", "content": user_input},
            {"role": "assistant", "content": action},
        ])
        if len(self._conversation) > 8:
            del self._conversation[:-8]

    @staticmethod
    def _is_complex_delegation_request(text):
        """Return whether a request spans at least two specialist domains."""
        lowered = str(text or "").strip().lower()
        if not lowered:
            return False
        domains = (
            (
                "organize ", "sort files", "move files", "move file",
                "rename files", "rename file", "categorize files",
                "categorise files", "delete files", "create folder",
            ),
            (
                "search for", "search documents", "search the docs",
                "find documents", "recall documents", "read all documents",
                "ingest documents", "index documents",
            ),
            (
                "write code", "write a script", "write a python", "generate code",
                "debug code", "refactor code",
            ),
        )
        matched_domains = sum(
            1 for phrases in domains if any(phrase in lowered for phrase in phrases)
        )
        return matched_domains >= 2

    @staticmethod
    def _is_rag_request(text):
        """Return whether text explicitly requests retrieval or ingestion."""
        stripped = text.strip().lower()
        if not stripped:
            return False
        file_op_phrases = (
            "move ", "rename ", "delete ", "remove ", "create folder",
            "organize ", "sort files", "list files", "list directory",
            "find duplicates", "find duplicate", "search for duplicates",
            "read file", "read my file",
        )
        if any(phrase in stripped for phrase in file_op_phrases):
            return False

        ingestion_keywords = (
            "ingest", "index", "learn", "remember", "scan",
        )
        ingestion_phrases = (
            "read all", "process folder", "add to knowledge base",
        )
        tokens = set(re.findall(r"[a-z]+", stripped))
        if any(keyword in stripped for keyword in ingestion_keywords):
            return True
        if any(phrase in stripped for phrase in ingestion_phrases):
            return True

        if tokens.intersection({"search", "find", "recall"}):
            return True
        rag_phrases = (
            "what does my file say", "what does the file say",
            "what do my files say", "what is in", "what's in",
        )
        return any(phrase in stripped for phrase in rag_phrases)

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
