"""UUID-based job ID generation and validation."""

import re
import uuid

# A job ID becomes a path segment under data/, so it must start with an alphanumeric
# (which rules out "." and "..") and contain no separator, drive letter or wildcard.
# Issued IDs are UUIDs; the wider pattern keeps hand-written IDs in tests and existing
# data readable.
_JOB_ID = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$')


class InvalidJobIdError(ValueError):
    """Raised when a job ID is not one this service could have issued."""


def new_job_id() -> str:
    """Generate a new unique job identifier."""
    return str(uuid.uuid4())


def is_job_id(value: str) -> bool:
    """True when ``value`` is safe to use as a single path segment."""
    return isinstance(value, str) and bool(_JOB_ID.match(value))


def require_job_id(value: str) -> str:
    """Return ``value`` if it is a valid job ID, else raise InvalidJobIdError."""
    if not is_job_id(value):
        raise InvalidJobIdError(f"Not a valid job id: {value!r}")
    return str(value)
