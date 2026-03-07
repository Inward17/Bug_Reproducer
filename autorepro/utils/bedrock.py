"""Bedrock chat helpers with provider-specific fallbacks."""

import json
import re
from dataclasses import dataclass

from utils.logger import get_logger

log = get_logger(__name__)


def _make_converse_model(model: str, temperature: float):
    from langchain_aws import ChatBedrockConverse
    return ChatBedrockConverse(model=model, temperature=temperature)


def _make_legacy_model(model: str, temperature: float):
    from langchain_aws import ChatBedrock
    return ChatBedrock(model_id=model, model_kwargs={"temperature": temperature})


def _should_fallback_to_legacy(error: Exception) -> bool:
    text = str(error).lower()
    return (
        "unexpected content block type in content" in text
        or "reasoningcontent" in text
        or "sdk_unknown_member" in text
    )


def _strip_openai_reasoning(text: str) -> str:
    """Remove Bedrock OpenAI reasoning blocks from InvokeModel responses."""
    return re.sub(r"^\s*<reasoning>.*?</reasoning>\s*", "", text, flags=re.DOTALL)


def _extract_openai_text(response_body: dict) -> str:
    choices = response_body.get("choices") or []
    if not choices:
        raise RuntimeError("Bedrock OpenAI response did not contain any choices")

    message = choices[0].get("message") or {}
    content = message.get("content", "")

    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                if item.get("type") == "text":
                    parts.append(item.get("text", ""))
                elif "text" in item:
                    parts.append(str(item["text"]))
        content = "".join(parts)

    return _strip_openai_reasoning(str(content).strip())


@dataclass
class _InvokeResponse:
    content: str


class OpenAIBedrockInvokeLLM:
    """Direct InvokeModel adapter for OpenAI Bedrock models."""

    def __init__(self, model: str, temperature: float):
        import boto3

        self._client = boto3.client("bedrock-runtime")
        self._model = model
        self._temperature = temperature

    def invoke(self, prompt: str):
        request_body = {
            "model": self._model,
            "messages": [
                {
                    "role": "user",
                    "content": str(prompt),
                }
            ],
            "max_completion_tokens": 4096,
            "temperature": self._temperature,
            "stream": False,
        }
        response = self._client.invoke_model(
            modelId=self._model,
            body=json.dumps(request_body),
        )
        response_body = json.loads(response["body"].read().decode("utf-8"))
        return _InvokeResponse(content=_extract_openai_text(response_body))


class BedrockLLM:
    """Use Converse by default, but fall back to legacy Bedrock chat when needed."""

    def __init__(self, model: str, temperature: float):
        self._model = model
        self._temperature = temperature
        self._converse = _make_converse_model(model, temperature)
        self._legacy = _make_legacy_model(model, temperature)
        self._use_legacy = False

    def invoke(self, *args, **kwargs):
        if self._use_legacy:
            return self._legacy.invoke(*args, **kwargs)

        try:
            return self._converse.invoke(*args, **kwargs)
        except Exception as error:
            if not _should_fallback_to_legacy(error):
                raise

            self._use_legacy = True
            log.warning(
                "bedrock_converse_fallback",
                model=self._model,
                temperature=self._temperature,
                error=str(error),
            )
            return self._legacy.invoke(*args, **kwargs)


def make_bedrock_llm(model: str, temperature: float):
    if model.startswith("openai."):
        return OpenAIBedrockInvokeLLM(model, temperature)
    return BedrockLLM(model, temperature)
