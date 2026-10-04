"""Anthropic provider over the official SDK, using structured outputs.

Spec amendment 2 (plan-header.md): current Anthropic models reject a forced
tool_choice and a non-default temperature with HTTP 400. This provider relies
on output_config's json_schema format for determinism instead, and never
passes temperature, tool_choice, or thinking. output_config also sets
effort "low": coaching is a short structured summary, and adaptive thinking
at a higher effort only adds latency. max_tokens has a floor of
MIN_MAX_TOKENS because thinking tokens count against it.

Two clients: generation uses max_retries=0 (a retried slow call would
double the job's wait; coaching degrades to a warning instead), while
list_models keeps the SDK's default retries with a short timeout.
"""
from __future__ import annotations

import json

import anthropic

from vocal_coach.llm.base import LLMError, LLMProvider
from vocal_coach.llm.registry import register

DEFAULT_MODEL = "claude-opus-5-5"
MIN_MAX_TOKENS = 16000
LIST_MODELS_TIMEOUT_S = 10.0


@register("anthropic")
class AnthropicProvider(LLMProvider):
    name = "anthropic"

    def __init__(self, cfg, settings) -> None:
        super().__init__(cfg, settings)
        if not settings.anthropic_api_key:
            raise LLMError("ANTHROPIC_API_KEY is not set")
        self._client = anthropic.Anthropic(
            api_key=settings.anthropic_api_key, timeout=cfg.timeout_s, max_retries=0
        )
        self._models_client = anthropic.Anthropic(
            api_key=settings.anthropic_api_key, timeout=LIST_MODELS_TIMEOUT_S
        )

    def generate_coaching(
        self, system_prompt: str, user_payload: dict, schema: dict, *, model: str
    ) -> dict:
        try:
            response = self._client.messages.create(
                model=model or DEFAULT_MODEL,
                max_tokens=max(self.cfg.max_output_tokens, MIN_MAX_TOKENS),
                system=system_prompt,
                messages=[{"role": "user", "content": json.dumps(user_payload, sort_keys=True)}],
                output_config={
                    "effort": "low",
                    "format": {"type": "json_schema", "schema": schema},
                },
            )
        except anthropic.APIStatusError as e:
            raise LLMError(f"anthropic error {e.status_code}") from e
        except anthropic.APIConnectionError as e:  # includes APITimeoutError
            raise LLMError(f"anthropic connection error: {type(e).__name__}") from e
        except anthropic.APIError as e:  # catch-all for any other SDK failure mode
            raise LLMError(f"anthropic error: {type(e).__name__}") from e

        if response.stop_reason == "refusal":
            raise LLMError("anthropic declined the request")
        if response.stop_reason == "max_tokens":
            raise LLMError("anthropic response truncated")

        text = next((b.text for b in response.content if b.type == "text"), None)
        if text is None:
            raise LLMError("model returned no text")
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as e:
            raise LLMError("model returned non-JSON content") from e
        if not isinstance(parsed, dict):
            raise LLMError("model returned non-JSON content")
        return parsed

    def list_models(self) -> list[str]:
        try:
            return sorted(m.id for m in self._models_client.models.list())
        except anthropic.APIStatusError as e:
            raise LLMError(f"anthropic error {e.status_code}") from e
        except anthropic.APIConnectionError as e:  # includes APITimeoutError
            raise LLMError(f"anthropic connection error: {type(e).__name__}") from e
        except Exception as e:
            raise LLMError("anthropic models listing failed") from e
