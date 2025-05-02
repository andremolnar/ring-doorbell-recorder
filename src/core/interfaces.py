"""Core interfaces for the Ring Doorbell application."""

import abc
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

from pydantic import BaseModel


class EventData(BaseModel):
    """Base model for Ring event data."""
    id: str
    kind: str
    created_at: str
    device_id: str
    device_name: str
    
    class Config:
        """Pydantic configuration."""
        extra = "allow"  # Allow extra fields


class DingEventData(EventData):
    """Model for doorbell ding events."""
    answered: bool


class MotionEventData(EventData):
    """Model for motion detection events."""
    motion_detection_score: Optional[float] = None


class OnDemandEventData(EventData):
    """Model for on-demand (live view) events."""
    requester: Optional[str] = None


@runtime_checkable
class IStorage(Protocol):
    """Interface for storage implementations."""
    
    async def save(self, event: EventData) -> bool:
        """
        Save event data to storage.
        
        Args:
            event: Event data to save
            
        Returns:
            True if saved successfully, False if already exists or failed
        """
        ...
    
    async def retrieve(self, event_id: str) -> Optional[EventData]:
        """
        Retrieve event data from storage.
        
        Args:
            event_id: ID of the event to retrieve
            
        Returns:
            Event data if found, None otherwise
        """
        ...


class IEventListener(abc.ABC):
    """Interface for event listeners."""
    
    @abc.abstractmethod
    async def start(self) -> None:
        """Start listening for events."""
        pass
    
    @abc.abstractmethod
    async def stop(self) -> None:
        """Stop listening for events."""
        pass
    
    @abc.abstractmethod
    def on(self, event_type: str, callback) -> None:
        """
        Register callback for event type.
        
        Args:
            event_type: Type of event to listen for
            callback: Callback function to invoke
        """
        pass


class IAuthManager(abc.ABC):
    """Interface for authentication managers."""
    
    @abc.abstractmethod
    async def authenticate(self) -> None:
        """Authenticate with the API."""
        pass
    
    @abc.abstractmethod
    async def is_authenticated(self) -> bool:
        """
        Check if the API is authenticated.
        
        Returns:
            True if authenticated, False otherwise
        """
        pass
    
    @property
    @abc.abstractmethod
    def api(self) -> Any:
        """
        Get the authenticated API instance.
        
        Returns:
            Authenticated API instance
        """
        pass
