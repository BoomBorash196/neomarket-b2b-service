from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from src.models.base import Base


class IdempotencyRecord(Base):
    """Stores processed idempotency keys to prevent duplicate event processing."""
    __tablename__ = "idempotency_records"

    id = Column(Integer, primary_key=True, index=True)
    key = Column(String(255), unique=True, nullable=False, index=True)
    product_id = Column(Integer, ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    event_type = Column(String(50), nullable=False)
    processed_at = Column(DateTime(timezone=True), server_default=func.now())

    product = relationship("Product")

    def __repr__(self):
        return f"<IdempotencyRecord(key={self.key}, product_id={self.product_id}, event={self.event_type})>"
