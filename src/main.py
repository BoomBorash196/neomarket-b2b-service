from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.routes import products, skus, invoices, categories, moderation

app = FastAPI(
    title="NeoMarket B2B Seller Cabinet",
    description="API для управления товарами, SKU и накладными продавцов",
    version="0.1.0",
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Подключение роутеров
app.include_router(products.router, prefix="/api/v1", tags=["Products"])
app.include_router(skus.router, prefix="/api/v1", tags=["SKUs"])
app.include_router(invoices.router, prefix="/api/v1", tags=["Invoices"])
app.include_router(categories.router, prefix="/api/v1", tags=["Categories"])
app.include_router(moderation.router, prefix="/api/v1", tags=["Moderation"])
app.include_router(moderation.approve_router, prefix="/api/v1", tags=["Moderation"])


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "b2b-seller-cabinet"}
