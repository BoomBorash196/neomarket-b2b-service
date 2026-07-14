"""Tests for idempotency, service auth, status transitions, and delete flow."""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.main import app
from src.models.base import get_db as real_get_db
from src.models.product import Product, ProductStatus
from src.models.idempotency import IdempotencyRecord
from tests.conftest import _mock_product, _mock_sku, _mock_session


def _make_idempotent_record(key: str, processed_at: datetime | None = None):
    """Create a mock IdempotencyRecord with proper processed_at."""
    record = MagicMock()
    record.key = key
    record.processed_at = processed_at or datetime.now(timezone.utc) - timedelta(hours=1)
    return record


# ──────────────────────── Idempotency ────────────────────────

@pytest.mark.asyncio
async def test_duplicate_event_no_side_effects():
    """Duplicate event with same idempotency_key returns 200 without side effects."""
    product = _mock_product(
        product_id=100,
        status=ProductStatus.ON_MODERATION,
        seller_id=1,
        has_sku=True,
    )
    sku = _mock_sku()
    session = _mock_session(product, [sku])

    # Mock idempotency check — key already exists
    async def mock_execute(query):
        result = AsyncMock()
        query_str = str(query)
        if "idempotency_records" in query_str or "key" in query_str:
            # Return existing record with valid processed_at
            record = _make_idempotent_record("idem-001")
            result.scalar_one_or_none = MagicMock(return_value=record)
            return result
        # For SKU query
        scalars_mock = MagicMock()
        scalars_mock.all = MagicMock(return_value=[sku])
        result.scalars = MagicMock(return_value=scalars_mock)
        return result

    session.execute = AsyncMock(side_effect=mock_execute)

    async def override_get_db():
        yield session

    app.dependency_overrides[real_get_db] = override_get_db

    with patch("src.services.moderation.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=MagicMock(status_code=200))
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_client)
        mock_ctx.__aexit__ = AsyncMock(return_value=None)
        mock_client_cls.return_value = mock_ctx

        response = TestClient(app, base_url="http://test").post(
            "/api/v1/moderation/events",
            json={
                "product_id": 100,
                "event_type": "MODERATED",
                "idempotency_key": "idem-001",
            },
            headers={"X-Service-Token": "neomarket-b2b-secret"},
        )

    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
    data = response.json()
    assert data["status"] == "accepted"


@pytest.mark.asyncio
async def test_duplicate_blocked_event_no_side_effects():
    """Duplicate BLOCKED event with same key returns 200."""
    product = _mock_product(
        product_id=100,
        status=ProductStatus.ON_MODERATION,
        seller_id=1,
        has_sku=True,
    )
    sku = _mock_sku()
    session = _mock_session(product, [sku])

    async def mock_execute(query):
        result = AsyncMock()
        query_str = str(query)
        if "idempotency_records" in query_str or "key" in query_str:
            record = _make_idempotent_record("idem-block-001")
            result.scalar_one_or_none = MagicMock(return_value=record)
            return result
        scalars_mock = MagicMock()
        scalars_mock.all = MagicMock(return_value=[sku])
        result.scalars = MagicMock(return_value=scalars_mock)
        return result

    session.execute = AsyncMock(side_effect=mock_execute)

    async def override_get_db():
        yield session

    app.dependency_overrides[real_get_db] = override_get_db

    response = TestClient(app, base_url="http://test").post(
        "/api/v1/moderation/events",
        json={
            "product_id": 100,
            "event_type": "BLOCKED",
            "hard_block": False,
            "idempotency_key": "idem-block-001",
        },
        headers={"X-Service-Token": "neomarket-b2b-secret"},
    )

    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"


# ──────────────────────── Service Auth ────────────────────────

@pytest.mark.asyncio
async def test_missing_service_header_401():
    """Request without X-Service-Token returns 401."""
    response = TestClient(app, base_url="http://test").post(
        "/api/v1/moderation/events",
        json={
            "product_id": 100,
            "event_type": "MODERATED",
            "idempotency_key": "idem-002",
        },
    )

    assert response.status_code == 401, f"Expected 401, got {response.status_code}: {response.text}"
    data = response.json()
    assert data["detail"]["code"] == "UNAUTHORIZED_SERVICE"


@pytest.mark.asyncio
async def test_invalid_service_header_401():
    """Request with wrong X-Service-Token returns 401."""
    response = TestClient(app, base_url="http://test").post(
        "/api/v1/moderation/events",
        json={
            "product_id": 100,
            "event_type": "MODERATED",
            "idempotency_key": "idem-003",
        },
        headers={"X-Service-Token": "wrong-token"},
    )

    assert response.status_code == 401, f"Expected 401, got {response.status_code}: {response.text}"
    data = response.json()
    assert data["detail"]["code"] == "UNAUTHORIZED_SERVICE"


# ──────────────────────── Status Transitions ────────────────────────

@pytest.mark.asyncio
async def test_edited_returns_to_review():
    """Editing a MODERATED product returns it to ON_MODERATION."""
    product = _mock_product(
        product_id=100,
        status=ProductStatus.MODERATED,
        seller_id=1,
        has_sku=True,
    )
    session = _mock_session(product, [])

    async def mock_refresh(obj):
        obj.status = ProductStatus.ON_MODERATION
        obj.previous_snapshot = '{"status": "MODERATED"}'
        return None

    session.refresh = mock_refresh
    session.commit = AsyncMock()

    async def override_get_db():
        yield session

    app.dependency_overrides[real_get_db] = override_get_db

    response = TestClient(app, base_url="http://test").put(
        "/api/v1/products/100",
        json={"title": "Updated title"},
        headers={"X-Seller-Id": "1"},
    )

    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
    data = response.json()
    assert data["status"] == "ON_MODERATION"


@pytest.mark.asyncio
async def test_edited_updates_in_review():
    """Editing a BLOCKED product returns it to ON_MODERATION."""
    product = _mock_product(
        product_id=100,
        status=ProductStatus.BLOCKED,
        seller_id=1,
        has_sku=True,
    )
    session = _mock_session(product, [])

    async def mock_refresh(obj):
        obj.status = ProductStatus.ON_MODERATION
        obj.previous_snapshot = '{"status": "BLOCKED"}'
        return None

    session.refresh = mock_refresh
    session.commit = AsyncMock()

    async def override_get_db():
        yield session

    app.dependency_overrides[real_get_db] = override_get_db

    response = TestClient(app, base_url="http://test").put(
        "/api/v1/products/100",
        json={"title": "Updated title"},
        headers={"X-Seller-Id": "1"},
    )

    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
    data = response.json()
    assert data["status"] == "ON_MODERATION"


# ──────────────────────── Delete Flow ────────────────────────

@pytest.mark.asyncio
async def test_deleted_archived():
    """Deleting a product sets deleted=True and notifies moderation."""
    product = _mock_product(
        product_id=100,
        status=ProductStatus.ON_MODERATION,
        seller_id=1,
        has_sku=True,
    )
    session = _mock_session(product, [])

    async def override_get_db():
        yield session

    app.dependency_overrides[real_get_db] = override_get_db

    with patch("src.routes.products._notify_moderation_delete") as mock_notify:
        response = TestClient(app, base_url="http://test").post(
            "/api/v1/products/100/delete",
        )

    assert response.status_code == 204, f"Expected 204, got {response.status_code}: {response.text}"
    mock_notify.assert_called_once_with(100)


@pytest.mark.asyncio
async def test_delete_moderated_product_returns_to_review():
    """Deleting a MODERATED product should also notify moderation."""
    product = _mock_product(
        product_id=100,
        status=ProductStatus.MODERATED,
        seller_id=1,
        has_sku=True,
    )
    session = _mock_session(product, [])

    async def override_get_db():
        yield session

    app.dependency_overrides[real_get_db] = override_get_db

    with patch("src.routes.products._notify_moderation_delete") as mock_notify:
        response = TestClient(app, base_url="http://test").post(
            "/api/v1/products/100/delete",
        )

    assert response.status_code == 204, f"Expected 204, got {response.status_code}: {response.text}"
    mock_notify.assert_called_once_with(100)


# ──────────────────────── Snapshot History ────────────────────────

@pytest.mark.asyncio
async def test_update_saves_previous_snapshot():
    """Updating a product saves previous_snapshot before changes."""
    product = _mock_product(
        product_id=100,
        status=ProductStatus.CREATED,
        seller_id=1,
        has_sku=True,
    )
    session = _mock_session(product, [])

    async def mock_refresh(obj):
        obj.previous_snapshot = json.dumps({"title": "Old title", "status": "CREATED"})
        obj.title = "New title"
        return None

    session.refresh = mock_refresh
    session.commit = AsyncMock()

    async def override_get_db():
        yield session

    app.dependency_overrides[real_get_db] = override_get_db

    response = TestClient(app, base_url="http://test").put(
        "/api/v1/products/100",
        json={"title": "New title"},
        headers={"X-Seller-Id": "1"},
    )

    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
    data = response.json()
    assert data["title"] == "New title"
    assert data.get("previous_snapshot") is not None