"""Core interfaces for the Ring Doorbell application."""

import abc
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable, Union

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
    
    async def save_event(self, event: EventData) -> bool:
        """
        Save event data to storage.
        
        Args:
            event: Event data to save
            
        Returns:
            True if saved successfully, False if already exists or failed
        """
        ...
    
    async def retrieve_event(self, event_id: str) -> Optional[EventData]:
        """
        Retrieve event data from storage.
        
        Args:
            event_id: ID of the event to retrieve
            
        Returns:
            Event data if found, None otherwise
        """
        ...
    
    async def save_video(self, event_id: str, video_data: Union[bytes, str, Path], 
                         metadata: Optional[Dict] = None) -> str:
        """
        Save video data associated with an event.
        
        Args:
            event_id: ID of the associated event
            video_data: Video content as bytes, or path to video file as string or Path
            metadata: Optional metadata about the video (format, duration, etc.)
            
        Returns:
            Video identifier or URL to access the stored video
        """
        ...
    
    async def retrieve_video(self, event_id: str) -> Optional[Union[bytes, str]]:
        """
        Retrieve video data for an event.
        
        Args:
            event_id: ID of the event associated with the video
            
        Returns:
            Video data as bytes or a path/URL to the video, None if not found
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
