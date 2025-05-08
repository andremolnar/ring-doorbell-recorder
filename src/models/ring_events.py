"""SQLAlchemy models for Ring event data."""

from sqlalchemy import Column, Integer, String, Text, DateTime, Float, Boolean, LargeBinary
from sqlalchemy.sql import func
from src.models.base import Base


class RingEvent(Base):
    """SQLAlchemy model for Ring events."""
    
    __tablename__ = "ring_events"
    
    # Primary key and basic identification
    id = Column(String(50), primary_key=True, index=True)
    
    # Event metadata
    kind = Column(String(20), nullable=False, index=True)  # ding, motion, on_demand
    created_at = Column(String(50), nullable=False, index=True)  # ISO format timestamp
    
    # Device information
    device_id = Column(String(50), nullable=False, index=True)
    device_name = Column(String(100), nullable=False)
    
    # Event specific data stored as JSON
    event_data = Column(Text, nullable=False)
    
    # Video related fields
    has_video = Column(Boolean, nullable=False, server_default='0', index=True)
    recording_id = Column(Integer, nullable=True)
    video_url = Column(String(500), nullable=True)  # URL with protocol (file://, http://, s3://, etc.)
    
    # Tracking fields
    stored_at = Column(DateTime, server_default=func.now())
    
    def __repr__(self):
        """String representation of the model."""
        return f"<RingEvent(id='{self.id}', kind='{self.kind}', device='{self.device_name}')>"
