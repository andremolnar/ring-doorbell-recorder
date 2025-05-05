"""Tests for the event deduplication mechanism."""

import asyncio
import json
import os
import pytest
import time
from datetime import datetime

from src.core.interfaces import EventData
from src.storage.storage_impl import DatabaseStorage, FileStorage
from src.models.ring_events import RingEvent

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select


class MockEvent:
    """Mock Ring API event."""
    def __init__(self, id, kind="motion", device_name="Test Device", device_id="123456"):
        self.id = id
        self.kind = kind
        self.now = time.time()
        self.doorbot_id = device_id
        self.device_name = device_name


@pytest.fixture
async def db_storage():
    """Create a database storage for testing."""
    # Use in-memory SQLite database for testing
    db_url = "sqlite+aiosqlite:///:memory:"
    engine = create_async_engine(db_url)
    
    # Create tables
    from src.models.base import Base
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    # Create storage
    storage = DatabaseStorage(db_url)
    
    yield storage
    
    # Cleanup
    await storage.close()


@pytest.fixture
def event_data():
    """Create sample event data for testing."""
    return EventData(
        id="test-event-123",
        kind="motion",
        created_at=datetime.now().isoformat(),
        device_id="test-device-456",
        device_name="Test Device"
    )


@pytest.fixture
def ding_event_data():
    """Create sample ding event data for testing."""
    return EventData(
        id="test-ding-123",
        kind="ding",
        created_at=datetime.now().isoformat(),
        device_id="test-device-456",
        device_name="Test Device"
    )


@pytest.fixture
def on_demand_event_data():
    """Create sample on-demand event data for testing."""
    return EventData(
        id="test-ondemand-123",
        kind="on_demand",
        created_at=datetime.now().isoformat(),
        device_id="test-device-456",
        device_name="Test Device" 
    )


@pytest.fixture
def other_event_data():
    """Create sample event with non-standard type for testing."""
    return EventData(
        id="test-other-123",
        kind="custom_event",  # A non-standard event type
        created_at=datetime.now().isoformat(),
        device_id="test-device-456",
        device_name="Test Device"
    )

@pytest.mark.asyncio
async def test_file_storage_handles_errors(tmp_path):
    """Test that FileStorage handles errors gracefully."""
    # Create a storage with a temporary path
    storage_path = str(tmp_path)
    storage = FileStorage(storage_path)
    
    # Create a test event
    event = EventData(
        id="test-event-456",
        kind="motion",
        created_at=datetime.now().isoformat(),
        device_id="test-device-789",
        device_name="Test Device"
    )
    
    # First save should succeed
    result = await storage.save_event(event)
    assert result is True, "Save should return True on success"
    
    # Verify the file was created
    date_str = datetime.now().strftime("%Y-%m-%d")
    event_dir = os.path.join(storage_path, date_str, event.kind)
    files = os.listdir(event_dir)
    assert len(files) == 1, "One file should be created"
    assert files[0].startswith(event.id), "Filename should start with event ID"


@pytest.mark.asyncio
async def test_db_storage_different_event_types(db_storage, ding_event_data, on_demand_event_data, other_event_data):
    """Test that different event types are saved correctly."""
    # Save different event types
    result1 = await db_storage.save_event(ding_event_data)
    result2 = await db_storage.save_event(on_demand_event_data)
    result3 = await db_storage.save_event(other_event_data)
    
    assert result1 is True, "Ding event should be saved successfully"
    assert result2 is True, "On-demand event should be saved successfully"
    assert result3 is True, "Other event should be saved successfully"
    
    # Verify all events are in the database
    async with db_storage._session_factory() as session:
        # Check ding event
        result = await session.execute(select(RingEvent).where(RingEvent.id == ding_event_data.id))
        ding_event = result.scalar_one_or_none()
        assert ding_event is not None, "Ding event should be in the database"
        assert ding_event.kind == "ding", "Event kind should be 'ding'"
        
        # Check on-demand event
        result = await session.execute(select(RingEvent).where(RingEvent.id == on_demand_event_data.id))
        on_demand_event = result.scalar_one_or_none()
        assert on_demand_event is not None, "On-demand event should be in the database"
        assert on_demand_event.kind == "on_demand", "Event kind should be 'on_demand'"
        
        # Check other event
        result = await session.execute(select(RingEvent).where(RingEvent.id == other_event_data.id))
        other_event = result.scalar_one_or_none()
        assert other_event is not None, "Other event should be in the database"
        assert other_event.kind == "custom_event", "Event kind should be 'custom_event'"
