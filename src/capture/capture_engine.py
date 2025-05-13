"""Capture Engine for processing Ring events."""

import logging
import time
import os
import json
import asyncio
from datetime import datetime
from typing import Dict, List, Optional, Any, Type, Union, Tuple

from pydantic import ValidationError
from ring_doorbell.event import RingEvent
from ring_doorbell import Ring
from pyee.asyncio import AsyncIOEventEmitter

from .live_view_client import LiveViewClient
from .video_sinks import RecorderSink, CVFanoutSink

from ..core.interfaces import (
    EventData,
    DingEventData,
    MotionEventData, 
    OnDemandEventData,
    IStorage,
    IAuthManager
)


# Configure structured logging
logger = logging.getLogger(__name__)


class CaptureEngine:
    """Engine for processing Ring events and storing them."""
    
    def __init__(self, storages: List[IStorage], ring_api: Optional[Ring] = None, auth_manager: Optional[IAuthManager] = None):
        """
        Initialize the CaptureEngine.
        
        Args:
            storages: List of storage implementations to use
            ring_api: Optional authenticated Ring API instance for direct API calls
            auth_manager: Optional authentication manager for token management
        """
        self._storages = storages
        self._ring_api = ring_api
        self._auth_manager = auth_manager
        self._event_types = {
            "ding": DingEventData,
            "motion": MotionEventData,
            "on_demand": OnDemandEventData
        }
        # Event bus for decoupling event handling
        self._event_bus = AsyncIOEventEmitter()
        
        # Register internal event handlers
        self._event_bus.on("ding", self._handle_ding_event)
        self._event_bus.on("motion", self._handle_motion_event)
        
        # Track active recording sessions to prevent duplicates
        self._active_recordings = {}
    
    async def capture(self, event: Union[Dict[str, Any], RingEvent]) -> None:
        """
        Process and store an event.
        
        Args:
            event: Event data from the Ring API (either a RingEvent object or raw dictionary)
        """
        start_time = time.time()
        
        try:
            # Determine the event type and get basic info for logging
            if isinstance(event, RingEvent):
                event_type = event.kind
                device_name = event.device_name if hasattr(event, 'device_name') else "Unknown Device"
                device_id = str(event.doorbot_id) if hasattr(event, 'doorbot_id') else None
                event_id = str(event.id) if hasattr(event, 'id') else "unknown-id"
            else:
                event_type = event.get("kind", "unknown")
                device_info = event.get("doorbot", {})
                device_name = device_info.get("description", "Unknown Device")
                device_id = str(device_info.get("id")) if device_info.get("id") else None
                event_id = event.get("id", "unknown-id")
            
            logger.info(f"Received event of type: {event_type} - device: {device_name}, event_id: {event_id}")
            
            # Map common fields
            processed_event = self._process_event(event)
            
            if processed_event:
                # Store the event in all configured storages
                success_count = 0
                already_exists_count = 0
                for storage in self._storages:
                    try:
                        result = await storage.save_event(processed_event)
                        if result is True:  # Successfully saved
                            success_count += 1
                        elif result is False:  # Already exists or other issue
                            already_exists_count += 1
                    except Exception as e:
                        logger.error(f"Failed to save event to storage: {e} - event_id: {processed_event.id}, storage: {storage.__class__.__name__}")
                
                processing_time = round((time.time() - start_time) * 1000)
                
                # Log appropriately based on what happened
                if success_count > 0:
                    logger.info(f"Event processed and stored successfully - event_id: {processed_event.id}, type: {event_type}, time: {processing_time}ms, storage_count: {success_count}")
                    
                    # Emit event to trigger appropriate handlers for video recording
                    if device_id:
                        event_data = {
                            "event": processed_event,
                            "device_id": device_id,
                            "device_name": device_name
                        }
                        self._event_bus.emit(event_type, event_data)
                        
                elif already_exists_count > 0:
                    logger.info(f"Event already exists in storage - event_id: {processed_event.id}, type: {event_type}, time: {processing_time}ms")
            else:
                logger.warning(f"Event processing returned None, no data saved - event_type: {event_type}, device: {device_name}")
        except Exception as e:
            import traceback
            trace = traceback.format_exc()
            logger.error(f"Event processing failed: {e} - event_type: {event_type if 'event_type' in locals() else 'unknown'}")
            logger.debug(f"Error details: {trace}")
    
    async def _handle_ding_event(self, event_data: Dict[str, Any]) -> None:
        """
        Handle doorbell ding event by starting video recording.
        
        Args:
            event_data: Event data including the processed event and device information
        """
        device_id = event_data.get("device_id")
        event = event_data.get("event")
        
        if not device_id or not event:
            logger.error("Missing device_id or event in ding event handler")
            return
        
        # Check if we're already recording for this device
        if device_id in self._active_recordings:
            logger.info(f"Recording already in progress for device {device_id}")
            return
            
        logger.info(f"Starting video recording for ding event {event.id} on device {device_id}")
        
        # Mark this device as actively recording
        self._active_recordings[device_id] = event.id
        
        try:
            # Start recording for 30 seconds
            # Note: It's critical to pass the event_id parameter here so the recording
            # callback knows which event to associate the video with
            await self.start_live_view(device_id, duration_sec=30, event_id=event.id)

        except Exception as e:
            logger.error(f"Error recording video for ding event: {e}")
        finally:
            # Remove from active recordings
            self._active_recordings.pop(device_id, None)
    
    async def _handle_motion_event(self, event_data: Dict[str, Any]) -> None:
        """
        Handle motion event by starting video recording.
        
        Args:
            event_data: Event data including the processed event and device information
        """
        device_id = event_data.get("device_id")
        event = event_data.get("event")
        
        if not device_id or not event:
            logger.error("Missing device_id or event in motion event handler")
            return
        
        # Check if we're already recording for this device
        if device_id in self._active_recordings:
            logger.info(f"Recording already in progress for device {device_id}")
            return
            
        logger.info(f"Starting video recording for motion event {event.id} on device {device_id}")
        
        # Mark this device as actively recording
        self._active_recordings[device_id] = event.id
        
        try:
            # Start recording for about 20 seconds (typical motion event duration)
            await self.start_live_view(device_id, duration_sec=20, event_id=event.id)
            
        except Exception as e:
            logger.error(f"Error recording video for motion event: {e}", exc_info=True)
        finally:
            # Remove from active recordings
            self._active_recordings.pop(device_id, None)
            
    def _process_event(self, raw_event: Union[Dict[str, Any], RingEvent]) -> Optional[EventData]:
        """
        Process a raw event into a structured EventData object.
        
        Args:
            raw_event: Event data from the Ring API (either a RingEvent object or raw dictionary)
            
        Returns:
            Processed EventData object or None if processing failed
        """
        try:
            # Handle both dictionary input and RingEvent objects
            if isinstance(raw_event, RingEvent):
                # Extract data from RingEvent object
                event_type = raw_event.kind
                event_data = {
                    "id": str(raw_event.id),
                    "kind": event_type,
                    "created_at": datetime.fromtimestamp(raw_event.now).isoformat(),
                    "device_id": str(raw_event.doorbot_id),
                    "device_name": raw_event.device_name or "Unknown Device",
                    "has_video": False  # Initialize video flag as False
                }
                
                # Add event-specific fields based on the kind
                if event_type == "ding":
                    event_data["answered"] = False  # Not available directly from RingEvent
                elif event_type == "motion":
                    event_data["motion_detection_score"] = None  # Not available directly
                elif event_type == "on_demand":
                    event_data["requester"] = None  # Not available directly
            else:
                # Original dictionary-based processing
                event_type = raw_event.get("kind", "unknown")
                device_info = raw_event.get("doorbot", {})
                
                # Ensure values are properly formatted for Pydantic validation
                event_id = raw_event.get("id", f"unknown-{int(time.time())}")
                # Convert ID to string if it's not already
                if not isinstance(event_id, str):
                    event_id = str(event_id)
                    
                # Handle both string and datetime created_at values
                created_at = raw_event.get("created_at", datetime.now())
                # Convert datetime to ISO format string if needed
                if isinstance(created_at, datetime):
                    created_at = created_at.isoformat()
                
                # Convert device ID to string if needed
                device_id = device_info.get("id", "unknown")
                if not isinstance(device_id, str):
                    device_id = str(device_id)
                
                # Base event data that's common to all event types
                event_data = {
                    "id": event_id,
                    "kind": event_type,
                    "created_at": created_at,
                    "device_id": device_id,
                    "device_name": device_info.get("description", "Unknown Device"),
                    "has_video": False  # Initialize video flag as False
                }
                
                # Add event-specific fields
                if event_type == "ding":
                    event_data["answered"] = raw_event.get("answered", False)
                elif event_type == "motion":
                    event_data["motion_detection_score"] = raw_event.get("cv_score", None)
                elif event_type == "on_demand":
                    event_data["requester"] = raw_event.get("requester", None)
            
            # Choose the appropriate event class based on the event type
            event_class = self._event_types.get(event_type, EventData)
            
            # Create and validate the event object
            return event_class(**event_data)
            
        except ValidationError as e:
            logger.error(f"Event validation failed: {e}")
            return None
        except Exception as e:
            logger.error(f"Event processing failed: {e}")
            return None
            
            
    async def start_live_view(self, device_id: str, duration_sec: Optional[int] = None, event_id: Optional[str] = None) -> Optional[str]:
        """
        Start a live WebRTC stream from a Ring device and save it to a file.
        
        Args:
            device_id: ID of the Ring device to stream from
            duration_sec: Optional override for the stream duration in seconds
            event_id: Optional event ID to associate with this recording
            
        Returns:
            Path to the saved video if successful, None otherwise
        """
        try:
            # First try to get token from auth_manager if available
            token = None
            if self._auth_manager:
                try:
                    # Get fresh token from auth_manager
                    token = self._auth_manager.get_token()
                    if not token:
                        logger.error("No valid token available from auth_manager")
                except Exception as e:
                    logger.error(f"Error getting token from auth_manager: {e}")
            
            # Fall back to ring_api if auth_manager is not available or failed
            if not token and self._ring_api:
                if hasattr(self._ring_api, 'auth') and hasattr(self._ring_api.auth, 'token'):
                    token = self._ring_api.auth.token.get("access_token")
                    logger.debug(f"Got token from ring_api: {token is not None}")
                    
                # Try alternate paths to get token if direct path failed
                if not token and hasattr(self._ring_api, 'token'):
                    if isinstance(self._ring_api.token, dict) and "access_token" in self._ring_api.token:
                        token = self._ring_api.token.get("access_token")
                        logger.debug(f"Got token from ring_api.token: {token is not None}")
                
            # Check if we have a valid token
            if not token:
                logger.error("Cannot access Ring API token")
                return None
                
            # Create target directory for the video
            timestamp = int(time.time())
            video_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                "captured_media",
                device_id,
                "live_view",
                f"{timestamp}.mp4"
            )
            os.makedirs(os.path.dirname(video_path), exist_ok=True)
            
            # Define callback for when recording completes
            def recording_completed(path, size):
                # Use asyncio.create_task to call the async method from a sync context
                logger.info(f"Recording callback triggered for {path} with size {size}, event_id: {event_id}")
                task = asyncio.create_task(self._handle_recording_completed(path, size, event_id, device_id))
                # Add a done callback to log any exceptions
                def on_done(task):
                    try:
                        task.result()  # This will raise any exception that occurred
                        logger.info(f"Recording completion task finished successfully")
                    except Exception as e:
                        logger.error(f"Error in recording completion task: {e}", exc_info=True)
                task.add_done_callback(on_done)
            
            # Create recorder sink with callback and live view client
            sink = RecorderSink(video_path, callback=recording_completed)
            
            # Pass auth_manager to LiveViewClient for token refreshing
            client = LiveViewClient(token, device_id, sink, auth_manager=self._auth_manager)
            
            # Modify max duration if requested
            if duration_sec is not None and isinstance(duration_sec, int):
                client.MAX_DURATION = min(590, duration_sec)  # Cap at 590 seconds
            
            # Start the client with retry logic handled inside LiveViewClient
            logger.info(f"Starting live view capture for device {device_id} with duration {duration_sec}s")
            success = await client.start()
            
            if not success:
                logger.error("LiveViewClient failed to start after all retry attempts")
                return None
            
            # Just return the path - we'll rely on the callback to handle the video
            # once it's actually done recording
            logger.info(f"Live view started successfully, video will be saved to {video_path}")
            return video_path
                
        except Exception as e:
            logger.error(f"Error in start_live_view: {e}")
            import traceback
            logger.debug(traceback.format_exc())
            return None
            
    
    
    async def _update_event_with_video_info(self, event_id: str, video_path: str) -> None:
        """
        Update an event record with video information.
        
        Args:
            event_id: ID of the event to update
            video_path: Path to the video file
        """
        # First, retrieve the event from storage
        event = None
        for storage in self._storages:
            try:
                event = await storage.retrieve_event(event_id)
                if event:
                    break
            except Exception as e:
                logger.error(f"Error retrieving event {event_id}: {e}")
                
        if not event:
            logger.warning(f"Could not find event {event_id} to update with video information")
            return
            
        # Get the device_id and event_type from the event
        device_id = event.device_id
        event_type = event.kind
        
        if not os.path.exists(video_path):
            logger.warning(f"Video file does not exist: {video_path}")
            return
            
        try:
            # Create a proper event-specific video path
            event_dir = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                "captured_media",
                device_id,
                event_type,
                event_id
            )
            
            # Create the directory if it doesn't exist
            os.makedirs(event_dir, exist_ok=True)
            
            # Create the destination path for the video
            event_video_path = os.path.join(event_dir, "video.mp4")
            
            # Copy the video file from the live_view directory to the event directory
            import shutil
            shutil.copy2(video_path, event_video_path)
            logger.info(f"Copied video from {video_path} to {event_video_path}")
            
            # Update the event with the new video path
            event_dict = event.dict()
            event_dict["has_video"] = True
            event_dict["video_path"] = event_video_path
            
            # Create the appropriate event type
        except Exception as e:
            logger.error(f"Error copying video file to event directory: {e}")
            # Still update the event with the original video path
            event_dict = event.dict()
            event_dict["has_video"] = True
            event_dict["video_path"] = video_path
        event_class = self._event_types.get(event_type, EventData)
        updated_event = event_class(**event_dict)
        
        # Save the updated event back to all storages
        for storage in self._storages:
            try:
                await storage.save_event(updated_event)
                logger.info(f"Updated event {event_id} with video information in {storage.__class__.__name__}")
            except Exception as e:
                logger.error(f"Error updating event with video info in {storage.__class__.__name__}: {e}")
    
    async def _handle_recording_completed(self, video_path: str, file_size: int, event_id: Optional[str], device_id: str) -> None:
        """
        Handle the completion of a video recording.
        
        Args:
            video_path: Path to the recorded video file
            file_size: Size of the video file in bytes
            event_id: Optional ID of the event associated with this recording
            device_id: ID of the device that recorded the video
        """
        logger.info(f"Recording completed: {video_path} ({file_size} bytes)")
        
        # Skip if the file is too small or doesn't exist
        if not os.path.exists(video_path):
            logger.warning(f"Video file doesn't exist: {video_path}")
            return
            
        if file_size < 1000:
            logger.warning(f"Video file is too small, ignoring: {video_path} ({file_size} bytes)")
            return
            
        # If we have an event ID, update the event with video information
        if event_id:
            logger.info(f"Updating event {event_id} with video information")
            
            # First, retrieve the event from storage to get its type
            event = None
            event_type = "motion"  # Default to motion
            
            for storage in self._storages:
                try:
                    event = await storage.retrieve_event(event_id)
                    if event:
                        event_type = event.kind
                        break
                except Exception as e:
                    logger.error(f"Error retrieving event {event_id}: {e}")
            
            if not event:
                logger.warning(f"Could not find event {event_id} in storage")
            
            # Create event directory
            event_dir = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                "captured_media",
                device_id,
                event_type,
                event_id
            )
            
            # Create the directory if it doesn't exist
            try:
                os.makedirs(event_dir, exist_ok=True)
                
                # Create the destination path for the video
                event_video_path = os.path.join(event_dir, "video.mp4")
                
                # Copy the video file from the live_view directory to the event directory
                import shutil
                shutil.copy2(video_path, event_video_path)
                logger.info(f"Copied video from {video_path} to {event_video_path}")
                
                # Update the event with video information
                if event:
                    # Create updated event object
                    event_dict = event.dict()
                    event_dict["has_video"] = True
                    event_dict["video_path"] = event_video_path
                    
                    # Get the appropriate event class
                    event_class = self._event_types.get(event_type, EventData)
                    updated_event = event_class(**event_dict)
                    
                    # Save the updated event to all storages
                    for storage in self._storages:
                        try:
                            await storage.save_event(updated_event)
                            logger.info(f"Updated event {event_id} with video information in {storage.__class__.__name__}")
                        except Exception as e:
                            logger.error(f"Error updating event with video info in {storage.__class__.__name__}: {e}")
                else:
                    # If we couldn't retrieve the event, at least create an event.json file
                    event_json_path = os.path.join(event_dir, "event.json")
                    event_data = {
                        "id": event_id,
                        "kind": event_type,
                        "created_at": datetime.now().isoformat(),
                        "device_id": device_id,
                        "has_video": True,
                        "video_path": event_video_path
                    }
                    
                    try:
                        with open(event_json_path, 'w') as f:
                            json.dump(event_data, f, default=str, indent=2)
                        logger.info(f"Created event.json for {event_id} with video information")
                    except Exception as e:
                        logger.error(f"Error creating event.json: {e}")
            except Exception as e:
                logger.error(f"Error copying video file to event directory: {e}", exc_info=True)
        else:
            # No event ID provided, create a generic timestamp-based ID
            timestamp = int(time.time())
            generic_id = f"live_view_{timestamp}_{device_id}"
            
            # Store video in all configured storages
            metadata = {
                "event_type": "live_view",
                "device_id": device_id,
                "extension": "mp4",
                "capture_date": datetime.now().isoformat()
            }
            
            # Store in all storages
            for storage in self._storages:
                try:
                    await storage.save_video(generic_id, video_path, metadata)
                    logger.info(f"Saved video to storage {storage.__class__.__name__}")
                except Exception as e:
                    logger.error(f"Error saving video to storage {storage.__class__.__name__}: {e}")
                    
        # Emit an event for the completed recording
        self._event_bus.emit("recording_completed", {
            "video_path": video_path,
            "file_size": file_size,
            "event_id": event_id,
            "device_id": device_id,
            "timestamp": int(time.time())
        })
