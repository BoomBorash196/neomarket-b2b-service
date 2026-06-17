"""Pydantic schemas for moderation events."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class ModerationEventRequest(BaseModel):
    """
    Schema for receiving moderation events from Moderation Service.
    Matches B2B OpenAPI: ModerationEventRequest.
    """
    idempotency_key: str = Field(..., description="Idempotency key, TTL 24h")
    product_id: int
    event_type: str = Field(..., description="MODERATED or BLOCKED")
    moderator_id: Optional[str] = None
    moderator_comment: Optional[str] = None
    blocking_reason_id: Optional[str] = None
    hard_block: bool = False
    field_reports: Optional[list] = None
    occurred_at: Optional[datetime] = None


class ModerationEventResponse(BaseModel):
    """Response for accepted moderation event."""
    product_id: int
    event_type: str
    status: str = "accepted"


class ProductApproveRequest(BaseModel):
    """
    Request body for product approval endpoint.
    Matches Moderation OpenAPI approve endpoint optional comment.
    """
    comment: Optional[str] = Field(None, max_length=2000)


class ProductApproveResponse(BaseModel):
    """Response for approved product."""
    product_id: int
    status: str
    seller_id: int
    approved_at: datetime
    approved_by: Optional[str] = None
    comment: Optional[str] = None


class ErrorResponse(BaseModel):
    """Standard error response."""
    code: str
    message: str
    details: Optional[dict] = None
