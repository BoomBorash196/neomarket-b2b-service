"""Tests for US-MOD-03: product approval by moderator."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.main import app
from src.models.product import ProductStatus
from tests.conftest import _mock_product, _mock_sku, _mock_db_session


def _override_get_db(product, skus=None):
    """Create a dependency override for get_db with specific product/skus."""
    session = _mock_db_session(product, skus)

    async def override():
        yield session

    return override


# ─────────────────────────────────────────────
# Test 1: approve_transitions_to_moderated_and_emits_event
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_approve_transitions_to_moderated_and_emits_event(client):
    """
    Happy path:
    - Product in ON_MODERATION belongs to seller_id=1
    - POST /api/v1/products/{id}/approve with seller_id=1
    - Product status → MODERATED
    - B2C catalog event is emitted (mocked)
    """
    product = _mock_product(
        product_id=100,
        status=ProductStatus.ON_MODERATION,
        seller_id=1,
        has_sku=True,
    )
    sku = _mock_sku()

    # Override with specific product for this test
    app.dependency_overrides["get_db"] = _override_get_db(product, [sku])

    with patch("src.services.moderation.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=MagicMock(status_code=200))
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_client)
        mock_ctx.__aexit__ = AsyncMock(return_value=None)
        mock_client_cls.return_value = mock_ctx

        response = client.post(
            "/api/v1/products/100/approve",
            json={"comment": "Approved by moderator"},
            params={"seller_id": 1},
        )

    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
    data = response.json()
    assert data["status"] == "MODERATED"
    assert data["product_id"] == 100
    assert data["seller_id"] == 1
    assert data["comment"] == "Approved by moderator"

    mock_client.post.assert_called_once()
    call_kwargs = mock_client.post.call_args[1]
    payload = call_kwargs.get("json", {})
    assert payload["event_type"] == "MODERATED"
    assert payload["product_id"] == 100


# ─────────────────────────────────────────────
# Test 2: approve_others_card_returns_403
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_approve_others_card_returns_403(client):
    """
    Unhappy path:
    - Product belongs to seller_id=2
    - Moderator tries to approve with seller_id=1 (different seller)
    - Should return 403 Forbidden
    """
    product = _mock_product(
        product_id=100,
        status=ProductStatus.ON_MODERATION,
        seller_id=2,
        has_sku=True,
    )
    sku = _mock_sku()

    app.dependency_overrides["get_db"] = _override_get_db(product, [sku])

    response = client.post(
        "/api/v1/products/100/approve",
        json={"comment": "Trying to approve someone else's product"},
        params={"seller_id": 1},
    )

    assert response.status_code == 403, f"Expected 403, got {response.status_code}: {response.text}"
    data = response.json()
    assert data["detail"]["code"] == "PRODUCT_NOT_YOURS"
    assert "own product" in data["detail"]["message"].lower()


# ─────────────────────────────────────────────
# Test 3: approve_after_edited_returns_409
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_approve_after_edited_returns_409(client):
    """
    Unhappy path:
    - Product status is CREATED (seller edited it back)
    - Moderator tries to approve
    - Should return 409 Conflict
    """
    product = _mock_product(
        product_id=100,
        status=ProductStatus.CREATED,
        seller_id=1,
        has_sku=True,
    )
    sku = _mock_sku()

    app.dependency_overrides["get_db"] = _override_get_db(product, [sku])

    response = client.post(
        "/api/v1/products/100/approve",
        json={"comment": "Approve"},
        params={"seller_id": 1},
    )

    assert response.status_code == 409, f"Expected 409, got {response.status_code}: {response.text}"
    data = response.json()
    assert data["detail"]["code"] == "PRODUCT_WRONG_STATUS"
    assert "CREATED" in data["detail"]["message"]


# ─────────────────────────────────────────────
# Test 4: approve_without_sku_returns_409
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_approve_without_sku_returns_409(client):
    """
    Unhappy path:
    - Product is ON_MODERATION but has no SKU
    - Moderator tries to approve
    - Should return 409 Conflict
    """
    product = _mock_product(
        product_id=100,
        status=ProductStatus.ON_MODERATION,
        seller_id=1,
        has_sku=False,
    )

    app.dependency_overrides["get_db"] = _override_get_db(product, [])

    response = client.post(
        "/api/v1/products/100/approve",
        json={"comment": "Approve"},
        params={"seller_id": 1},
    )

    assert response.status_code == 409, f"Expected 409, got {response.status_code}: {response.text}"
    data = response.json()
    assert data["detail"]["code"] == "PRODUCT_NO_SKU"
    assert "no SKU" in data["detail"]["message"].lower()


# ─────────────────────────────────────────────
# Bonus: Moderation event endpoint tests
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_receive_moderation_event_moderated(client):
    """Test POST /api/v1/moderation/events with MODERATED event type."""
    product = _mock_product(
        product_id=100,
        status=ProductStatus.ON_MODERATION,
        seller_id=1,
        has_sku=True,
    )
    sku = _mock_sku()

    app.dependency_overrides["get_db"] = _override_get_db(product, [sku])

    with patch("src.services.moderation.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=MagicMock(status_code=200))
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_client)
        mock_ctx.__aexit__ = AsyncMock(return_value=None)
        mock_client_cls.return_value = mock_ctx

        response = client.post(
            "/api/v1/moderation/events",
            json={
                "idempotency_key": "550e8400-e29b-41d4-a716-446655440000",
                "product_id": 100,
                "event_type": "MODERATED",
                "moderator_id": "mod-1",
                "moderator_comment": "Looks good",
                "occurred_at": "2026-06-17T10:00:00Z",
            },
        )

    assert response.status_code == 200, f"Expected 200, got {response.text}"
    data = response.json()
    assert data["event_type"] == "MODERATED"
    assert data["status"] == "accepted"


@pytest.mark.asyncio
async def test_receive_moderation_event_wrong_status(client):
    """Test that MODERATED event on a non-ON_MODERATION product returns 409."""
    product = _mock_product(
        product_id=100,
        status=ProductStatus.CREATED,
        seller_id=1,
        has_sku=True,
    )
    sku = _mock_sku()

    app.dependency_overrides["get_db"] = _override_get_db(product, [sku])

    response = client.post(
        "/api/v1/moderation/events",
        json={
            "idempotency_key": "550e8400-e29b-41d4-a716-446655440001",
            "product_id": 100,
            "event_type": "MODERATED",
            "occurred_at": "2026-06-17T10:00:00Z",
        },
    )

    assert response.status_code == 409, f"Expected 409, got {response.text}"
    data = response.json()
    assert data["detail"]["code"] == "PRODUCT_WRONG_STATUS"