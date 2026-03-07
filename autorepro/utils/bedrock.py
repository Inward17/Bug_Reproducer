"""Bedrock chat helpers with fallback for Converse parsing issues."""

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
    return BedrockLLM(model, temperature)
