"""Storage implementations for the Ring Doorbell application."""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Union, Type

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.future import select
import fsspec

from ..core.interfaces import EventData, DingEventData, MotionEventData, OnDemandEventData, IStorage
from ..models.ring_events import RingEvent


class DatabaseStorage(IStorage):
    """SQLAlchemy-based database storage implementation."""
    
    def __init__(self, database_url: str):
        """
        Initialize the DatabaseStorage.
        
        Args:
            database_url: SQLAlchemy database URL
        """
        self._engine = create_async_engine(database_url)
        self._session_factory = sessionmaker(
            self._engine, 
            class_=AsyncSession, 
            expire_on_commit=False
        )
        
    async def save_event(self, event: EventData) -> bool:
        """
        Save event data to the database.
        
        Args:
            event: Event data to save
            
        Returns:
            True if saved successfully, False if already exists or failed
        """
        # Convert Pydantic model to dict
        event_dict = event.dict()
        
        # Extract standard fields and put the rest in event_data JSON
        standard_fields = {"id", "kind", "created_at", "device_id", "device_name"}
        event_data = {k: v for k, v in event_dict.items() if k not in standard_fields}
        
        async with self._session_factory() as session:
            try:
                # Use SQLAlchemy's merge instead of add to handle existing records gracefully
                # This performs an INSERT or UPDATE as needed
                db_event = RingEvent(
                    id=event.id,
                    kind=event.kind,
                    created_at=event.created_at,
                    device_id=event.device_id,
                    device_name=event.device_name,
                    event_data=json.dumps(event_data)
                )
                
                # Merge will update existing record or create new one
                db_event = await session.merge(db_event)
                
                # Commit changes
                await session.commit()
                return True  # Indicate success
            except sa.exc.IntegrityError as e:
                await session.rollback()
                if "UNIQUE constraint failed" in str(e):
                    # This is an expected case when processing duplicate events
                    # Log at debug level since this isn't an actual error
                    return False  # Indicate the event already exists
                else:
                    # Log other integrity errors as they might indicate real issues
                    print(f"Database integrity error saving event: {e}")
                    return False
            except Exception as e:
                await session.rollback()
                print(f"Error saving event to database: {e}")
                return False  # Indicate failure
            
    async def retrieve_event(self, event_id: str) -> Optional[EventData]:
        """
        Retrieve event data from the database.
        
        Args:
            event_id: ID of the event to retrieve
            
        Returns:
            Event data if found, None otherwise
        """
        async with self._session_factory() as session:
            # Query the database using SQLAlchemy
            query = select(RingEvent).where(RingEvent.id == event_id)
            result = await session.execute(query)
            db_event = result.scalar_one_or_none()
            
            if not db_event:
                return None
                
            # Combine standard fields with event_data JSON
            event_dict = {
                "id": db_event.id,
                "kind": db_event.kind,
                "created_at": db_event.created_at,
                "device_id": db_event.device_id,
                "device_name": db_event.device_name
            }
            
            # Parse the JSON event_data and merge with event_dict
            try:
                event_data = json.loads(db_event.event_data)
                event_dict.update(event_data)
            except (json.JSONDecodeError, TypeError):
                # Handle case where event_data is not valid JSON
                print(f"Warning: Could not parse event_data for event {event_id}")
            
            # Return appropriate EventData subclass based on kind
            event_classes = {
                "ding": DingEventData,
                "motion": MotionEventData,
                "on_demand": OnDemandEventData
            }
            event_class = event_classes.get(db_event.kind, EventData)
            return event_class.parse_obj(event_dict)

    async def close(self) -> None:
        """Close database connections and release resources."""
        if hasattr(self, '_engine') and self._engine is not None:
            try:
                await self._engine.dispose()
                print("✓ Database connections disposed successfully")
            except Exception as e:
                print(f"× Error disposing database connections: {e}")
                
    async def save_video(self, event_id: str, video_data: Union[bytes, str, Path], 
                         metadata: Optional[Dict] = None) -> str:
        """
        Save video reference in the database.
        
        Args:
            event_id: ID of the associated event
            video_data: For database storage, this should be a URL/path string where 
                        the video is stored (not the actual video bytes)
            metadata: Optional metadata about the video
            
        Returns:
            URL to access the stored video
        """
        if isinstance(video_data, bytes):
            raise ValueError("DatabaseStorage cannot store video bytes directly. Provide a URL/path string instead.")
        
        video_url = str(video_data)
        
        async with self._session_factory() as session:
            # Update the Ring event record to include video information
            stmt = (
                sa.update(RingEvent)
                .where(RingEvent.id == event_id)
                .values(
                    has_video=True,
                    video_url=video_url,
                    # Add metadata fields if provided
                    **({"recording_id": metadata.get("recording_id")} if metadata and "recording_id" in metadata else {})
                )
            )
            
            await session.execute(stmt)
            await session.commit()
            
            return video_url
    
    async def retrieve_video(self, event_id: str) -> Optional[str]:
        """
        Retrieve video URL for an event.
        
        Args:
            event_id: ID of the event associated with the video
            
        Returns:
            URL to the video if found, None otherwise
        """
        async with self._session_factory() as session:
            # Query the event to get the video URL
            query = select(RingEvent).where(RingEvent.id == event_id)
            result = await session.execute(query)
            event = result.scalar_one_or_none()
            
            if not event or not event.has_video or not event.video_url:
                return None
                
            return event.video_url

class FileStorage(IStorage):
    """File system-based storage implementation."""
    
    def __init__(self, storage_path: Union[str, Path]):
        """
        Initialize the FileStorage.
        
        Args:
            storage_path: Base path for storing event data
        """
        self._storage_path = str(storage_path)
        
    async def save_event(self, event: EventData) -> bool:
        """
        Save event data to the file system.
        
        Args:
            event: Event data to save
            
        Returns:
            True if saved successfully, False if already exists or failed
        """
        # Convert Pydantic model to dict
        event_dict = event.dict()
        
        # Extract standard fields and put the rest in event_data JSON
        standard_fields = {"id", "kind", "created_at", "device_id", "device_name"}
        event_data = {k: v for k, v in event_dict.items() if k not in standard_fields}
        
        # Create a directory for the event if it doesn't exist
        event_dir = os.path.join(self._storage_path, event.device_id, event.kind, event.id)
        os.makedirs(event_dir, exist_ok=True)
        
        # Save event metadata as JSON
        metadata_path = os.path.join(event_dir, "metadata.json")
        with open(metadata_path, 'w') as f:
            json.dump(event_data, f, default=str, indent=2)
           
        return True
            
    async def retrieve_event(self, event_id: str) -> Optional[EventData]:
        """
        Retrieve event data from the file system.
        
        Args:
            event_id: ID of the event to retrieve
            
        Returns:
            Event data if found, None otherwise
        """
        # For file storage, we will just read the metadata JSON directly
        metadata_path = os.path.join(self._storage_path, "**", event_id, "metadata.json")
        
        # Use fsspec to handle the glob pattern and read the file
        files = fsspec.open_files(metadata_path, recursive=True)
        for file in files:
            with file.open() as f:
                event_data = json.load(f)
                return EventData.parse_obj(event_data)
        
        return None

    async def close(self) -> None:
        """Close file storage and release resources."""
        # File storage doesn't need any special cleanup
        # This method is included for interface consistency
        pass
        
    async def save_video(self, event_id: str, video_data: Union[bytes, str, Path], 
                        metadata: Optional[Dict] = None) -> str:
        """
        Save video data to a file.
        
        Args:
            event_id: ID of the associated event
            video_data: Video content as bytes, or path to video file
            metadata: Optional metadata about the video
            
        Returns:
            Path to the saved video file
        """
        try:
            # Determine video extension (default to mp4 if not provided in metadata)
            video_ext = metadata.get("extension", "mp4") if metadata else "mp4"
            
            # Create a directory structure based on date and event type
            date_str = datetime.now().strftime("%Y-%m-%d")
            
            # Try to get the event type, default to "videos" if not found
            event_type = "videos"
            if metadata and "event_type" in metadata:
                event_type = metadata["event_type"]
            else:
                # Try to find the event to get its type
                event = await self.retrieve_event(event_id)
                if event:
                    event_type = event.kind
            
            video_dir = os.path.join(self._storage_path, date_str, event_type, "videos")
            os.makedirs(video_dir, exist_ok=True)
            
            # Create a filename based on event ID and timestamp
            timestamp = datetime.now().strftime("%H%M%S")
            filename = f"{event_id}_{timestamp}.{video_ext}"
            file_path = os.path.join(video_dir, filename)
            
            # Write the video data to the file
            if isinstance(video_data, (str, Path)) and os.path.isfile(video_data):
                # If video_data is a path to an existing file, copy it
                import shutil
                shutil.copy2(video_data, file_path)
            else:
                # Otherwise, write the bytes directly
                with open(file_path, 'wb') as f:
                    if isinstance(video_data, bytes):
                        f.write(video_data)
                    else:
                        # If it's a string but not a file path, treat it as base64 or other text format
                        f.write(str(video_data).encode('utf-8'))
            
            # If metadata is provided, save it alongside the video
            if metadata:
                metadata_path = f"{file_path}.meta.json"
                with open(metadata_path, 'w') as f:
                    json.dump(metadata, f, indent=2)
            
            return file_path
            
        except Exception as e:
            print(f"Error saving video to file: {e}")
            return ""
    
    async def retrieve_video(self, event_id: str) -> Optional[str]:
        """
        Retrieve video path for an event.
        
        Args:
            event_id: ID of the event associated with the video
            
        Returns:
            Path to the video file if found, None otherwise
        """
        # Search for video files with the event ID in the filename
        for root, _, files in os.walk(self._storage_path):
            for file in files:
                # Check if this is a video file (not metadata) with the event ID
                if file.startswith(f"{event_id}_") and not file.endswith(".meta.json"):
                    # Only return files with video extensions
                    video_exts = ['.mp4', '.avi', '.mov', '.mkv', '.webm']
                    if any(file.lower().endswith(ext) for ext in video_exts):
                        return os.path.join(root, file)
        
        return None

class NetworkStorage(IStorage):
    """Network-based storage implementation."""
    
    def __init__(self, storage_url: str, fs: Optional[fsspec.AbstractFileSystem] = None):
        """
        Initialize the NetworkStorage.
        
        Args:
            storage_url: Base URL for storing event data
            fs: Optional file system object for handling storage operations
        """
        self._storage_url = storage_url
        self._fs = fs or fsspec.filesystem('http')
        
    async def save_event(self, event: EventData) -> bool:
        """
        Save event data to network storage.
        
        Args:
            event: Event data to save
            
        Returns:
            True if saved successfully, False if already exists or failed
        """
        # Convert Pydantic model to dict
        event_dict = event.dict()
        
        # Extract standard fields and put the rest in event_data JSON
        standard_fields = {"id", "kind", "created_at", "device_id", "device_name"}
        event_data = {k: v for k, v in event_dict.items() if k not in standard_fields}
        
        # Create a directory for the event if it doesn't exist
        event_dir = f"{self._storage_url}/{event.device_id}/{event.kind}/{event.id}"
        self._fs.makedirs(event_dir, exist_ok=True)
        
        # Save event metadata as JSON
        metadata_path = f"{event_dir}/metadata.json"
        with self._fs.open(metadata_path, 'w') as f:
            f.write(json.dumps(event_data, default=str, indent=2))
                
        return True
            
    async def retrieve_event(self, event_id: str) -> Optional[EventData]:
        """
        Retrieve event data from network storage.
        
        Args:
            event_id: ID of the event to retrieve
            
        Returns:
            Event data if found, None otherwise
        """
        # For network storage, we will just read the metadata JSON directly
        metadata_path = f"{self._storage_url}/**/{event_id}/metadata.json"
        
        # Use fsspec to handle the glob pattern and read the file
        files = self._fs.glob(metadata_path)
        for file_path in files:
            with self._fs.open(file_path) as f:
                event_data = json.load(f)
                return EventData.parse_obj(event_data)
        
        return None

    async def close(self) -> None:
        """Close network connections and release resources."""
        if hasattr(self, '_fs') and self._fs is not None:
            try:
                # Close any open sessions or connections
                if hasattr(self._fs, 'close'):
                    self._fs.close()
                elif hasattr(self._fs, '_session') and self._fs._session is not None:
                    self._fs._session.close()
                print("✓ Network storage connections closed successfully")
            except Exception as e:
                print(f"× Error closing network storage connections: {e}")
                
    async def save_video(self, event_id: str, video_data: Union[bytes, str, Path], 
                        metadata: Optional[Dict] = None) -> str:
        """
        Save video data to network storage.
        
        Args:
            event_id: ID of the associated event
            video_data: Video content as bytes, or path to video file
            metadata: Optional metadata about the video
            
        Returns:
            URL to the saved video file
        """
        try:
            # Determine video extension (default to mp4 if not provided in metadata)
            video_ext = metadata.get("extension", "mp4") if metadata else "mp4"
            
            # Create a directory structure based on date and event type
            date_str = datetime.now().strftime("%Y-%m-%d")
            
            # Try to get the event type, default to "videos" if not found
            event_type = "videos"
            if metadata and "event_type" in metadata:
                event_type = metadata["event_type"]
            else:
                # Try to find the event to get its type
                event = await self.retrieve_event(event_id)
                if event:
                    event_type = event.kind
            
            video_dir = f"{self._storage_url}/{date_str}/{event_type}/videos"
            self._fs.makedirs(video_dir, exist_ok=True)
            
            # Create a filename based on event ID and timestamp
            timestamp = datetime.now().strftime("%H%M%S")
            filename = f"{event_id}_{timestamp}.{video_ext}"
            file_path = f"{video_dir}/{filename}"
            
            # Write the video data to the file
            if isinstance(video_data, (str, Path)) and os.path.isfile(str(video_data)):
                # If video_data is a path to an existing file, copy it
                with open(str(video_data), 'rb') as src, self._fs.open(file_path, 'wb') as dst:
                    dst.write(src.read())
            else:
                # Otherwise, write the bytes directly
                with self._fs.open(file_path, 'wb') as f:
                    if isinstance(video_data, bytes):
                        f.write(video_data)
                    else:
                        # If it's a string but not a file path, treat it as base64 or other text format
                        f.write(str(video_data).encode('utf-8'))
            
            # If metadata is provided, save it alongside the video
            if metadata:
                metadata_path = f"{file_path}.meta.json"
                with self._fs.open(metadata_path, 'w') as f:
                    f.write(json.dumps(metadata, indent=2))
            
            return file_path
            
        except Exception as e:
            print(f"Error saving video to network storage: {e}")
            return ""
    
    async def retrieve_video(self, event_id: str) -> Optional[str]:
        """
        Retrieve video URL for an event.
        
        Args:
            event_id: ID of the event associated with the video
            
        Returns:
            URL to the video file if found, None otherwise
        """
        # Search for video files with the event ID in the filename
        pattern = f"{self._storage_url}/**/{event_id}_*"
        
        try:
            for file_path in self._fs.glob(pattern):
                # Exclude metadata files
                if not file_path.endswith(".meta.json"):
                    # Check if this appears to be a video file
                    video_exts = ['.mp4', '.avi', '.mov', '.mkv', '.webm']
                    if any(file_path.lower().endswith(ext) for ext in video_exts):
                        return file_path
                        
        except Exception as e:
            print(f"Error searching for video {event_id} in network storage: {e}")
        
        return None
