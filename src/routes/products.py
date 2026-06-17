from fastapi import APIRouter, HTTPException, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from typing import List, Optional

from src.models.base import get_db
from src.models.product import Product, ProductStatus, ProductImage, ProductCharacteristic
from src.models.sku import SKU
from src.schemas.product import ProductCreate, ProductResponse, ProductUpdate, ProductStatusEnum

router = APIRouter()


def _check_hard_blocked(product: Product) -> None:
    """Raise 403 if product is HARD_BLOCKED."""
    if product.status == ProductStatus.HARD_BLOCKED:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "PRODUCT_HARD_BLOCKED",
                "message": "Product is HARD_BLOCKED — modification is forbidden",
            },
        )


@router.post("/products", response_model=ProductResponse, status_code=201)
async def create_product(
    product: ProductCreate,
    db: AsyncSession = Depends(get_db)
):
    """
    Создать новый товар
    """
    db_product = Product(
        title=product.title,
        description=product.description,
        category_id=product.category_id,
        seller_id=product.seller_id,
        status=ProductStatus.CREATED
    )
    db.session.add(db_product)
    await db.flush()

    # Добавляем изображения
    for img_data in product.images:
        img = ProductImage(product_id=db_product.id, **img_data.model_dump())
        db.session.add(img)

    # Добавляем характеристики
    for char_data in product.characteristics:
        char = ProductCharacteristic(product_id=db_product.id, **char_data.model_dump())
        db.session.add(char)

    # Добавляем SKU
    for sku_data in product.skus:
        sku = SKU(
            product_id=db_product.id,
            sku_code=sku_data.sku_code,
            name=sku_data.name,
            price=sku_data.price,
            active_quantity=sku_data.active_quantity
        )
        db.session.add(sku)

        # Характеристики SKU
        for sku_char_data in sku_data.characteristics:
            from src.models.sku import SKUCharacteristic
            sku_char = SKUCharacteristic(sku_id=sku.id, **sku_char_data.model_dump())
            db.session.add(sku_char)

    await db.commit()
    await db.refresh(db_product)

    return db_product


@router.get("/products", response_model=List[ProductResponse])
async def list_products(
    seller_id: Optional[int] = Query(None, description="Фильтр по продавцу"),
    status: Optional[ProductStatusEnum] = Query(None, description="Фильтр по статусу"),
    category_id: Optional[int] = Query(None, description="Фильтр по категории"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db)
):
    """
    Получить список товаров (с пагинацией)
    """
    query = select(Product).where(Product.deleted == False)

    if seller_id:
        query = query.where(Product.seller_id == seller_id)
    if status:
        query = query.where(Product.status == ProductStatus(status))
    if category_id:
        query = query.where(Product.category_id == category_id)

    query = query.offset((page - 1) * size).limit(size)

    result = await db.execute(query)
    products = result.scalars().all()

    return products


@router.post("/products/batch")
async def get_products_batch(product_ids: list[int], db: AsyncSession = Depends(get_db)):
    """
    Получить несколько товаров по списку ID (batch запрос для B2C)
    """
    products = await db.execute(select(Product).where(Product.id.in_(product_ids)))
    product_list = products.scalars().all()
    
    result = {}
    for product in product_list:
        min_price = min([sku.price for sku in product.skus], default=product.skus[0].price if product.skus else 0)
        result[str(product.id)] = {
            "product_id": product.id,
            "title": product.title,
            "description": product.description,
            "category_id": product.category_id,
            "status": product.status.value,
            "main_image_url": product.images[0].url if product.images else "",
            "images": [img.url for img in product.images],
            "min_price": min_price,
            "is_available": product.status == ProductStatus.MODERATED and not product.deleted,
            "characteristics": {
                char.name: char.value for char in product.characteristics
            },
            "skus": [
                {
                    "sku_id": sku.id,
                    "sku_code": sku.sku_code,
                    "name": sku.name,
                    "price": sku.price,
                    "active_quantity": sku.active_quantity,
                    "blocked_quantity": sku.blocked_quantity,
                    "active": sku.active,
                    "characteristics": [
                        {"name": c.name, "value": c.value}
                        for c in sku.characteristics
                    ]
                }
                for sku in product.skus
            ]
        }
    return result


@router.get("/products/{product_id}", response_model=ProductResponse)
async def get_product(product_id: int, db: AsyncSession = Depends(get_db)):
    """
    Получить товар по ID
    """
    result = await db.get(Product, product_id)
    if not result or result.deleted:
        raise HTTPException(status_code=404, detail="Product not found")
    return result


@router.put("/products/{product_id}", response_model=ProductResponse)
async def update_product(
    product_id: int,
    product_update: ProductUpdate,
    db: AsyncSession = Depends(get_db)
):
    """
    Обновить товар
    """
    db_product = await db.get(Product, product_id)
    if not db_product or db_product.deleted:
        raise HTTPException(status_code=404, detail="Product not found")

    _check_hard_blocked(db_product)

    update_data = product_update.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_product, field, value)

    await db.commit()
    await db.refresh(db_product)

    return db_product


@router.post("/products/{product_id}/submit-moderation", status_code=204)
async def submit_for_moderation(product_id: int, db: AsyncSession = Depends(get_db)):
    """
    Отправить товар на модерацию
    """
    db_product = await db.get(Product, product_id)
    if not db_product or db_product.deleted:
        raise HTTPException(status_code=404, detail="Product not found")

    _check_hard_blocked(db_product)

    if db_product.status != ProductStatus.CREATED:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot submit product with status {db_product.status.value}"
        )

    db_product.status = ProductStatus.ON_MODERATION

    # TODO: Отправить событие в Moderation сервис
    # async with httpx.AsyncClient() as client:
    #     await client.post(
    #         f"{settings.moderation_service_url}/api/v1/products/{product_id}/notify"
    #     )

    await db.commit()

    return None


@router.post("/products/{product_id}/delete", status_code=204)
async def delete_product(product_id: int, db: AsyncSession = Depends(get_db)):
    """
    Удалить товар (мягкое удаление)
    """
    db_product = await db.get(Product, product_id)
    if not db_product or db_product.deleted:
        raise HTTPException(status_code=404, detail="Product not found")

    _check_hard_blocked(db_product)

    db_product.deleted = True
    await db.commit()

    return None
