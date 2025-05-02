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
        
    async def save(self, event: EventData) -> None:
        """
        Save event data to the database.
        
        Args:
            event: Event data to save
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
            
    async def retrieve(self, event_id: str) -> Optional[EventData]:
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


class FileStorage(IStorage):
    """File-based storage implementation using fsspec."""
    
    def __init__(self, storage_path: str):
        """
        Initialize the FileStorage.
        
        Args:
            storage_path: Path for storing files
        """
        self._storage_path = storage_path
        # Ensure the storage path exists
        os.makedirs(storage_path, exist_ok=True)
        
    async def save(self, event: EventData) -> bool:
        """
        Save event data to a file.
        
        Args:
            event: Event data to save
            
        Returns:
            True if saved successfully, False otherwise
        """
        try:
            # Create a directory structure based on date
            date_str = datetime.now().strftime("%Y-%m-%d")
            event_dir = os.path.join(self._storage_path, date_str, event.kind)
            os.makedirs(event_dir, exist_ok=True)
            
            # Create a filename based on event ID and timestamp
            timestamp = datetime.now().strftime("%H%M%S")
            filename = f"{event.id}_{timestamp}.json"
            file_path = os.path.join(event_dir, filename)
            
            # Write the event data to the file
            with open(file_path, 'w') as f:
                # Use json.dumps instead of event.json() to avoid dumps_kwargs error
                f.write(json.dumps(event.dict(), indent=2))
                
            return True
        except Exception as e:
            print(f"Error saving event to file: {e}")
            return False
        
    async def retrieve(self, event_id: str) -> Optional[EventData]:
        """
        Retrieve event data from a file.
        
        Args:
            event_id: ID of the event to retrieve
            
        Returns:
            Event data if found, None otherwise
        """
        # Search for files with the event ID in the filename
        for root, _, files in os.walk(self._storage_path):
            for file in files:
                if file.startswith(f"{event_id}_") and file.endswith(".json"):
                    file_path = os.path.join(root, file)
                    try:
                        with open(file_path, 'r') as f:
                            event_data = json.load(f)
                            return EventData.parse_obj(event_data)
                    except (json.JSONDecodeError, TypeError) as e:
                        print(f"Error loading event from file {file_path}: {e}")
                    except Exception as e:
                        print(f"Error parsing event data from file {file_path}: {e}")
        
        return None
    
    async def close(self) -> None:
        """Close file storage and release resources."""
        # File storage doesn't need any special cleanup
        # This method is included for interface consistency
        pass


class NetworkStorage(IStorage):
    """Network-based storage implementation using fsspec."""
    
    def __init__(self, storage_url: str):
        """
        Initialize the NetworkStorage.
        
        Args:
            storage_url: URL for the storage (e.g., s3://bucket, sftp://host/path)
        """
        self._storage_url = storage_url
        self._fs = fsspec.filesystem(storage_url.split("://")[0])
        
    async def save(self, event: EventData) -> None:
        """
        Save event data to network storage.
        
        Args:
            event: Event data to save
        """
        # Create a directory structure based on date
        date_str = datetime.now().strftime("%Y-%m-%d")
        event_dir = f"{self._storage_url}/{date_str}/{event.kind}"
        
        # Ensure the directory exists
        self._fs.makedirs(event_dir, exist_ok=True)
        
        # Create a filename based on event ID and timestamp
        timestamp = datetime.now().strftime("%H%M%S")
        filename = f"{event.id}_{timestamp}.json"
        file_path = f"{event_dir}/{filename}"
        
        # Write the event data to the file
        with self._fs.open(file_path, 'w') as f:
            # Use json.dumps instead of event.json() to avoid dumps_kwargs error
            f.write(json.dumps(event.dict(), indent=2))
        
    async def retrieve(self, event_id: str) -> Optional[EventData]:
        """
        Retrieve event data from network storage.
        
        Args:
            event_id: ID of the event to retrieve
            
        Returns:
            Event data if found, None otherwise
        """
        # Search for files with the event ID in the filename
        pattern = f"{self._storage_url}/**/{event_id}_*.json"
        
        try:
            for file_path in self._fs.glob(pattern):
                try:
                    with self._fs.open(file_path, 'r') as f:
                        event_data = json.load(f)
                        return EventData.parse_obj(event_data)
                except (json.JSONDecodeError, TypeError) as e:
                    print(f"Error loading event from network file {file_path}: {e}")
                except Exception as e:
                    print(f"Error parsing event data from network file {file_path}: {e}")
        except Exception as e:
            print(f"Error searching for event {event_id} in network storage: {e}")
        
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
