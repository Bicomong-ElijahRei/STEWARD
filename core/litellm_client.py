"""
LiteLLM client with fallback logic for STEWARD.

Supports a configurable fallback chain: Gemini Flash -> Groq -> OpenRouter.
API keys are loaded from environment variables via python-dotenv.
"""

import os
import json
import logging
from typing import Optional, Dict, Any, List

from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

logger = logging.getLogger(__name__)

# Default fallback model chain
DEFAULT_FALLBACK_CHAIN = [
    {"provider": "gemini", "model": "gemini-2.0-flash-exp", "api_key_env": "GEMINI_API_KEY"},
    {"provider": "groq", "model": "llama-3.1-8b-instant", "api_key_env": "GROQ_API_KEY"},
    {"provider": "openrouter", "model": "anthropic/claude-3-haiku", "api_key_env": "OPENROUTER_API_KEY"},
]


class LiteLLMClient:
    """
    A LiteLLM wrapper that attempts multiple providers with fallback.

    Usage:
        client = LiteLLMClient()
        response = client.complete(messages, tools=tool_definitions)
    """

    def __init__(self, fallback_chain: Optional[List[Dict[str, str]]] = None):
        self.fallback_chain = fallback_chain or DEFAULT_FALLBACK_CHAIN
        self._import_litellm()

    def _import_litellm(self):
        """Lazy import of litellm to avoid hard dependency at import time."""
        global litellm
        try:
            import litellm
            litellm.drop_params = True  # Gracefully drop unsupported params
        except ImportError:
            logger.error("litellm package not installed. Run: pip install litellm python-dotenv")
            raise

    def _get_api_key(self, env_var: str) -> Optional[str]:
        """Retrieve API key from environment."""
        return os.getenv(env_var)

    def complete(
        self,
        messages: List[Dict[str, str]],
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[str] = None,
        temperature: float = 0.3,
        max_tokens: Optional[int] = None,
        stream: bool = False,
    ) -> Dict[str, Any]:
        """
        Attempt to complete a chat message using the fallback chain.

        Tries each provider in order until one succeeds.
        Returns the raw litellm response dict.
        """
        last_error = None

        for provider_config in self.fallback_chain:
            provider = provider_config["provider"]
            model = provider_config["model"]
            api_key_env = provider_config["api_key_env"]
            api_key = self._get_api_key(api_key_env)

            if not api_key:
                logger.warning(f"Skipping {provider}: {api_key_env} not set")
                continue

            try:
                logger.info(f"Attempting LLM call via {provider} ({model})")

                # Build model string for litellm (e.g., "gemini/gemini-2.0-flash-exp")
                model_string = f"{provider}/{model}"

                kwargs = {
                    "model": model_string,
                    "messages": messages,
                    "temperature": temperature,
                    "stream": stream,
                }

                if api_key:
                    kwargs["api_key"] = api_key

                if tools:
                    kwargs["tools"] = tools
                    if tool_choice:
                        kwargs["tool_choice"] = tool_choice

                if max_tokens:
                    kwargs["max_tokens"] = max_tokens

                response = litellm.completion(**kwargs)
                logger.info(f"LLM call succeeded via {provider}")
                return response

            except Exception as e:
                logger.warning(f"Provider {provider} failed: {e}")
                last_error = e
                continue

        # All providers failed
        error_msg = f"All LLM providers failed. Last error: {last_error}"
        logger.error(error_msg)
        raise RuntimeError(error_msg)


def get_llm_response(
    messages: List[Dict[str, str]],
    tools: Optional[List[Dict[str, Any]]] = None,
    tool_choice: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Convenience function to get an LLM response using the default client.
    """
    client = LiteLLMClient()
    return client.complete(messages=messages, tools=tools, tool_choice=tool_choice)