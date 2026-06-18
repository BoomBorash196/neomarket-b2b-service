from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from src.models.base import get_db
from src.models.product import Product, ProductStatus
from src.models.sku import SKU, SKUCharacteristic
from src.schemas.product import SKUCreate, SKUResponse
from fastapi import Request

router = APIRouter()


@router.post("/skus", response_model=SKUResponse, status_code=201)
async def create_sku(sku: SKUCreate, request: Request, db: AsyncSession = Depends(get_db)):
    """
    Create SKU. For first SKU on product: transition to ON_MODERATION, emit event to Moderation.
    """
    # Проверяем существование товара
    product = await db.get(Product, sku.product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    # HARD_BLOCKED check for US-B2B-02
    if product.status == ProductStatus.HARD_BLOCKED:
        raise HTTPException(status_code=403, detail={"code": "PRODUCT_HARD_BLOCKED"})

    # Check if first SKU
    skus_count = await db.execute(select(SKU).where(SKU.product_id == sku.product_id))
    is_first_sku = len(skus_count.scalars().all()) == 0

    # Проверяем уникальный SKU код
    existing = await db.execute(
        select(SKU).where(SKU.sku_code == sku.sku_code)
    )
    if existing.scalar():
        raise HTTPException(status_code=400, detail="SKU code already exists")

    db_sku = SKU(
        product_id=sku.product_id,
        sku_code=sku.sku_code,
        name=sku.name,
        price=sku.price,
        active_quantity=sku.active_quantity
    )
    db.add(db_sku)

    # Добавляем характеристики SKU
    for char_data in sku.characteristics:
        char = SKUCharacteristic(sku_id=db_sku.id, **char_data.model_dump())
        db.add(char)

    await db.flush()  # to get id

    if is_first_sku and product.status == ProductStatus.CREATED:
        product.status = ProductStatus.ON_MODERATION
        # TODO: emit CREATED event to Moderation (per ADR fire-and-forget or outbox)
        # e.g. httpx post with X-Service-Key

    await db.commit()
    await db.refresh(db_sku)

    return db_sku


@router.put("/skus/{sku_id}", response_model=SKUResponse)
async def update_sku(sku_id: int, sku_update: SKUCreate, db: AsyncSession = Depends(get_db)):
    """
    Обновить SKU
    """
    db_sku = await db.get(SKU, sku_id)
    if not db_sku:
        raise HTTPException(status_code=404, detail="SKU not found")

    # Обновляем поля
    db_sku.sku_code = sku_update.sku_code
    db_sku.name = sku_update.name
    db_sku.price = sku_update.price
    db_sku.active_quantity = sku_update.active_quantity

    # Обновляем характеристики
    await db.execute(
        "DELETE FROM sku_characteristics WHERE sku_id = :sku_id",
        {"sku_id": sku_id}
    )

    for char_data in sku_update.characteristics:
        char = SKUCharacteristic(
            sku_id=sku_id,
            name=char_data.name,
            value=char_data.value
        )
        db.add(char)

    await db.commit()
    await db.refresh(db_sku)

    return db_sku


@router.get("/skus/{sku_id}", response_model=SKUResponse)
async def get_sku(sku_id: int, db: AsyncSession = Depends(get_db)):
    """
    Получить SKU по ID
    """
    sku = await db.get(SKU, sku_id)
    if not sku:
        raise HTTPException(status_code=404, detail="SKU not found")
    return sku


@router.post("/skus/{sku_id}/reserve")
async def reserve_sku(sku_id: int, quantity: int, db: AsyncSession = Depends(get_db)):
    """
    Резервировать товар (уменьшить activeQuantity)
    Используется при оформлении заказа в B2C
    """
    sku = await db.get(SKU, sku_id)
    if not sku:
        raise HTTPException(status_code=404, detail="SKU not found")

    if sku.active_quantity < quantity:
        raise HTTPException(
            status_code=400,
            detail=f"Insufficient quantity. Available: {sku.active_quantity}, requested: {quantity}"
        )

    sku.active_quantity -= quantity
    sku.blocked_quantity += quantity

    await db.commit()
    await db.refresh(sku)

    return {
        "sku_id": sku_id,
        "reserved": quantity,
        "remaining": sku.active_quantity
    }


@router.post("/skus/{sku_id}/release")
async def release_sku(sku_id: int, quantity: int, db: AsyncSession = Depends(get_db)):
    """
    Освободить резерв (вернуть товар в activeQuantity)
    Используется при отмене заказа в B2C
    """
    sku = await db.get(SKU, sku_id)
    if not sku:
        raise HTTPException(status_code=404, detail="SKU not found")

    if sku.blocked_quantity < quantity:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot release more than reserved. Reserved: {sku.blocked_quantity}"
        )

    sku.blocked_quantity -= quantity
    sku.active_quantity += quantity

    await db.commit()
    await db.refresh(sku)

    return {
        "sku_id": sku_id,
        "released": quantity,
        "active": sku.active_quantity
    }


@router.post("/skus/batch")
async def get_skus_batch(sku_ids: list[int], db: AsyncSession = Depends(get_db)):
    """
    Получить несколько SKU по списку ID (batch запрос)
    Используется в B2C для получения деталей товаров
    """
    skus = await db.execute(select(SKU).where(SKU.id.in_(sku_ids)))
    sku_list = skus.scalars().all()
    
    result = {}
    for sku in sku_list:
        result[str(sku.id)] = {
            "id": sku.id,
            "product_id": sku.product_id,
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
    return result


@router.post("/reserve")
async def reserve_stock(reservations: list[dict], db: AsyncSession = Depends(get_db)):
    """
    All-or-nothing reserve for multiple SKUs (US-B2B-08).
    Uses transaction rollback on partial failure.
    Idempotency via key in future.
    """
    # For simplicity, use try/except with rollback for all-or-nothing
    try:
        results = []
        for res in reservations:
            sku_id = res.get("sku_id")
            quantity = res.get("quantity", 1)
            
            sku = await db.get(SKU, sku_id, with_for_update=True)  # lock
            if not sku:
                raise HTTPException(status_code=404, detail=f"SKU {sku_id} not found")
            
            if sku.active_quantity < quantity:
                raise HTTPException(
                    status_code=409,
                    detail={"code": "INSUFFICIENT_STOCK", "message": "Partial insufficient - rollback"}
                )
            
            sku.active_quantity -= quantity
            sku.blocked_quantity += quantity
            results.append({
                "sku_id": sku_id,
                "reserved": quantity,
                "remaining": sku.active_quantity
            })
        
        await db.commit()
        return {
            "success": results,
            "total_reserved": len(results)
        }
    except HTTPException as e:
        await db.rollback()
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
