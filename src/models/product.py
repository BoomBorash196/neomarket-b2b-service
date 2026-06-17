from sqlalchemy import Column, Integer, String, Enum, Text, Boolean, DateTime, ForeignKey, Enum as SQLEnum
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from src.models.base import Base
import enum


class ProductStatus(str, enum.Enum):
    CREATED = "CREATED"
    ON_MODERATION = "ON_MODERATION"
    MODERATED = "MODERATED"
    BLOCKED = "BLOCKED"


class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, index=True)
    seller_id = Column(Integer, nullable=False, index=True)
    title = Column(String(500), nullable=False)
    description = Column(Text, nullable=True)
    status = Column(SQLEnum(ProductStatus), default=ProductStatus.CREATED, nullable=False)
    category_id = Column(Integer, ForeignKey("categories.id"), nullable=False)

    images = relationship("ProductImage", back_populates="product", cascade="all, delete-orphan")
    characteristics = relationship("ProductCharacteristic", back_populates="product", cascade="all, delete-orphan")
    skus = relationship("SKU", back_populates="product", cascade="all, delete-orphan")
    category = relationship("Category", back_populates="products")

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    deleted = Column(Boolean, default=False, nullable=False)

    blocking_reason_id = Column(Integer, ForeignKey("product_blocking_reasons.id"), nullable=True)
    blocking_comment = Column(Text, nullable=True)

    def __repr__(self):
        return f"<Product(id={self.id}, title='{self.title}', status={self.status.value})>"


class ProductImage(Base):
    __tablename__ = "product_images"

    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(Integer, ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    url = Column(String(500), nullable=False)
    ordering = Column(Integer, default=0)

    product = relationship("Product", back_populates="images")

    def __repr__(self):
        return f"<ProductImage(id={self.id}, product_id={self.product_id}, ordering={self.ordering})>"


class ProductCharacteristic(Base):
    __tablename__ = "product_characteristics"

    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(Integer, ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(200), nullable=False)
    value = Column(String(500), nullable=False)

    product = relationship("Product", back_populates="characteristics")

    def __repr__(self):
        return f"<ProductCharacteristic(product_id={self.product_id}, name='{self.name}', value='{self.value}')>"


class Category(Base):
    __tablename__ = "categories"

    id = Column(Integer, primary_key=True, index=True)
    parent_id = Column(Integer, ForeignKey("categories.id"), nullable=True)
    name = Column(String(200), nullable=False, unique=True)
    slug = Column(String(200), unique=True, nullable=False)

    parent = relationship("Category", remote_side=[id], backref="children")
    products = relationship("Product", back_populates="category")

    def __repr__(self):
        return f"<Category(id={self.id}, name='{self.name}', slug='{self.slug}')>"
