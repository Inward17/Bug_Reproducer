"""Pydantic request/response models for the AutoRepro API."""

from typing import Literal

from pydantic import BaseModel, Field, HttpUrl


class ReproduceRequest(BaseModel):
    """Request body for POST /reproduce."""
    bug_report: str = Field(..., min_length=20)
    target_url: HttpUrl


class JobCreatedResponse(BaseModel):
    """Response for accepted reproduction job."""
    job_id: str
    status: Literal["processing"]


class JobResultResponse(BaseModel):
    """Response for completed/failed reproduction job."""
    job_id:          str
    status:          str
    success:         bool | None      = None
    attempt_count:   int | None       = None
    final_script:    str | None       = None
    screenshot_urls: list[str] | None = None
    logs:            str | None       = None
    created_at:      str | None       = None
    completed_at:    str | None       = None
