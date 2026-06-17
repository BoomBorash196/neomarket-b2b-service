"""Tests for US-B2B-01: create product endpoint."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from src.main import app
from src.models.base import get_db as real_get_db
from src.models.product import Product, ProductStatus


def _mock_product(product_id: int = 500, seller_id: int = 42, status=ProductStatus.CREATED):
    product = MagicMock()
    product.id = product_id
    product.title = "Test Product"
    product.description = "Test desc"
    product.status = status
    product.seller_id = seller_id
    product.category_id = 1
    product.deleted = False
    product.blocking_comment = None
    product.images = []
    product.characteristics = []
    product.skus = []
    product.created_at = datetime.now(timezone.utc)
    product.updated_at = None
    return product


def _mock_session(product):
    session = AsyncMock()

    async def mock_get(model, ident):
        if model is Product:
            return product
        return None

    async def mock_execute(query):
        result = AsyncMock()
        scalars_mock = MagicMock()
        scalars_mock.all = MagicMock(return_value=[])
        result.scalars = MagicMock(return_value=scalars_mock)
        return result

    session.get = AsyncMock(side_effect=mock_get)
    session.execute = AsyncMock(side_effect=mock_execute)
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.add = MagicMock()

    async def mock_refresh(obj):
        obj.id = 500
        obj.created_at = datetime.now(timezone.utc)
        obj.deleted = False
        obj.images = []
        obj.characteristics = []
        obj.skus = []
        obj.updated_at = None
        return None

    session.refresh = mock_refresh
    return session


def make_test_client(product, seller_id: int = 42):
    session = _mock_session(product)

    async def override_get_db():
        yield session

    app.dependency_overrides[real_get_db] = override_get_db
    return TestClient(app, base_url="http://test", headers={"X-Seller-Id": str(seller_id)})


@pytest.mark.asyncio
async def test_create_product_returns_201_with_created_status():
    """Happy path: product created with status=CREATED, skus=[]."""
    product = _mock_product(seller_id=42)
    client = make_test_client(product, seller_id=42)

    response = client.post(
        "/api/v1/products",
        json={
            "title": "New Product",
            "description": "Test description",
            "category_id": 1,
            "images": [
                {"url": "https://example.com/img.jpg", "ordering": 0}
            ],
            "characteristics": [],
            "skus": [],
        },
    )

    assert response.status_code == 201, f"Expected 201, got {response.status_code}: {response.text}"
    data = response.json()
    assert data["title"] == "New Product"
    assert data["status"] == "CREATED"
    assert data["skus"] == []


@pytest.mark.asyncio
async def test_seller_id_taken_from_jwt():
    """seller_id in the created product must come from JWT (header), not from body."""
    product = _mock_product(seller_id=999)
    client = make_test_client(product, seller_id=999)

    response = client.post(
        "/api/v1/products",
        json={
            "title": "New Product",
            "description": "Test description",
            "category_id": 1,
            "images": [
                {"url": "https://example.com/img.jpg", "ordering": 0}
            ],
            "characteristics": [],
            "skus": [],
        },
    )

    assert response.status_code == 201, f"Expected 201, got {response.status_code}: {response.text}"
    data = response.json()
    assert data["seller_id"] == 999


@pytest.mark.asyncio
async def test_missing_images_returns_400():
    """Request without images → 400 (422 from Pydantic validation)."""
    product = _mock_product()
    client = make_test_client(product)

    response = client.post(
        "/api/v1/products",
        json={
            "title": "New Product",
            "description": "Test description",
            "category_id": 1,
            "images": [],
            "characteristics": [],
            "skus": [],
        },
    )

    assert response.status_code == 422, f"Expected 422, got {response.status_code}: {response.text}"


@pytest.mark.asyncio
async def test_missing_category_returns_400():
    """Request without category_id → 400 (422 from Pydantic validation)."""
    product = _mock_product()
    client = make_test_client(product)

    response = client.post(
        "/api/v1/products",
        json={
            "title": "New Product",
            "description": "Test description",
            "images": [
                {"url": "https://example.com/img.jpg", "ordering": 0}
            ],
            "characteristics": [],
            "skus": [],
        },
    )

    assert response.status_code == 422, f"Expected 422, got {response.status_code}: {response.text}"
