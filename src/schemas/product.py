from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from enum import Enum


class ProductStatusEnum(str, Enum):
    CREATED = "CREATED"
    ON_MODERATION = "ON_MODERATION"
    MODERATED = "MODERATED"
    BLOCKED = "BLOCKED"


class ProductImageBase(BaseModel):
    url: str
    ordering: int = 0


class ProductImageCreate(ProductImageBase):
    pass


class ProductImageResponse(ProductImageBase):
    id: int
    product_id: int

    class Config:
        from_attributes = True


class ProductCharacteristicBase(BaseModel):
    name: str
    value: str


class ProductCharacteristicCreate(ProductCharacteristicBase):
    pass


class ProductCharacteristicResponse(ProductCharacteristicBase):
    id: int
    product_id: int

    class Config:
        from_attributes = True


class SKUBase(BaseModel):
    sku_code: str
    name: str
    price: int = Field(..., description="Цена в копейках")
    active_quantity: int = 0
    characteristics: List[ProductCharacteristicBase] = []


class SKUCreate(SKUBase):
    pass


class SKUResponse(SKUBase):
    id: int
    product_id: int
    active: bool = True

    class Config:
        from_attributes = True


class ProductBase(BaseModel):
    seller_id: int
    title: str = Field(..., min_length=1, max_length=500)
    description: Optional[str] = None
    category_id: int = Field(..., description="Category ID is required")

    class Config:
        from_attributes = True


class ProductCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=500)
    description: Optional[str] = None
    category_id: int = Field(..., description="Category ID is required")
    images: List[ProductImageCreate] = Field(default_factory=list, min_length=1, description="At least one image is required")
    characteristics: List[ProductCharacteristicCreate] = []
    skus: List[SKUCreate] = []


class ProductUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=500)
    description: Optional[str] = None
    category_id: Optional[int] = None


class ProductResponse(ProductBase):
    id: int
    status: str
    images: List[ProductImageResponse] = []
    characteristics: List[ProductCharacteristicResponse] = []
    skus: List[SKUResponse] = []
    created_at: datetime
    updated_at: Optional[datetime] = None
    deleted: bool = False
    blocking_comment: Optional[str] = None
    blocking_reason: Optional[dict] = None  # for blocked status
    field_reports: Optional[list] = None

    class Config:
        from_attributes = True
