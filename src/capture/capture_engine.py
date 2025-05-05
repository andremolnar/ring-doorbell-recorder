"""Capture Engine for processing Ring events."""

import logging
import time
import os
import aiohttp
import json
from datetime import datetime
from typing import Dict, List, Optional, Any, Callable, TypeVar, Type, Union, Tuple
from pathlib import Path

from pydantic import ValidationError
from ring_doorbell.event import RingEvent
from ring_doorbell import Ring

from ..core.interfaces import (
    EventData,
    DingEventData,
    MotionEventData, 
    OnDemandEventData,
    IStorage
)


# Configure structured logging
logger = logging.getLogger(__name__)


class CaptureEngine:
    """Engine for processing Ring events and storing them."""
    
    def __init__(self, storages: List[IStorage], ring_api: Optional[Ring] = None):
        """
        Initialize the CaptureEngine.
        
        Args:
            storages: List of storage implementations to use
            ring_api: Optional authenticated Ring API instance for direct API calls
        """
        self._storages = storages
        self._ring_api = ring_api
        self._event_types = {
            "ding": DingEventData,
            "motion": MotionEventData,
            "on_demand": OnDemandEventData
        }
    
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
                event_id = str(event.id) if hasattr(event, 'id') else "unknown-id"
                
                # For Ring event objects, also try to capture the video if available
                recording_id = getattr(event, 'recording_id', None)
                if recording_id:
                    await self._capture_video(event_id, event_type)
            else:
                event_type = event.get("kind", "unknown")
                device_info = event.get("doorbot", {})
                device_name = device_info.get("description", "Unknown Device")
                event_id = event.get("id", "unknown-id")
                
                # For dictionary events, try to find recording ID
                recording_id = event.get("recording", {}).get("id") if event.get("recording") else None
                if recording_id:
                    await self._capture_video(event_id, event_type)
            
            logger.info(f"Received event of type: {event_type}", 
                       extra={"device_name": device_name, "event_id": event_id})
            
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
                        logger.error(f"Failed to save event to storage: {e}", 
                                  extra={"event_id": processed_event.id, "storage": storage.__class__.__name__})
                
                processing_time = round((time.time() - start_time) * 1000)
                
                # Log appropriately based on what happened
                if success_count > 0:
                    logger.info(f"Event processed and stored successfully",
                              extra={
                                  "event_id": processed_event.id,
                                  "event_type": event_type,
                                  "processing_time_ms": processing_time,
                                  "storage_success_count": success_count
                              })
                elif already_exists_count > 0:
                    logger.info(f"Event already exists in storage",
                              extra={
                                  "event_id": processed_event.id,
                                  "event_type": event_type,
                                  "processing_time_ms": processing_time
                              })
            else:
                logger.warning(f"Event processing returned None, no data saved",
                             extra={"event_type": event_type, "device_name": device_name})
        except Exception as e:
            import traceback
            trace = traceback.format_exc()
            logger.error(f"Event processing failed: {e}",
                       extra={"event_type": event_type if 'event_type' in locals() else "unknown",
                             "error_details": str(e),
                             "traceback": trace})
    
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
                    "device_name": raw_event.device_name or "Unknown Device"
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
                    "device_name": device_info.get("description", "Unknown Device")
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
            
    async def _capture_video(self, event_id: str, event_type: str) -> Optional[Tuple[str, bytes]]:
        """
        Attempt to download and store a video associated with an event.
        
        Args:
            event_id: The ID of the event associated with the recording (also used as recording ID)
            event_type: The type of event (ding, motion, etc.)
            
        Returns:
            A tuple of (file_path, video_data) if successful, None otherwise
        """
        try:
            logger.info(f"Attempting to download video for event {event_id}")
            
            if not self._ring_api:
                logger.warning("No Ring API client available, cannot download video")
                return None
                
            # Find the device associated with this event through the Ring API
            # We need to find the device to use the API's recording download methods
            devices = self._ring_api.devices()
            
            # Try to find the right device
            target_device = None
            
            # First check doorbells and cameras
            for device in devices.doorbots + devices.stickup_cams:
                if str(event_id).startswith(str(device.id)):
                    target_device = device
                    break
            
            if not target_device:
                logger.warning(f"Could not find device for recording ID: {event_id}")
                
                # Try a different approach - get the recording URL directly
                try:
                    # Create a temporary file path
                    temp_path = os.path.join(
                        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                        "captured_media", 
                        f"temp_{event_id}.mp4"
                    )
                    
                    # Ensure the directory exists
                    os.makedirs(os.path.dirname(temp_path), exist_ok=True)
                    
                    # Get the recording URL using the event ID directly 
                    for device in devices.doorbots + devices.stickup_cams:
                        try:
                            # First check if we can get the recording URL
                            recording_url = await device.async_recording_url(event_id)
                            logger.info(f"Found recording URL: {recording_url}")
                            
                            if not recording_url:
                                logger.warning("No recording URL returned - likely due to missing subscription")
                                continue
                            
                            # Download the recording to a temporary file
                            success = await device.async_recording_download(
                                event_id, 
                                filename=temp_path,
                                override=True
                            )
                            
                            if success and os.path.exists(temp_path):
                                with open(temp_path, 'rb') as f:
                                    video_data = f.read()
                                    
                                # Clean up temporary file
                                try:
                                    os.remove(temp_path)
                                except:
                                    pass
                                    
                                logger.info(f"Successfully downloaded video for event {event_id} ({len(video_data)} bytes)")
                                
                                # Continue with storage
                                break
                        except Exception as e:
                            logger.debug(f"Error getting recording URL from device {device.name}: {e}")
                            continue
                    else:
                        logger.warning(f"Could not get recording URL for ID: {event_id}")
                        return None
                        
                except Exception as e:
                    logger.error(f"Error downloading recording: {e}")
                    return None
            else:
                # We found the device, use its methods to download the recording
                try:
                    # Create a temporary file path
                    temp_path = os.path.join(
                        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                        "captured_media", 
                        f"temp_{event_id}.mp4"
                    )
                    
                    # Ensure the directory exists
                    os.makedirs(os.path.dirname(temp_path), exist_ok=True)
                    
                    # Download the recording to a temporary file
                    success = await target_device.async_recording_download(
                        event_id, 
                        filename=temp_path,
                        override=True
                    )
                    
                    if not success or not os.path.exists(temp_path):
                        logger.warning(f"Failed to download recording {event_id}")
                        return None
                        
                    # Read the video data from the temporary file
                    with open(temp_path, 'rb') as f:
                        video_data = f.read()
                        
                    # Clean up temporary file
                    try:
                        os.remove(temp_path)
                    except:
                        pass
                        
                    logger.info(f"Successfully downloaded video for event {event_id} ({len(video_data)} bytes)")
                    
                except Exception as e:
                    logger.error(f"Error downloading recording: {e}")
                    return None
            
            # Store the video in all configured storages
            metadata = {
                "event_type": event_type,
                "recording_id": event_id,  # Use event_id as recording_id
                "extension": "mp4",  # Ring videos are MP4 format
                "download_date": datetime.now().isoformat()
            }
            
            # Try to save the video in all configured storages
            success_paths = []
            for storage in self._storages:
                try:
                    file_path = await storage.save_video(event_id, video_data, metadata)
                    if file_path:
                        success_paths.append(file_path)
                        
                        # Update the database to link the video with the event
                        if hasattr(storage, 'save_video_reference'):
                            await storage.save_video_reference(event_id, file_path, metadata)
                except Exception as e:
                    logger.error(f"Failed to save video to storage: {e}",
                                extra={"event_id": event_id, "storage": storage.__class__.__name__})
            
            if success_paths:
                logger.info(f"Video for event {event_id} saved successfully to {len(success_paths)} storage(s)")
                return (success_paths[0], video_data)
            else:
                logger.warning(f"Video for event {event_id} could not be saved to any storage")
                return None
                
        except Exception as e:
            logger.error(f"Unexpected error while capturing video for event {event_id}: {e}")
            import traceback
            logger.debug(traceback.format_exc())
            return None
            
    async def capture_latest_videos(self, device_id: str, limit: int = 5) -> List[str]:
        """
        Capture the latest videos for a specific device.
        
        Args:
            device_id: The ID of the device to capture videos for
            limit: Maximum number of videos to capture
            
        Returns:
            List of video paths that were successfully captured
        """
        # This is a placeholder for a real implementation that would:
        # 1. Query the Ring API for recent history
        # 2. Filter for events with the specified device ID
        # 3. Attempt to download videos for those events
        # 4. Return the paths to the saved videos
        
        # This would need a Ring API client reference that's not part of our current implementation
        logger.warning("capture_latest_videos not fully implemented - requires Ring API client")
        return []
        
    async def fetch_video_for_event(self, event_id: str, ring_api: Optional[Ring] = None) -> Optional[str]:
        """
        Fetch and store a video for a specific event.
        
        Args:
            event_id: The ID of the event to fetch video for (also used as recording ID)
            ring_api: Optional Ring API instance to use for this specific request
            
        Returns:
            Path to the saved video if successful, None otherwise
        """
        # Use provided Ring API if available
        original_ring_api = self._ring_api
        
        try:
            # Set the Ring API client if one was provided
            if ring_api:
                self._ring_api = ring_api
                
            # Ensure we have an API client
            if not self._ring_api:
                logger.warning("No Ring API client available for video download")
                return None
                
            # Since we don't know the event type, use a generic value
            result = await self._capture_video(event_id, "unknown")
            
            if result:
                return result[0]  # Return the path of the saved video
            return None
            
        except Exception as e:
            logger.error(f"Error in fetch_video_for_event: {e}")
            import traceback
            logger.debug(traceback.format_exc())
            return None
            
        finally:
            # Always restore the original Ring API
            self._ring_api = original_ring_api
