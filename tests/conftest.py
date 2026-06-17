"""Shared pytest fixtures and test helpers for the project."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from src.main import app
from src.models.product import ProductStatus


@pytest.fixture
def client():
    """Test client with dependency overrides applied."""
    # Override get_db so all routes use our mock session
    product = _mock_product(
        product_id=100,
        status=ProductStatus.ON_MODERATION,
        seller_id=1,
        has_sku=True,
    )
    sku = _mock_sku()
    session = _mock_db_session(product, [sku])

    async def override_get_db():
        yield session

    app.dependency_overrides["get_db"] = override_get_db

    test_client = TestClient(app)

    yield test_client

    # Clean up overrides after each test
    app.dependency_overrides.clear()


def _mock_product(
    product_id: int = 100,
    seller_id: int = 1,
    status=ProductStatus.ON_MODERATION,
    deleted: bool = False,
    has_sku: bool = True,
    blocking_comment: str | None = None,
):
    """Build a MagicMock that looks like a Product ORM object."""
    product = MagicMock()
    product.id = product_id
    product.title = "Test Product"
    product.description = "Test description"
    product.status = status
    product.seller_id = seller_id
    product.deleted = deleted
    product.blocking_comment = blocking_comment
    product.category_id = 1
    return product


def _mock_sku():
    """Build a MagicMock that looks like a SKU ORM object."""
    sku = MagicMock()
    sku.id = 200
    sku.sku_code = "TEST-SKU-001"
    sku.name = "Test SKU"
    sku.price = 1000
    sku.active_quantity = 10
    sku.active = True
    return sku


def _mock_db_session(product, skus=None):
    """
    Build an AsyncMock session that returns our mock product on get()
    and mock skus on execute(SELECT SKU ...).
    """
    session = AsyncMock()

    async def mock_get(model, ident):
        if model.__name__ == "Product":
            return product
        return None

    session.get = mock_get

    async def mock_execute(query):
        result = AsyncMock()
        result.scalars = MagicMock()
        result.scalars.return_value.all = MagicMock(
            return_value=skus if skus is not None else []
        )
        return result

    session.execute = mock_execute
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    return session
