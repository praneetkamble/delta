"""Tiny OpenAI-compatible chat client (works with Ollama, OpenAI, Groq, LM Studio, vLLM...). Uses httpx only."""
from __future__ import annotations

import httpx


class LLMError(RuntimeError):
    pass


class LLMClient:
    def __init__(self, base_url: str, model: str, api_key: str = "", timeout: float = 60,
                 temperature: float = 0.2, transport: httpx.BaseTransport | None = None):
        self.base_url = (base_url or "").rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout = timeout
        self.temperature = temperature
        self.transport = transport

    @property
    def available(self) -> bool:
        return bool(self.base_url and self.model)

    def chat(self, messages: list[dict], tools: list[dict] | None = None) -> dict:
        """POST /chat/completions -> the assistant message dict (may contain tool_calls)."""
        if not self.available:
            raise LLMError("no LLM configured")
        body: dict = {"model": self.model, "messages": messages, "temperature": self.temperature}
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        try:
            with httpx.Client(timeout=self.timeout, transport=self.transport) as c:
                r = c.post(f"{self.base_url}/chat/completions", json=body, headers=headers)
        except httpx.HTTPError as e:
            raise LLMError(f"could not reach the LLM at {self.base_url}: {e}") from e
        if r.status_code >= 400:
            raise LLMError(f"LLM returned HTTP {r.status_code}: {r.text[:200]}")
        try:
            return r.json()["choices"][0]["message"]
        except (KeyError, IndexError, ValueError) as e:
            raise LLMError("unexpected LLM response format") from e

    def complete_text(self, system: str, user: str) -> str:
        """Plain completion with NO tools (used to summarise untrusted text safely)."""
        msg = self.chat([{"role": "system", "content": system}, {"role": "user", "content": user}])
        return msg.get("content") or ""
