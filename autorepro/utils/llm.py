"""Centralized LLM provider with automatic fallback chain.

Fallback order: Anthropic → Google Gemini → Ollama (local).
Set LLM_PROVIDER to a specific provider name to skip fallback,
or set it to 'auto' to enable the full chain.
"""

from utils import config
from utils.logger import get_logger

log = get_logger(__name__)

# Cache: (provider_name, temperature) → LLM instance
_llm_cache: dict[tuple[str, float], object] = {}

# Fallback chain definition: (provider_name, model_config_attr, factory)
_PROVIDERS = [
    ("bedrock",   "BEDROCK_MODEL",   "_make_bedrock"),
    ("anthropic", "ANTHROPIC_MODEL", "_make_anthropic"),
    ("google",    "GOOGLE_MODEL",    "_make_google"),
    ("ollama",    "OLLAMA_MODEL",    "_make_ollama"),
]


def _make_bedrock(model: str, temperature: float):
    from langchain_aws import ChatBedrockConverse
    return ChatBedrockConverse(model=model, temperature=temperature)


def _make_anthropic(model: str, temperature: float):
    from langchain_anthropic import ChatAnthropic
    return ChatAnthropic(model=model, temperature=temperature)


def _make_google(model: str, temperature: float):
    from langchain_google_genai import ChatGoogleGenerativeAI
    return ChatGoogleGenerativeAI(model=model, temperature=temperature)


def _make_ollama(model: str, temperature: float):
    from langchain_ollama import ChatOllama
    return ChatOllama(model=model, temperature=temperature)


def _make_openai(model: str, temperature: float):
    from langchain_openai import ChatOpenAI
    return ChatOpenAI(model=model, temperature=temperature)


def _probe(llm) -> bool:
    """Quick probe to verify the LLM can respond."""
    try:
        response = llm.invoke("Reply with OK")
        return bool(response and response.content)
    except Exception as e:
        log.debug("llm_probe_failed", error=str(e))
        return False


def _get_model_for_provider(provider: str) -> str:
    """Return the configured model name for a provider."""
    mapping = {
        "bedrock":   config.BEDROCK_MODEL,
        "anthropic": config.ANTHROPIC_MODEL,
        "google":    config.GOOGLE_MODEL,
        "ollama":    config.OLLAMA_MODEL,
        "openai":    config.LLM_MODEL,
    }
    return mapping.get(provider, config.LLM_MODEL)


def _make_single(provider: str, temperature: float):
    """Create an LLM instance for a single specific provider (no fallback)."""
    if provider == "mock":
        from utils.mock_llm import MockLLM
        return MockLLM()

    factories = {
        "bedrock":   _make_bedrock,
        "anthropic": _make_anthropic,
        "google":    _make_google,
        "ollama":    _make_ollama,
        "openai":    _make_openai,
    }
    factory = factories.get(provider)
    if factory is None:
        raise ValueError(f"Unknown LLM provider: {provider}")

    model = _get_model_for_provider(provider)
    return factory(model, temperature)


def get_llm(temperature: float = 0):
    """Return an LLM instance, using fallback chain if LLM_PROVIDER is 'auto'.

    When LLM_PROVIDER is set to a specific provider ('ollama', 'anthropic', etc.),
    that provider is used directly with no fallback — preserving backwards compatibility.

    When LLM_PROVIDER is 'auto', tries: Anthropic → Google Gemini → Ollama.
    Each provider is probed with a tiny request; on failure, the next is tried.
    Successful instances are cached for the lifetime of the process.
    """
    provider = config.LLM_PROVIDER

    # ── Single-provider mode (backwards compatible) ──
    if provider != "auto":
        cache_key = (provider, temperature)
        if cache_key in _llm_cache:
            return _llm_cache[cache_key]
        llm = _make_single(provider, temperature)
        _llm_cache[cache_key] = llm
        log.info("llm_provider_selected", provider=provider, mode="single")
        return llm

    # ── Auto-fallback mode ──
    cache_key = ("auto", temperature)
    if cache_key in _llm_cache:
        return _llm_cache[cache_key]

    errors: list[str] = []

    for name, model_attr, factory_name in _PROVIDERS:
        model = getattr(config, model_attr)
        factory = globals()[factory_name]
        try:
            llm = factory(model, temperature)
            if _probe(llm):
                _llm_cache[cache_key] = llm
                log.info("llm_fallback_selected", provider=name, model=model, mode="auto")
                return llm
            else:
                errors.append(f"{name}: probe returned empty response")
        except Exception as e:
            msg = f"{name}: {type(e).__name__}: {e}"
            errors.append(msg)
            log.warning("llm_fallback_skip", provider=name, error=str(e))

    raise RuntimeError(
        f"All LLM providers failed. Tried: {', '.join(e for e in errors)}"
    )


def clear_cache():
    """Clear the LLM cache — useful for testing."""
    _llm_cache.clear()
