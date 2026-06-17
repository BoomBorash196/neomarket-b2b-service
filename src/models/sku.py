from sqlalchemy import Column, Integer, String, Text, Boolean, ForeignKey, Enum as SQLEnum
from sqlalchemy.orm import relationship
from src.models.base import Base


class SKU(Base):
    __tablename__ = "skus"

    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(Integer, ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    sku_code = Column(String(100), nullable=False, unique=True, index=True)
    name = Column(String(200), nullable=False)
    price = Column(Integer, nullable=False)  # цена в копейках
    active_quantity = Column(Integer, default=0, nullable=False)
    blocked_quantity = Column(Integer, default=0, nullable=False)
    active = Column(Boolean, default=True, nullable=False)

    characteristics = relationship("SKUCharacteristic", back_populates="sku", cascade="all, delete-orphan")
    product = relationship("Product", back_populates="skus")

    def __repr__(self):
        return f"<SKU(id={self.id}, code='{self.sku_code}', price={self.price}, qty={self.active_quantity})>"


class SKUCharacteristic(Base):
    __tablename__ = "sku_characteristics"

    id = Column(Integer, primary_key=True, index=True)
    sku_id = Column(Integer, ForeignKey("skus.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(200), nullable=False)
    value = Column(String(500), nullable=False)

    sku = relationship("SKU", back_populates="characteristics")

    def __repr__(self):
        return f"<SKUCharacteristic(sku_id={self.sku_id}, name='{self.name}', value='{self.value}')>"
