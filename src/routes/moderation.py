"""Routes for moderation events and product approval."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.base import get_db
from src.models.product import Product, ProductStatus
from src.models.sku import SKU
from src.schemas.moderation import (
    ModerationEventRequest,
    ModerationEventResponse,
    ProductApproveRequest,
    ProductApproveResponse,
    ErrorResponse,
)
from src.services.moderation import (
    ModerationService,
    ModeratorApproveService,
    ProductNotFoundError,
    ProductWrongStatusError,
    ProductNoSKUError,
    ProductAlreadyModeratedError,
    ModerationEventError,
)
from src.settings import settings

router = APIRouter()


def _check_service_token(request: Request) -> None:
    """
    Validate inter-service authorization header.
    Expects: X-Service-Token: <service_token>
    Returns 401 if missing or invalid.
    """
    token = request.headers.get("X-Service-Token")
    if not token or token != settings.service_token:
        raise HTTPException(
            status_code=401,
            detail={
                "code": "UNAUTHORIZED_SERVICE",
                "message": "Missing or invalid service token",
            },
        )


def _get_moderation_service() -> ModerationService:
    return ModerationService()


def _get_approve_service() -> ModeratorApproveService:
    return ModeratorApproveService()


# ──────────────────────── /moderation/events ────────────────────────

@router.post(
    "/moderation/events",
    response_model=ModerationEventResponse,
    status_code=200,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid event payload"},
        401: {"model": ErrorResponse, "description": "Unauthorized — missing service token"},
        409: {"model": ErrorResponse, "description": "Duplicate event or wrong status"},
    },
)
async def receive_moderation_event(
    event: ModerationEventRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> ModerationEventResponse:
    """
    Receive moderation events from Moderation Service.
    Implements B2B OpenAPI: POST /api/v1/moderation/events

    Events accepted:
    - MODERATED → product transitions ON_MODERATION → MODERATED
    - BLOCKED → product transitions ON_MODERATION → BLOCKED/HARD_BLOCKED

    Idempotent by idempotency_key (TTL 24h).
    Requires X-Service-Token header for inter-service auth.
    """
    # Inter-service auth
    _check_service_token(request)

    service = _get_moderation_service()

    try:
        if event.event_type == "MODERATED":
            product = await service.process_moderated_event(
                db=db,
                product_id=event.product_id,
                idempotency_key=event.idempotency_key,
                moderator_id=event.moderator_id,
                moderator_comment=event.moderator_comment,
            )
            # Push to B2C catalog so product becomes visible
            await service.push_to_b2c_catalog(
                product_id=event.product_id,
                idempotency_key=event.idempotency_key,
            )
            return ModerationEventResponse(
                product_id=event.product_id,
                event_type=event.event_type,
                status="accepted",
            )

        elif event.event_type == "BLOCKED":
            product = await service.process_blocked_event(
                db=db,
                product_id=event.product_id,
                idempotency_key=event.idempotency_key,
                hard_block=event.hard_block,
                blocking_reason=event.blocking_reason,
                moderator_comment=event.moderator_comment,
                field_reports=event.field_reports,
            )
            return ModerationEventResponse(
                product_id=event.product_id,
                event_type=event.event_type,
                status="accepted",
            )

        else:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "UNKNOWN_EVENT_TYPE",
                    "message": f"Unknown event type: {event.event_type}",
                },
            )

    except (ProductNotFoundError, ProductWrongStatusError, ProductNoSKUError) as e:
        raise HTTPException(status_code=e.status_code, detail={"code": e.code, "message": e.message})
    except ProductAlreadyModeratedError as e:
        # Already moderated — idempotent success
        return ModerationEventResponse(
            product_id=event.product_id,
            event_type=event.event_type,
            status="accepted",
        )
    except ModerationEventError as e:
        raise HTTPException(status_code=e.status_code, detail={"code": e.code, "message": e.message})


# ──────────────────────── /products/{product_id}/approve ────────────────────────

@router.post(
    "/products/{product_id}/approve",
    response_model=ProductApproveResponse,
    status_code=200,
    responses={
        403: {"model": ErrorResponse, "description": "Forbidden — not your product"},
        409: {"model": ErrorResponse, "description": "Conflict — wrong status or no SKU"},
        404: {"model": ErrorResponse, "description": "Product not found"},
    },
)
async def approve_product(
    product_id: int,
    body: ProductApproveRequest = ProductApproveRequest(),
    seller_id: int = 0,  # from auth context in real system
    db: AsyncSession = Depends(get_db),
) -> ProductApproveResponse:
    """
    Approve a product: ON_MODERATION → MODERATED.

    Validates:
    - Product belongs to the seller (IDOR prevention).
    - Product is in ON_MODERATION status.
    - Product has at least one active SKU.

    After approval:
    - Product status becomes MODERATED.
    - MODERATED event is pushed to B2C catalog.
    """
    service = _get_approve_service()

    try:
        product = await service.approve_product(
            db=db,
            product_id=product_id,
            moderator_id=0,  # not used in B2B approve
            seller_id=seller_id,
            comment=body.comment,
        )
        await service.push_to_b2c_catalog(product_id)

        return ProductApproveResponse(
            product_id=product.id,
            status=product.status.value,
            seller_id=product.seller_id,
            approved_at=datetime.now(timezone.utc),
            comment=body.comment,
        )

    except ProductNotFoundError as e:
        raise HTTPException(status_code=e.status_code, detail={"code": e.code, "message": e.message})
    except ModerationEventError as e:
        if e.status_code == 403:
            raise HTTPException(status_code=403, detail={"code": e.code, "message": e.message})
        raise HTTPException(status_code=e.status_code, detail={"code": e.code, "message": e.message})