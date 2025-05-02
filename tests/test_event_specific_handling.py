"""Tests for event-specific handling in AppManager."""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.app.app_manager import AppManager
from src.core.interfaces import IAuthManager, IEventListener, IStorage
from src.capture.capture_engine import CaptureEngine


class MockEvent:
    """Mock Ring API event."""
    def __init__(self, id, kind, device_name="Test Device", device_id="123456"):
        self.id = id
        self.kind = kind
        self.doorbot_id = device_id
        self.device_name = device_name


@pytest.fixture
def mock_auth_manager():
    """Create a mock auth manager."""
    mock = AsyncMock(spec=IAuthManager)
    mock.api = MagicMock()
    return mock


@pytest.fixture
def mock_event_listener():
    """Create a mock event listener."""
    mock = AsyncMock(spec=IEventListener)
    # Track the registered event types and callbacks
    mock.event_handlers = {}
    
    # Override the 'on' method to track registrations
    def mock_on(event_type, callback):
        mock.event_handlers[event_type] = callback
    
    mock.on = mock_on
    return mock


@pytest.fixture
def mock_capture_engine():
    """Create a mock capture engine."""
    return AsyncMock(spec=CaptureEngine)


@pytest.fixture
def app_manager(mock_auth_manager, mock_event_listener, mock_capture_engine):
    """Create an AppManager instance with mock components."""
    return AppManager(
        auth_manager=mock_auth_manager,
        event_listener=mock_event_listener,
        capture_engine=mock_capture_engine
    )


@pytest.mark.asyncio
async def test_initialize_registers_event_handlers(app_manager):
    """Test that initialize registers the correct event handlers."""
    # Mock out the authenticate method to avoid actual API calls
    app_manager._auth_manager.authenticate.return_value = None
    
    # Mock ring_devices and its attributes
    mock_devices = MagicMock()
    mock_devices.doorbots = []
    mock_devices.stickup_cams = []
    mock_devices.chimes = []
    
    # Mock the ring API's devices() method
    app_manager._auth_manager.api.devices.return_value = mock_devices
    
    # Call initialize
    await app_manager.initialize()
    
    # Check that the event handlers were registered
    event_listener = app_manager._event_listener
    assert "ding" in event_listener.event_handlers
    assert "motion" in event_listener.event_handlers
    assert "on_demand" in event_listener.event_handlers
    assert "other" in event_listener.event_handlers
    
    # Verify "all" is not registered to avoid duplicate processing
    assert "all" not in event_listener.event_handlers


@pytest.mark.asyncio
async def test_handle_ding_event(app_manager):
    """Test that ding events are handled correctly."""
    # Create a mock ding event
    mock_event = MockEvent(id="test-ding-123", kind="ding")
    
    # Call the handler
    await app_manager._handle_ding_event(mock_event)
    
    # Verify the capture_engine was called
    app_manager._capture_engine.capture.assert_called_once_with(mock_event)


@pytest.mark.asyncio
async def test_handle_motion_event(app_manager):
    """Test that motion events are handled correctly."""
    # Create a mock motion event
    mock_event = MockEvent(id="test-motion-123", kind="motion")
    
    # Call the handler
    await app_manager._handle_motion_event(mock_event)
    
    # Verify the capture_engine was called
    app_manager._capture_engine.capture.assert_called_once_with(mock_event)


@pytest.mark.asyncio
async def test_handle_on_demand_event(app_manager):
    """Test that on-demand events are handled correctly."""
    # Create a mock on-demand event
    mock_event = MockEvent(id="test-on-demand-123", kind="on_demand")
    
    # Call the handler
    await app_manager._handle_on_demand_event(mock_event)
    
    # Verify the capture_engine was called
    app_manager._capture_engine.capture.assert_called_once_with(mock_event)


@pytest.mark.asyncio
async def test_handle_other_event(app_manager):
    """Test that other event types are handled correctly."""
    # Create a mock event with an unrecognized type
    mock_event = MockEvent(id="test-other-123", kind="custom_event")
    
    # Call the handler
    await app_manager._handle_other_event(mock_event)
    
    # Verify the capture_engine was called
    app_manager._capture_engine.capture.assert_called_once_with(mock_event)


@pytest.mark.asyncio
async def test_event_dispatch_calls_correct_handler(app_manager, mock_event_listener):
    """Test that the event dispatcher calls the correct handler based on event type."""
    # Initialize the app manager to register the handlers
    app_manager._auth_manager.authenticate.return_value = None
    mock_devices = MagicMock()
    mock_devices.doorbots = []
    mock_devices.stickup_cams = []
    mock_devices.chimes = []
    app_manager._auth_manager.api.devices.return_value = mock_devices
    await app_manager.initialize()
    
    # Patch the specific event handlers
    with patch.object(app_manager, '_handle_ding_event') as mock_ding_handler, \
         patch.object(app_manager, '_handle_motion_event') as mock_motion_handler, \
         patch.object(app_manager, '_handle_on_demand_event') as mock_on_demand_handler, \
         patch.object(app_manager, '_handle_other_event') as mock_other_handler:
        
        # Get the registered handlers from the mock event listener
        ding_handler = mock_event_listener.event_handlers["ding"]
        motion_handler = mock_event_listener.event_handlers["motion"]
        on_demand_handler = mock_event_listener.event_handlers["on_demand"]
        other_handler = mock_event_listener.event_handlers["other"]
        
        # Create mock events of different types
        ding_event = MockEvent(id="test-ding-123", kind="ding")
        motion_event = MockEvent(id="test-motion-123", kind="motion")
        on_demand_event = MockEvent(id="test-on-demand-123", kind="on_demand")
        other_event = MockEvent(id="test-other-123", kind="custom_event")
        
        # Call the handlers directly (simulating event dispatch)
        await ding_handler(ding_event)
        await motion_handler(motion_event)
        await on_demand_handler(on_demand_event)
        await other_handler(other_event)
        
        # Verify that the correct handlers were called with the right events
        mock_ding_handler.assert_called_once_with(ding_event)
        mock_motion_handler.assert_called_once_with(motion_event)
        mock_on_demand_handler.assert_called_once_with(on_demand_event)
        mock_other_handler.assert_called_once_with(other_event)
