"""Event Listener for Ring API events."""

import asyncio
import gc
from typing import Any, Callable, Dict, List, Optional
import json
import weakref

from pyee.asyncio import AsyncIOEventEmitter
from ring_doorbell import Ring
from ring_doorbell.listen.eventlistener import RingEventListener as RingApiEventListener

from ..core.interfaces import IEventListener
from ..auth.auth_manager import RingAuthManager


class RingEventListener(IEventListener):
    """Event Listener for Ring API events."""
    
    def __init__(self, ring_api: Ring, auth_manager: Optional[RingAuthManager] = None):
        """
        Initialize the RingEventListener.
        
        Args:
            ring_api: Authenticated Ring API instance
            auth_manager: Authentication manager instance for FCM credentials (optional)
        """
        self._ring = ring_api
        self._auth_manager = auth_manager
        self._event_listener = None
        self._emitter = AsyncIOEventEmitter()
        self._running = False
    
    def _credentials_updated_handler(self, updated_credentials: Dict[str, Any]) -> None:
        """
        Handle credentials update from the Ring API.
        
        Args:
            updated_credentials: Updated credentials dictionary
        """
        if self._auth_manager:
            # Use the auth manager to save the credentials
            self._auth_manager._save_fcm_credentials(updated_credentials)
        else:
            print("Warning: FCM credentials updated but no auth_manager to save them.")
        
        print("Ring event listener FCM credentials updated.")
    
    async def start(self) -> None:
        """
        Start listening for events.
        
        Raises:
            Exception: If starting the event listener fails
        """
        if self._running:
            print("Event listener is already running.")
            return
        
        try:
            # Initialize the RingApiEventListener with our Ring API instance
            # Get FCM credentials from auth_manager if available
            fcm_credentials = None
            credentials_callback = None
            
            if self._auth_manager:
                fcm_credentials = self._auth_manager.fcm_credentials
                credentials_callback = self._auth_manager.get_fcm_credentials_callback()
            else:
                # If no auth_manager is provided, use our local handler
                credentials_callback = self._credentials_updated_handler
            
            self._event_listener = RingApiEventListener(
                self._ring, 
                credentials=fcm_credentials, 
                credentials_updated_callback=credentials_callback
            )

            print("✓ Event listener created!")
            
            # Add our event dispatcher as a callback
            self._event_listener.add_notification_callback(self._dispatch_event)
            
            # Start the event listener
            await self._event_listener.start()
            self._running = True
            
            print("✓ Event listener started successfully!")
            print("🔔 Listening for Ring doorbell events...")
        except Exception as e:
            import traceback
            print(f"Exception details: {e}")
            print("Stack trace:")
            traceback.print_exc()
            self._running = False
            raise Exception(f"Failed to start event listener: {e}")
    
    async def stop(self) -> None:
        """Stop listening for events."""
        if not self._running:
            print("Event listener is not running.")
            return
        
        if self._event_listener:
            try:
                # Properly stop the event listener and wait for it to complete
                await self._event_listener.stop()
                
                # Clear callbacks to help with garbage collection
                if hasattr(self._event_listener, '_callbacks'):
                    self._event_listener._callbacks.clear()
                
                # Explicitly close any FCM client sessions if they exist
                await self._cleanup_fcm_resources()
                
                print("✓ Event listener stopped successfully.")
            except Exception as e:
                import traceback
                print(f"× Error stopping event listener: {e}")
                print("Stack trace:")
                traceback.print_exc()
            finally:
                self._event_listener = None
                self._running = False
        
        # Clear all event listeners
        self._emitter.remove_all_listeners()
    
    def on(self, event_type: str, callback) -> None:
        """
        Register callback for event type.
        
        Args:
            event_type: Type of event to listen for (e.g., 'ding', 'motion')
            callback: Async callback function to invoke
        """
        self._emitter.on(event_type, callback)
    
    def _dispatch_event(self, event) -> None:
        """
        Dispatch events to registered callbacks.
        
        Args:
            event: RingEvent object from the Ring API
        """
        try:
            # RingEvent has attributes like kind, id, etc. directly accessible as properties
            event_type = event.kind if hasattr(event, 'kind') else "unknown"
            device_name = event.device_name if hasattr(event, 'device_name') else "Unknown Device"
            event_id = event.id if hasattr(event, 'id') else "unknown-id"
            
            print(f"📩 Received {event_type} event from {device_name} (ID: {event_id})")
            
            # Emit the specific event type
            self._emitter.emit(event_type, event)
            
            # For events not in our standard types, also emit as "other"
            known_types = ["ding", "motion", "on_demand"]
            if event_type not in known_types:
                self._emitter.emit("other", event)
            
            # Also emit 'all' for listeners that want all events
            # self._emitter.emit('all', event)
        except Exception as e:
            import traceback
            print(f"× Error dispatching event: {e}")
            print("Stack trace:")
            traceback.print_exc()
    
    async def _cleanup_fcm_resources(self) -> None:
        """Clean up Firebase Cloud Messaging resources to prevent resource leaks."""
        try:
            if not self._event_listener:
                return
                
            # Get access to the internal FCM client
            fcm_client = None
            if hasattr(self._event_listener, '_receiver'):
                fcm_client = self._event_listener._receiver
            
            # Close FCM client session if it exists
            if fcm_client:
                if hasattr(fcm_client, '_session') and fcm_client._session and not fcm_client._session.closed:
                    try:
                        await fcm_client._session.close()
                    except Exception as e:
                        print(f"× Error closing FCM client session: {e}")
                
                # Clean up any other resources
                for attr_name in dir(fcm_client):
                    attr = getattr(fcm_client, attr_name)
                    # Check for aiohttp sessions or connectors
                    if attr_name.endswith('session') and hasattr(attr, 'closed') and not attr.closed:
                        try:
                            await attr.close()
                        except Exception as e:
                            print(f"× Error closing session {attr_name}: {e}")
        except Exception as e:
            print(f"× Error during FCM resource cleanup: {e}")
