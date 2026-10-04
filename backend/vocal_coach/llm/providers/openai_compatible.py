"""OpenAI-compatible chat-completions provider, over httpx (not the openai SDK).

Talks to any server exposing the OpenAI chat-completions wire format
(vLLM, Ollama's OpenAI-compat endpoint, LM Studio and others). Tries strict
structured output (response_format: json_schema) first; when that attempt is
rejected with 400 or 422 (the server does not support json_schema), retries
once with response_format: json_object and the schema appended to the system
prompt as plain text. Any other status (401, 403, 404, 429, 5xx) raises
immediately.

Local models do not always honour the response format exactly, so content
parsing is lenient: a <think>...</think> block and a Markdown code fence are
stripped, and as a last resort the slice from the first "{" to the last "}"
is parsed.
"""
from __future__ import annotations

import json
import re

import httpx

from vocal_coach.llm.base import LLMError, LLMProvider
from vocal_coach.llm.registry import register

CONNECT_TIMEOUT_S = 10.0
LIST_MODELS_TIMEOUT_S = 10.0
FALLBACK_STATUSES = (400, 422)

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)
_LEADING_FENCE_RE = re.compile(r"\A\s*```(?:json)?[^\n]*\n")
_TRAILING_FENCE_RE = re.compile(r"\n?```\s*\Z")


def _chat_timeout(read_s: float) -> httpx.Timeout:
    return httpx.Timeout(CONNECT_TIMEOUT_S, read=read_s)


def _list_models_timeout() -> httpx.Timeout:
    return httpx.Timeout(LIST_MODELS_TIMEOUT_S)


def _clean_content(content: str) -> str:
    text = _THINK_RE.sub("", content).strip()
    text = _LEADING_FENCE_RE.sub("", text)
    text = _TRAILING_FENCE_RE.sub("", text)
    return text.strip()


def _load_object(text: str) -> dict | None:
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            return None
        try:
            parsed = json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            return None
    return parsed if isinstance(parsed, dict) else None


@register("openai_compatible")
class OpenAICompatibleProvider(LLMProvider):
    name = "openai_compatible"

    def generate_coaching(
        self, system_prompt: str, user_payload: dict, schema: dict, *, model: str
    ) -> dict:
        with httpx.Client(timeout=_chat_timeout(self.cfg.timeout_s)) as client:
            try:
                data = self._post_once(
                    client, system_prompt, user_payload, schema, model, json_schema_mode=True
                )
            except httpx.HTTPStatusError as e:
                status = e.response.status_code
                if status not in FALLBACK_STATUSES:
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
            with httpx.Client(timeout=_list_models_timeout()) as client:
                response = client.get(self._url("models"), headers=self._headers())
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPStatusError as e:
            raise LLMError(f"openai-compatible error {e.response.status_code}") from None
        except (httpx.TimeoutException, httpx.TransportError) as e:
            raise LLMError(f"openai-compatible connection error: {type(e).__name__}") from None
        except json.JSONDecodeError:
            raise LLMError("openai-compatible returned a malformed response") from None
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
        try:
            return response.json()
        except json.JSONDecodeError:
            raise LLMError("openai-compatible returned a malformed response") from None

    def _parse_content(self, data: dict) -> dict:
        try:
            choice = data["choices"][0]
            content = choice["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise LLMError("model returned non-JSON content") from None
        if isinstance(choice, dict) and choice.get("finish_reason") == "length":
            raise LLMError("model response truncated")
        if not isinstance(content, str):
            raise LLMError("model returned non-JSON content")
        parsed = _load_object(_clean_content(content))
        if parsed is None:
            raise LLMError("model returned non-JSON content")
        return parsed
