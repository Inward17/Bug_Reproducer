"""Tests for the LLM fallback chain in utils/llm.py.

Run with: python -m pytest tests/test_llm_fallback.py -v
"""

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# Ensure project root on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from utils.llm import get_llm, clear_cache


# ── Fixtures ──────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _clear_llm_cache():
    """Clear the LLM cache before and after each test."""
    clear_cache()
    yield
    clear_cache()


# ── Mock provider mode ───────────────────────────────────

def test_mock_provider_returns_mock_llm():
    """LLM_PROVIDER=mock should return MockLLM without any fallback."""
    with patch("utils.llm.config") as mock_config:
        mock_config.LLM_PROVIDER = "mock"
        llm = get_llm(temperature=0)
        from utils.mock_llm import MockLLM
        assert isinstance(llm, MockLLM)


# ── Single provider mode ─────────────────────────────────

def test_single_provider_ollama():
    """LLM_PROVIDER=ollama should use ollama directly without fallback."""
    with patch("utils.llm.config") as mock_config:
        mock_config.LLM_PROVIDER = "ollama"
        mock_config.OLLAMA_MODEL = "qwen2.5-coder:3b"
        mock_config.LLM_MODEL = "qwen2.5-coder:3b"

        mock_ollama = MagicMock()
        with patch("utils.llm._make_ollama", return_value=mock_ollama) as make:
            llm = get_llm(temperature=0.2)
            assert llm is mock_ollama
            make.assert_called_once_with("qwen2.5-coder:3b", 0.2)


def test_single_provider_anthropic():
    """LLM_PROVIDER=anthropic should use anthropic directly."""
    with patch("utils.llm.config") as mock_config:
        mock_config.LLM_PROVIDER = "anthropic"
        mock_config.ANTHROPIC_MODEL = "claude-sonnet-4-20250514"
        mock_config.LLM_MODEL = "claude-sonnet-4-20250514"

        mock_anthropic = MagicMock()
        with patch("utils.llm._make_anthropic", return_value=mock_anthropic) as make:
            llm = get_llm(temperature=0)
            assert llm is mock_anthropic
            make.assert_called_once_with("claude-sonnet-4-20250514", 0)


# ── Caching ──────────────────────────────────────────────

def test_caching_returns_same_instance():
    """Repeated calls with same temperature should return cached instance."""
    with patch("utils.llm.config") as mock_config:
        mock_config.LLM_PROVIDER = "ollama"
        mock_config.OLLAMA_MODEL = "qwen2.5-coder:3b"
        mock_config.LLM_MODEL = "qwen2.5-coder:3b"

        mock_ollama = MagicMock()
        with patch("utils.llm._make_ollama", return_value=mock_ollama) as make:
            llm1 = get_llm(temperature=0)
            llm2 = get_llm(temperature=0)
            assert llm1 is llm2
            # Factory should only be called once
            assert make.call_count == 1


def test_different_temperatures_get_different_instances():
    """Different temperatures should not share cache entries."""
    with patch("utils.llm.config") as mock_config:
        mock_config.LLM_PROVIDER = "ollama"
        mock_config.OLLAMA_MODEL = "qwen2.5-coder:3b"
        mock_config.LLM_MODEL = "qwen2.5-coder:3b"

        mock1, mock2 = MagicMock(), MagicMock()
        with patch("utils.llm._make_ollama", side_effect=[mock1, mock2]):
            llm_a = get_llm(temperature=0)
            llm_b = get_llm(temperature=0.3)
            assert llm_a is not llm_b


# ── Auto fallback mode ───────────────────────────────────

def test_auto_falls_back_to_ollama_when_anthropic_and_google_fail():
    """Auto mode: Anthropic fails → Google fails → Ollama succeeds."""
    with patch("utils.llm.config") as mock_config:
        mock_config.LLM_PROVIDER = "auto"
        mock_config.ANTHROPIC_MODEL = "claude-sonnet-4-20250514"
        mock_config.GOOGLE_MODEL = "gemini-2.0-flash"
        mock_config.OLLAMA_MODEL = "qwen2.5-coder:3b"

        mock_ollama = MagicMock()
        mock_probe_response = MagicMock()
        mock_probe_response.content = "OK"
        mock_ollama.invoke.return_value = mock_probe_response

        with patch("utils.llm._make_anthropic", side_effect=Exception("No API key")), \
             patch("utils.llm._make_google", side_effect=Exception("No API key")), \
             patch("utils.llm._make_ollama", return_value=mock_ollama):
            llm = get_llm(temperature=0)
            assert llm is mock_ollama


def test_auto_uses_anthropic_first_when_available():
    """Auto mode: Anthropic available → use it (don't try others)."""
    with patch("utils.llm.config") as mock_config:
        mock_config.LLM_PROVIDER = "auto"
        mock_config.ANTHROPIC_MODEL = "claude-sonnet-4-20250514"
        mock_config.GOOGLE_MODEL = "gemini-2.0-flash"
        mock_config.OLLAMA_MODEL = "qwen2.5-coder:3b"

        mock_anthropic = MagicMock()
        mock_probe_response = MagicMock()
        mock_probe_response.content = "OK"
        mock_anthropic.invoke.return_value = mock_probe_response

        with patch("utils.llm._make_anthropic", return_value=mock_anthropic) as make_a, \
             patch("utils.llm._make_google") as make_g, \
             patch("utils.llm._make_ollama") as make_o:
            llm = get_llm(temperature=0)
            assert llm is mock_anthropic
            make_a.assert_called_once()
            make_g.assert_not_called()
            make_o.assert_not_called()


def test_auto_uses_google_when_anthropic_fails():
    """Auto mode: Anthropic fails → Google succeeds → use Google."""
    with patch("utils.llm.config") as mock_config:
        mock_config.LLM_PROVIDER = "auto"
        mock_config.ANTHROPIC_MODEL = "claude-sonnet-4-20250514"
        mock_config.GOOGLE_MODEL = "gemini-2.0-flash"
        mock_config.OLLAMA_MODEL = "qwen2.5-coder:3b"

        mock_google = MagicMock()
        mock_probe_response = MagicMock()
        mock_probe_response.content = "OK"
        mock_google.invoke.return_value = mock_probe_response

        with patch("utils.llm._make_anthropic", side_effect=Exception("No key")), \
             patch("utils.llm._make_google", return_value=mock_google), \
             patch("utils.llm._make_ollama") as make_o:
            llm = get_llm(temperature=0)
            assert llm is mock_google
            make_o.assert_not_called()


def test_auto_all_fail_raises_error():
    """Auto mode: all providers fail → raise RuntimeError."""
    with patch("utils.llm.config") as mock_config:
        mock_config.LLM_PROVIDER = "auto"
        mock_config.ANTHROPIC_MODEL = "claude-sonnet-4-20250514"
        mock_config.GOOGLE_MODEL = "gemini-2.0-flash"
        mock_config.OLLAMA_MODEL = "qwen2.5-coder:3b"

        with patch("utils.llm._make_anthropic", side_effect=Exception("fail")), \
             patch("utils.llm._make_google", side_effect=Exception("fail")), \
             patch("utils.llm._make_ollama", side_effect=Exception("fail")):
            with pytest.raises(RuntimeError, match="All LLM providers failed"):
                get_llm(temperature=0)


# ── Unknown provider ─────────────────────────────────────

def test_unknown_provider_raises_error():
    """Unknown LLM_PROVIDER should raise ValueError."""
    with patch("utils.llm.config") as mock_config:
        mock_config.LLM_PROVIDER = "unknown_provider"
        with pytest.raises(ValueError, match="Unknown LLM provider"):
            get_llm(temperature=0)
