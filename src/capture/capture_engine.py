"""Capture Engine for processing Ring events."""

import logging
import time
from datetime import datetime
from typing import Dict, List, Optional, Any, Callable, TypeVar, Type, Union

from pydantic import ValidationError
from ring_doorbell.event import RingEvent

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
    
    def __init__(self, storages: List[IStorage]):
        """
        Initialize the CaptureEngine.
        
        Args:
            storages: List of storage implementations to use
        """
        self._storages = storages
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
            else:
                event_type = event.get("kind", "unknown")
                device_info = event.get("doorbot", {})
                device_name = device_info.get("description", "Unknown Device")
                event_id = event.get("id", "unknown-id")
            
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
                        result = await storage.save(processed_event)
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
                
                # Base event data that's common to all event types
                event_data = {
                    "id": raw_event.get("id", f"unknown-{int(time.time())}"),
                    "kind": event_type,
                    "created_at": raw_event.get("created_at", datetime.now().isoformat()),
                    "device_id": device_info.get("id", "unknown"),
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
