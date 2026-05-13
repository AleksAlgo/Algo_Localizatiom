"""Унифицированный LLM-клиент: Anthropic, OpenAI, Google, DeepSeek, OpenRouter."""
from __future__ import annotations
import json
import os
from abc import ABC, abstractmethod


class LLMClient(ABC):
    provider_name: str = ""
    env_key: str = ""

    def __init__(self):
        self.api_key = os.environ.get(self.env_key)
        self._client = None
        if self.api_key:
            try:
                self._client = self._init_client()
            except Exception as e:
                print(f"[{self.provider_name}] init failed: {e}")
                self._client = None

    def is_available(self) -> bool:
        return self._client is not None

    @abstractmethod
    def _init_client(self): ...

    @abstractmethod
    def chat(self, system: str, user: str, model: str, max_tokens: int = 4096, json_mode: bool = False) -> str: ...


class AnthropicClient(LLMClient):
    provider_name = "anthropic"
    env_key = "ANTHROPIC_API_KEY"

    def _init_client(self):
        from anthropic import Anthropic
        return Anthropic(api_key=self.api_key)

    def chat(self, system, user, model, max_tokens=4096, json_mode=False):
        msg = self._client.messages.create(
            model=model, max_tokens=max_tokens, system=system,
            messages=[{"role": "user", "content": user}],
        )
        return msg.content[0].text


class OpenAIClient(LLMClient):
    provider_name = "openai"
    env_key = "OPENAI_API_KEY"

    def _init_client(self):
        from openai import OpenAI
        return OpenAI(api_key=self.api_key)

    def chat(self, system, user, model, max_tokens=4096, json_mode=False):
        kwargs = {"model": model, "max_tokens": max_tokens,
                  "messages": [{"role": "system", "content": system},
                               {"role": "user", "content": user}]}
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        resp = self._client.chat.completions.create(**kwargs)
        return resp.choices[0].message.content


class DeepSeekClient(LLMClient):
    provider_name = "deepseek"
    env_key = "DEEPSEEK_API_KEY"

    def _init_client(self):
        from openai import OpenAI
        return OpenAI(api_key=self.api_key, base_url="https://api.deepseek.com/v1")

    def chat(self, system, user, model, max_tokens=4096, json_mode=False):
        kwargs = {"model": model, "max_tokens": max_tokens,
                  "messages": [{"role": "system", "content": system},
                               {"role": "user", "content": user}]}
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        resp = self._client.chat.completions.create(**kwargs)
        return resp.choices[0].message.content


class GoogleClient(LLMClient):
    provider_name = "google"
    env_key = "GOOGLE_API_KEY"

    def _init_client(self):
        import google.generativeai as genai
        genai.configure(api_key=self.api_key)
        return genai

    def chat(self, system, user, model, max_tokens=4096, json_mode=False):
        gen_config = {"max_output_tokens": max_tokens}
        if json_mode:
            gen_config["response_mime_type"] = "application/json"
        m = self._client.GenerativeModel(model_name=model, system_instruction=system, generation_config=gen_config)
        return m.generate_content(user).text


class OpenRouterClient(LLMClient):
    """OpenRouter — единый OpenAI-совместимый шлюз ко всем провайдерам."""
    provider_name = "openrouter"
    env_key = "OPENROUTER_API_KEY"

    def _init_client(self):
        from openai import OpenAI
        return OpenAI(
            api_key=self.api_key,
            base_url="https://openrouter.ai/api/v1",
            default_headers={
                "HTTP-Referer": os.environ.get("OPENROUTER_REFERER", "https://anthropic.com/cowork"),
                "X-Title":      os.environ.get("OPENROUTER_TITLE",   "Translation QA Agent"),
            },
        )

    def chat(self, system, user, model, max_tokens=4096, json_mode=False):
        kwargs = {"model": model, "max_tokens": max_tokens,
                  "messages": [{"role": "system", "content": system},
                               {"role": "user", "content": user}]}
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        resp = self._client.chat.completions.create(**kwargs)
        return resp.choices[0].message.content


_REGISTRY: dict[str, LLMClient] = {}
_PROVIDER_CLASSES = {
    "anthropic":  AnthropicClient,
    "openai":     OpenAIClient,
    "google":     GoogleClient,
    "deepseek":   DeepSeekClient,
    "openrouter": OpenRouterClient,
}


def get_client(provider: str) -> LLMClient:
    if provider not in _REGISTRY:
        cls = _PROVIDER_CLASSES.get(provider)
        if cls is None:
            raise ValueError(f"Unknown provider: {provider}")
        _REGISTRY[provider] = cls()
    return _REGISTRY[provider]


def available_providers() -> list[str]:
    return [name for name in _PROVIDER_CLASSES if get_client(name).is_available()]


def call_llm(provider: str, model_id: str, system: str, user: str,
             max_tokens: int = 4096, json_mode: bool = False) -> str:
    client = get_client(provider)
    if not client.is_available():
        raise RuntimeError(f"Provider {provider} unavailable (no API key)")
    return client.chat(system=system, user=user, model=model_id,
                       max_tokens=max_tokens, json_mode=json_mode)


def parse_json_response(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])
    return json.loads(text)
