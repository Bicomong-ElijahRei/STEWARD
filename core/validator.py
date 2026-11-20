import requests
import time
import json
import re
from datetime import datetime

# ── OpenAI-compatible chat completion payload helpers ──────────────────────

def _build_system_prompt() -> str:
    """Return a short neutral system prompt for the intelligence probe."""
    return (
        "You are a concise reasoning assistant. "
        "Answer the user request in exactly one word if possible. "
        "Do not add explanations, examples, or formatting."
    )


def _build_phone_number_prompt() -> str:
    """
    A deterministic logic puzzle that tests multi-step reasoning.
    Prompt: "Format the following phone number as: (XXX) XXX-XXXX.
              The digits are 5551234567.
              Output ONLY the formatted number."
    Expected: "(555) 123-4567"
    """
    return (
        "Format the following phone number as: (XXX) XXX-XXXX.\n"
        "The digits are 5551234567.\n\n"
        "Output ONLY the formatted number."
    )


def _build_tool_call_probe() -> tuple[str, dict]:
    """
    A minimal tool definition that the provider should acknowledge
    by emitting a tool-call JSON block.
    Returns (system_prompt, payload_dict).
    """
    system_prompt = (
        "You are a helpful assistant. If the user asks a question, "
        "you may use the available tools to answer accurately."
    )
    tools = [
        {
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "Get the current weather for a city",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "city": {"type": "string", "description": "City name"},
                    },
                    "required": ["city"],
                },
            },
        }
    ]
    payload = {
        "model": "placeholder",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": "What is the weather in Paris?"},
        ],
        "tools": tools,
        "tool_choice": "auto",
    }
    return system_prompt, payload


class ValidationResult:
    """Holds the benchmark results for one provider."""
    def __init__(self, provider: str):
        self.provider = provider
        self.speed_ms = None
        self.intel_tier = None
        self.supports_tools = None
        self.status = "unknown"
        self.error = None
        self.first_byte_ms = None
        self.success = False

    def model_dump(self) -> dict:
        return {
            "provider": self.provider,
            "speed_ms": self.speed_ms,
            "intel_tier": self.intel_tier,
            "supports_tools": self.supports_tools,
            "status": self.status,
            "error": self.error,
            "first_byte_ms": self.first_byte_ms,
            "success": self.success,
        }


# ── Health check (speed) ──────────────────────────────────────────────────

def health_check(base_url: str, api_key: str, timeout: float = 15.0) -> ValidationResult:
    """
    Send a minimal 'Say "OK"' payload and measure time from request start
    until we have the first byte of the response body.
    Returns a ValidationResult with speed_ms set on success.
    """
    result = ValidationResult(base_url)
    url = base_url.rstrip("/") + "/v1/chat/completions"

    payload = {
        "model": "benchmark",
        "messages": [{"role": "user", "content": "Say 'OK' and nothing else."}],
        "temperature": 0.0,
        "max_tokens": 5,
    }
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }

    start = time.perf_counter()
    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=timeout)
        first_byte = time.perf_counter()
        elapsed = int((first_byte - start) * 1000)

        if resp.status_code == 401:
            result.status = "invalid_key"
            result.error = f"HTTP 401 - Invalid API key for {base_url}"
            return result
        if resp.status_code == 429:
            result.status = "rate_limited"
            result.error = f"HTTP 429 - Rate limited for {base_url}"
            result.speed_ms = int(elapsed)
            return result

        try:
            data = resp.json()
        except ValueError:
            data = {"raw": resp.text[:200]}

        result.speed_ms = elapsed
        result.first_byte_ms = elapsed
        result.status = "healthy"
        result.success = True
        return result

    except requests.exceptions.Timeout:
        result.status = "timeout"
        result.error = f"Request to {base_url} timed out after {timeout}s"
        return result
    except requests.exceptions.ConnectionError as e:
        result.status = "connection_error"
        result.error = f"Cannot connect to {base_url} - {e}"
        return result
    except Exception as e:
        result.status = "error"
        result.error = str(e)
        return result


# ── Intelligence probe (tiering) ──────────────────────────────────────────

def intelligence_probe(base_url: str, api_key: str, timeout: float = 15.0) -> ValidationResult:
    """
    Send a standardized logic puzzle and parse the answer.
    Correct "(555) 123-4567"   -> Tier 1: Genius
    Partial match            -> Tier 2: Standard
    Gibberish                -> Tier 3: Fast
    Falls back to the speed probe result if the puzzle fails.
    """
    result = health_check(base_url, api_key, timeout=timeout)
    if not result.success:
        return result

    url = base_url.rstrip("/") + "/v1/chat/completions"
    system_prompt = _build_system_prompt()
    prompt = _build_phone_number_prompt()

    payload = {
        "model": "benchmark",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.0,
        "max_tokens": 10,
    }
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }

    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=timeout)
        if resp.status_code == 401:
            result.status = "invalid_key"
            result.error = f"HTTP 401 - Invalid API key for {base_url}"
            return result
        if resp.status_code == 429:
            result.status = "rate_limited"
            result.error = f"HTTP 429 - Rate limited for {base_url}"
            return result

        data = resp.json()
        content = ""
        for choice in data.get("choices", []):
            if "message" in choice and "content" in choice["message"]:
                content += choice["message"]["content"]

        match = re.search(r"\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}", content)
        clean = content.strip().replace("\n", " ").replace("  ", " ")

        if match and match.group(0) == "(555) 123-4567":
            result.intel_tier = "Tier 1: Genius"
        elif match:
            result.intel_tier = "Tier 2: Standard"
        else:
            result.intel_tier = "Tier 3: Fast"

        result.status = "healthy"
        result.success = True
        return result

    except Exception as e:
        result.error = f"Intelligence probe error: {e}"
        return result


# ── Tool Calling Check (function calling support) ─────────────────────────

def tool_calling_check(base_url: str, api_key: str, timeout: float = 15.0) -> ValidationResult:
    """
    Send a dummy tools array with a get_weather function. If the provider
    returns a valid tool-call JSON block in the response, supports_tools = True.
    """
    result = health_check(base_url, api_key, timeout=timeout)
    if not result.success:
        return result

    url = base_url.rstrip("/") + "/v1/chat/completions"
    system_prompt, payload = _build_tool_call_probe()

    try:
        resp = requests.post(
            url,
            json=payload,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
            timeout=timeout,
        )
        if resp.status_code == 401:
            result.status = "invalid_key"
            result.error = f"HTTP 401 - Invalid API key for {base_url}"
            return result
        if resp.status_code == 429:
            result.status = "rate_limited"
            result.error = f"HTTP 429 - Rate limited for {base_url}"
            return result

        data = resp.json()
        tool_calls = 0
        for choice in data.get("choices", []):
            message = choice.get("message", {})
            if "tool_calls" in message:
                tool_calls = len(message["tool_calls"])

        result.supports_tools = tool_calls > 0
        result.status = "healthy"
        result.success = True
        return result

    except Exception as e:
        result.error = f"Tool-call probe error: {e}"
        return result


# ── Full validation pipeline ─────────────────────────────────────────────

def validate_provider(
    name: str,
    base_url: str,
    api_key: str,
    model_name: str = "benchmark",
) -> ValidationResult:
    """
    Run health check, intelligence probe, and tool-calling check in sequence.
    Returns a ValidationResult whose fields can be written back to the DB.
    """
    result = ValidationResult(name)

    # 1. Speed
    speed = health_check(base_url, api_key)
    result.speed_ms = speed.speed_ms
    if speed.status == "invalid_key":
        result.status = "invalid_key"
        result.error = speed.error
        return result
    if speed.status == "rate_limited":
        result.status = "rate_limited"
        result.error = speed.error
        return result
    if speed.status != "healthy":
        result.status = speed.status
        result.error = speed.error
        return result

    # 2. Intelligence
    intel = intelligence_probe(base_url, api_key)
    if intel.success:
        result.intel_tier = intel.intel_tier
    elif intel.status == "invalid_key":
        result.status = "invalid_key"
        result.error = intel.error
        return result

    # 3. Tools
    tools = tool_calling_check(base_url, api_key)
    if tools.success:
        result.supports_tools = tools.supports_tools

    result.status = "healthy"
    result.success = True
    return result
