"""AgentState TypedDict and FailureType enum — single source of truth for agent data."""

from typing import TypedDict
from enum import Enum


class FailureType(str, Enum):
    """Classification of script execution failures."""
    ELEMENT_NOT_FOUND = "ElementNotFound"
    TIMEOUT           = "Timeout"
    ASSERTION_ERROR   = "AssertionError"
    NETWORK_ERROR     = "NetworkError"
    UNKNOWN           = "Unknown"


class AgentState(TypedDict):
    """State passed between LangGraph nodes."""
    job_id:           str
    bug_report:       str
    target_url:       str
    attempt_count:    int
    max_attempts:     int
    analysis:         dict
    script:           str
    execution_result: dict
    success:          bool
    history:          list
