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
        # Convert the entire Pydantic model to dict, keeping all fields
        event_dict = event.dict()
        
        # Create a directory for the event if it doesn't exist
        event_dir = os.path.join(self._storage_path, event.device_id, event.kind, event.id)
        os.makedirs(event_dir, exist_ok=True)
        
        # Save complete event data as JSON
        event_path = os.path.join(event_dir, "event.json")
        with open(event_path, 'w') as f:
            json.dump(event_dict, f, default=str, indent=2)
           
        return True
            
    async def retrieve_event(self, event_id: str) -> Optional[EventData]:
        """
        Retrieve event data from the file system.
        
        Args:
            event_id: ID of the event to retrieve
            
        Returns:
            Event data if found, None otherwise
        """
        # Search for event.json files that match this event_id
        event_path = os.path.join(self._storage_path, "**", "**", event_id, "event.json")
        
        # Use fsspec to handle the glob pattern and read the file
        files = fsspec.open_files(event_path, recursive=True)
        for file in files:
            with file.open() as f:
                event_data = json.load(f)
                
                # Determine the correct event type model based on the kind field
                event_kind = event_data.get("kind", "")
                if event_kind == "ding":
                    return DingEventData.parse_obj(event_data)
                elif event_kind == "motion":
                    return MotionEventData.parse_obj(event_data)
                elif event_kind == "on_demand":
                    return OnDemandEventData.parse_obj(event_data)
                else:
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
            
            # Try to get the event to determine its path
            device_id = metadata.get("device_id") if metadata else None
            event_type = metadata.get("event_type") if metadata else None
            
            if not (device_id and event_type):
                # Try to find the event to get its device_id and kind
                event_path_pattern = os.path.join(self._storage_path, "**", "**", event_id, "event.json")
                files = fsspec.open_files(event_path_pattern, recursive=True)
                
                for file in files:
                    with file.open() as f:
                        try:
                            event_data = json.load(f)
                            device_id = event_data.get("device_id")
                            event_type = event_data.get("kind")
                            break
                        except json.JSONDecodeError:
                            continue
            
            # Create a directory structure based on device_id/event_type/event_id
            if device_id and event_type:
                video_dir = os.path.join(self._storage_path, device_id, event_type, event_id)
            else:
                # Fallback if we couldn't determine the path
                video_dir = os.path.join(self._storage_path, "unknown", "videos", event_id)
            
            os.makedirs(video_dir, exist_ok=True)
            
            # Create a filename for the video
            filename = f"video.{video_ext}"
            file_path = os.path.join(video_dir, filename)
            
            # Write the video data to the file
            if isinstance(video_data, (str, Path)) and os.path.isfile(str(video_data)):
                # If video_data is a path to an existing file, copy it
                with open(str(video_data), 'rb') as src, open(file_path, 'wb') as dst:
                    dst.write(src.read())
            else:
                # Otherwise, write the bytes directly
                with open(file_path, 'wb') as f:
                    if isinstance(video_data, bytes):
                        f.write(video_data)
                    else:
                        # If it's a string but not a file path, treat it as text
                        f.write(str(video_data).encode('utf-8'))
            
            # If metadata is provided, save it alongside the video
            if metadata:
                metadata_path = os.path.join(video_dir, "video_metadata.json")
                with open(metadata_path, 'w') as f:
                    json.dump(metadata, f, indent=2)
            
            # If we have a corresponding event JSON, update it to include video information
            event_json_path = os.path.join(video_dir, "event.json")
            if os.path.exists(event_json_path):
                with open(event_json_path, 'r') as f:
                    event_data = json.load(f)
                
                # Update the event data to include video information
                event_data["has_video"] = True
                event_data["video_path"] = file_path
                if metadata and "recording_id" in metadata:
                    event_data["recording_id"] = metadata["recording_id"]
                
                # Write the updated event data back to the file
                with open(event_json_path, 'w') as f:
                    json.dump(event_data, f, default=str, indent=2)
            
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
        try:
            # First, try to find the event to get its path
            event_path_pattern = os.path.join(self._storage_path, "**", "**", event_id, "event.json")
            files = fsspec.open_files(event_path_pattern, recursive=True)
            
            for file in files:
                try:
                    with file.open() as f:
                        event_data = json.load(f)
                        
                        # Check if the event has video information
                        if event_data.get("has_video") and event_data.get("video_path"):
                            return event_data["video_path"]
                except Exception:
                    continue
            
            # If no video path in event data, try to find a video file directly
            event_dir_pattern = os.path.join(self._storage_path, "**", "**", event_id)
            dirs = [d for d in fsspec.filesystem("file").glob(event_dir_pattern)]
            
            for event_dir in dirs:
                # Check for video files in the event directory
                for ext in ["mp4", "mkv", "mov", "avi"]:
                    video_path = os.path.join(event_dir, f"video.{ext}")
                    if os.path.exists(video_path):
                        return video_path
            
            return None
        except Exception as e:
            print(f"Error retrieving video: {e}")
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
        # Convert the entire Pydantic model to dict, keeping all fields
        event_dict = event.dict()
        
        # Create a directory for the event if it doesn't exist
        event_dir = f"{self._storage_url}/{event.device_id}/{event.kind}/{event.id}"
        self._fs.makedirs(event_dir, exist_ok=True)
        
        # Save complete event data as JSON
        event_path = f"{event_dir}/event.json"
        with self._fs.open(event_path, 'w') as f:
            f.write(json.dumps(event_dict, default=str, indent=2))
                
        return True
            
    async def retrieve_event(self, event_id: str) -> Optional[EventData]:
        """
        Retrieve event data from network storage.
        
        Args:
            event_id: ID of the event to retrieve
            
        Returns:
            Event data if found, None otherwise
        """
        # Search for event.json files that match this event_id
        event_path = f"{self._storage_url}/**/**/{event_id}/event.json"
        
        # Use fsspec to handle the glob pattern and read the file
        files = self._fs.glob(event_path)
        for file_path in files:
            with self._fs.open(file_path) as f:
                event_data = json.load(f)
                
                # Determine the correct event type model based on the kind field
                event_kind = event_data.get("kind", "")
                if event_kind == "ding":
                    return DingEventData.parse_obj(event_data)
                elif event_kind == "motion":
                    return MotionEventData.parse_obj(event_data)
                elif event_kind == "on_demand":
                    return OnDemandEventData.parse_obj(event_data)
                else:
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
            
            # Try to get the event to determine its path
            device_id = metadata.get("device_id") if metadata else None
            event_type = metadata.get("event_type") if metadata else None
            
            if not (device_id and event_type):
                # Try to find the event to get its device_id and kind
                event_path = f"{self._storage_url}/**/**/{event_id}/event.json"
                files = self._fs.glob(event_path)
                
                for file_path in files:
                    with self._fs.open(file_path) as f:
                        try:
                            event_data = json.load(f)
                            device_id = event_data.get("device_id")
                            event_type = event_data.get("kind")
                            break
                        except json.JSONDecodeError:
                            continue
            
            # Create a directory structure based on device_id/event_type/event_id
            if device_id and event_type:
                video_dir = f"{self._storage_url}/{device_id}/{event_type}/{event_id}"
            else:
                # Fallback if we couldn't determine the path
                video_dir = f"{self._storage_url}/unknown/videos/{event_id}"
            
            self._fs.makedirs(video_dir, exist_ok=True)
            
            # Create a filename for the video
            filename = f"video.{video_ext}"
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
                        # If it's a string but not a file path, treat it as text
                        f.write(str(video_data).encode('utf-8'))
            
            # If metadata is provided, save it alongside the video
            if metadata:
                metadata_path = f"{video_dir}/video_metadata.json"
                with self._fs.open(metadata_path, 'w') as f:
                    f.write(json.dumps(metadata, indent=2))
            
            # If we have a corresponding event JSON, update it to include video information
            event_json_path = f"{video_dir}/event.json"
            if self._fs.exists(event_json_path):
                with self._fs.open(event_json_path, 'r') as f:
                    event_data = json.load(f)
                
                # Update the event data to include video information
                event_data["has_video"] = True
                event_data["video_path"] = file_path
                if metadata and "recording_id" in metadata:
                    event_data["recording_id"] = metadata["recording_id"]
                
                # Write the updated event data back to the file
                with self._fs.open(event_json_path, 'w') as f:
                    f.write(json.dumps(event_data, default=str, indent=2))
            
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
        try:
            # First, try to find the event to get its path
            event_path = f"{self._storage_url}/**/**/{event_id}/event.json"
            files = self._fs.glob(event_path)
            
            for file_path in files:
                try:
                    with self._fs.open(file_path) as f:
                        event_data = json.load(f)
                        
                        # Check if the event has video information
                        if event_data.get("has_video") and event_data.get("video_path"):
                            return event_data["video_path"]
                except Exception:
                    continue
            
            # If no video path in event data, try to find a video file directly
            event_dir_pattern = f"{self._storage_url}/**/**/{event_id}"
            dirs = self._fs.glob(event_dir_pattern)
            
            for event_dir in dirs:
                # Check for video files in the event directory
                for ext in ["mp4", "mkv", "mov", "avi"]:
                    video_path = f"{event_dir}/video.{ext}"
                    if self._fs.exists(video_path):
                        return video_path
            
            return None
        except Exception as e:
            print(f"Error retrieving video: {e}")
            return None
