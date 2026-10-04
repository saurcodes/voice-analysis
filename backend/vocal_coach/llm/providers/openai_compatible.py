"""OpenAI-compatible chat-completions provider, over httpx (not the openai SDK).

Talks to any server exposing the OpenAI chat-completions wire format
(vLLM, Ollama's OpenAI-compat endpoint, LM Studio, etc.). Tries strict
structured output (response_format: json_schema) first; on a 4xx from
that attempt, retries once with response_format: json_object and the
schema appended to the system prompt as plain text.
"""
from __future__ import annotations

import json

import httpx

from vocal_coach.llm.base import LLMError, LLMProvider
from vocal_coach.llm.registry import register


@register("openai_compatible")
class OpenAICompatibleProvider(LLMProvider):
    name = "openai_compatible"

    def generate_coaching(
        self, system_prompt: str, user_payload: dict, schema: dict, *, model: str
    ) -> dict:
        with httpx.Client(timeout=self.cfg.timeout_s) as client:
            try:
                data = self._post_once(
                    client, system_prompt, user_payload, schema, model, json_schema_mode=True
                )
            except httpx.HTTPStatusError as e:
                status = e.response.status_code
                if not (400 <= status < 500):
                    raise LLMError(f"openai-compatible error {status}") from None
                fallback_prompt = (
                    system_prompt
                    + "\n\nThe JSON must match this schema exactly:\n"
                    + json.dumps(schema)
                )
                try:
                    data = self._post_once(
                        client,
                        fallback_prompt,
                        user_payload,
                        schema,
                        model,
                        json_schema_mode=False,
                    )
                except httpx.HTTPStatusError as e2:
                    raise LLMError(f"openai-compatible error {e2.response.status_code}") from None
        return self._parse_content(data)

    def list_models(self) -> list[str]:
        try:
            with httpx.Client(timeout=self.cfg.timeout_s) as client:
                response = client.get(self._url("models"), headers=self._headers())
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPStatusError as e:
            raise LLMError(f"openai-compatible error {e.response.status_code}") from None
        except (httpx.TimeoutException, httpx.TransportError) as e:
            raise LLMError(f"openai-compatible connection error: {type(e).__name__}") from None
        try:
            return sorted(m["id"] for m in data["data"])
        except (KeyError, TypeError):
            raise LLMError("openai-compatible error: unexpected models response shape") from None

    # -- internals ---------------------------------------------------------

    def _url(self, path: str) -> str:
        return f"{self.cfg.base_url.rstrip('/')}/{path}"

    def _headers(self) -> dict:
        if self.settings.openai_compat_api_key:
            return {"Authorization": f"Bearer {self.settings.openai_compat_api_key}"}
        return {}

    def _post_once(
        self,
        client: httpx.Client,
        system_prompt: str,
        user_payload: dict,
        schema: dict,
        model: str,
        *,
        json_schema_mode: bool,
    ) -> dict:
        if json_schema_mode:
            response_format = {
                "type": "json_schema",
                "json_schema": {"name": "coaching_output", "strict": True, "schema": schema},
            }
        else:
            response_format = {"type": "json_object"}
        body = {
            "model": model,
            "temperature": 0,
            "seed": self.cfg.seed,
            "max_tokens": self.cfg.max_output_tokens,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(user_payload, sort_keys=True)},
            ],
            "response_format": response_format,
        }
        try:
            response = client.post(self._url("chat/completions"), json=body, headers=self._headers())
            response.raise_for_status()
        except (httpx.TimeoutException, httpx.TransportError) as e:
            raise LLMError(f"openai-compatible connection error: {type(e).__name__}") from None
        return response.json()

    def _parse_content(self, data: dict) -> dict:
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise LLMError("model returned non-JSON content") from None
        if not isinstance(content, str):
            raise LLMError("model returned non-JSON content")
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            raise LLMError("model returned non-JSON content") from None
        if not isinstance(parsed, dict):
            raise LLMError("model returned non-JSON content")
        return parsed
