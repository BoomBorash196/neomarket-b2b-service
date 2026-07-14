from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.base import get_db
from src.models.sku import SKU

router = APIRouter()


@router.post("")
async def reserve_stock(reservations: list[dict], db: AsyncSession = Depends(get_db)):
    """
    Резервировать несколько SKU одновременно (batch)
    Используется при создании заказа в B2C.
    Поддерживает отрицательное quantity для освобождения резерва (cancel).

    Format: [{"sku_id": int, "quantity": int}, ...]
    """
    results = []
    failed = []

    for res in reservations:
        sku_id = res.get("sku_id")
        quantity = res.get("quantity", 1)

        sku = await db.get(SKU, sku_id)
        if not sku:
            failed.append({
                "sku_id": sku_id,
                "reason": "SKU not found",
            })
            continue

        # Handle unreserve (negative quantity from cancel flow)
        if quantity < 0:
            release_qty = abs(quantity)
            if sku.blocked_quantity < release_qty:
                failed.append({
                    "sku_id": sku_id,
                    "reason": "Cannot release more than reserved",
                    "available": sku.blocked_quantity,
                })
                continue
            sku.blocked_quantity -= release_qty
            sku.active_quantity += release_qty
            results.append({
                "sku_id": sku_id,
                "reserved": quantity,
                "remaining": sku.active_quantity,
            })
            continue

        # Normal reserve
        if sku.active_quantity < quantity:
            failed.append({
                "sku_id": sku_id,
                "reason": "Insufficient stock",
                "available": sku.active_quantity,
            })
            continue

        sku.active_quantity -= quantity
        sku.blocked_quantity += quantity
        results.append({
            "sku_id": sku_id,
            "reserved": quantity,
            "remaining": sku.active_quantity,
        })

    await db.commit()

    return {
        "success": results,
        "failed": failed,
        "total_reserved": len(results),
        "total_failed": len(failed),
    }
