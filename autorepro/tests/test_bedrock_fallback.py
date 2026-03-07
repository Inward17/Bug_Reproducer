"""Tests for Bedrock Converse fallback behavior."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from utils.bedrock import make_bedrock_llm


def test_reasoning_content_error_falls_back_to_legacy_bedrock():
    converse = MagicMock()
    converse.invoke.side_effect = ValueError(
        "Unexpected content block type in content. "
        "Received: {'sdk_unknown_member': {'name': 'reasoningContent'}}"
    )
    legacy = MagicMock()
    legacy.invoke.side_effect = ["first-response", "second-response"]

    with patch("utils.bedrock._make_converse_model", return_value=converse), \
         patch("utils.bedrock._make_legacy_model", return_value=legacy):
        llm = make_bedrock_llm("anthropic.test-model", 0.2)

        assert llm.invoke("first") == "first-response"
        assert llm.invoke("second") == "second-response"
        assert converse.invoke.call_count == 1
        assert legacy.invoke.call_count == 2


def test_non_reasoning_errors_still_raise():
    converse = MagicMock()
    converse.invoke.side_effect = RuntimeError("AWS credentials are invalid")
    legacy = MagicMock()

    with patch("utils.bedrock._make_converse_model", return_value=converse), \
         patch("utils.bedrock._make_legacy_model", return_value=legacy):
        llm = make_bedrock_llm("anthropic.test-model", 0)

        try:
            llm.invoke("hello")
        except RuntimeError as error:
            assert "credentials" in str(error).lower()
        else:
            raise AssertionError("Expected RuntimeError to be re-raised")

        legacy.invoke.assert_not_called()
