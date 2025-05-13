"""Application Manager for the Ring Doorbell application."""

import asyncio
import logging
import structlog
import platform
import subprocess
import os
import signal
from typing import Dict, List, Optional, Any, Tuple

from ..core.interfaces import IAuthManager, IEventListener, IStorage
from ..capture.capture_engine import CaptureEngine
from ..utils.sleep_prevention import SleepPrevention, SleepMode


# Configure structured logging
structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer()
    ],
    logger_factory=structlog.stdlib.LoggerFactory(),
)

logger = structlog.get_logger()


class AppManager:
    """Application Manager for bootstrapping and coordinating components."""
    
    def __init__(
        self,
        auth_manager: IAuthManager,
        event_listener: IEventListener,
        capture_engine: CaptureEngine,
        prevent_sleep: bool = True,
        sleep_mode: SleepMode = SleepMode.PREVENT_SYSTEM_ONLY
    ):
        """
        Initialize the AppManager.
        
        Args:
            auth_manager: Authentication manager for Ring API
            event_listener: Event listener for Ring events
            capture_engine: Engine for processing and storing events
            prevent_sleep: Whether to prevent system sleep while running
            sleep_mode: Sleep prevention mode to use (default: PREVENT_SYSTEM_ONLY - 
                        prevents system sleep but allows display sleep)
        """
        self._auth_manager = auth_manager
        self._event_listener = event_listener
        self._capture_engine = capture_engine
        self._running = False
        self._devices = {}
        self._prevent_sleep = prevent_sleep
        self._sleep_prevention = SleepPrevention(mode=sleep_mode) if prevent_sleep else None
    
    async def initialize(self) -> None:
        """
        Initialize the application.
        
        Raises:
            Exception: If initialization fails
        """
        logger.info("Initializing Ring Doorbell application")
        
        # Authenticate with the Ring API
        try:
            await self._auth_manager.authenticate()
        except Exception as e:
            logger.error(f"Authentication failed: {e}")
            raise
        
        # Get the authenticated API instance
        ring_api = self._auth_manager.api
        
        # Try to get and log the account ID
        try:
            account_id = await self._auth_manager.get_account_id()
            logger.info(f"Retrieved Ring account ID: {account_id}")
        except Exception as e:
            logger.warning(f"Failed to retrieve account ID: {e}")
            # Continue with initialization even if getting account ID fails
        
        # Get devices
        try:
            await ring_api.async_update_data()
            ring_devices = ring_api.devices()
            # Convert the devices to a dictionary for easier access
            self._devices = {
                "doorbots": ring_devices.doorbots,
                "stickup_cams": ring_devices.stickup_cams,
                "chimes": getattr(ring_devices, "chimes", []),
                "other": getattr(ring_devices, "other", [])
            }
            self._log_devices()
        except Exception as e:
            logger.error(f"Failed to get devices: {e}")
            raise
        
        # Wire up the event listener to the capture engine
        # Register different handlers for each event type
        self._event_listener.on("ding", self._handle_ding_event)
        self._event_listener.on("motion", self._handle_motion_event)
        self._event_listener.on("on_demand", self._handle_on_demand_event)
        
        # Add an "other" handler to catch any other event types
        self._event_listener.on("other", self._handle_other_event)
        
        # Note: We're not using the "all" handler to avoid duplicate processing
        
        logger.info("Ring Doorbell application initialized successfully")
    
    async def _handle_ding_event(self, event) -> None:
        """
        Handle doorbell ding events from the Ring API.
        
        Args:
            event: Ding event from the Ring API
        """
        event_id = getattr(event, 'id', 'unknown')
        device_name = getattr(event, 'device_name', 'unknown')
        
        logger.info(f"Received doorbell ding event - event_id: {event_id}, device: {device_name}")
            
        # Process and store the ding event
        # In the future, you can add ding-specific processing here
        await self._capture_engine.capture(event)
    
    async def _handle_motion_event(self, event) -> None:
        """
        Handle motion detection events from the Ring API.
        
        Args:
            event: Motion event from the Ring API
        """
        event_id = getattr(event, 'id', 'unknown')
        device_name = getattr(event, 'device_name', 'unknown')
        
        logger.info(f"Received motion detection event - event_id: {event_id}, device: {device_name}")
            
        # Process and store the motion event
        # In the future, you can add motion-specific processing here
        await self._capture_engine.capture(event)
    
    async def _handle_on_demand_event(self, event) -> None:
        """
        Handle on-demand (live view) events from the Ring API.
        
        Args:
            event: On-demand event from the Ring API
        """
        event_id = getattr(event, 'id', 'unknown')
        device_name = getattr(event, 'device_name', 'unknown')
        
        logger.info(f"Received on-demand (live view) event - event_id: {event_id}, device: {device_name}")
            
        # Process and store the on-demand event
        # In the future, you can add on-demand-specific processing here
        await self._capture_engine.capture(event)
    
    async def _handle_other_event(self, event) -> None:
        """
        Handle other event types from the Ring API.
        
        Args:
            event: Event from the Ring API with an unrecognized type
        """
        event_type = getattr(event, 'kind', 'unknown')
        event_id = getattr(event, 'id', 'unknown')
        device_name = getattr(event, 'device_name', 'unknown')
        
        logger.info(f"Received other event type: {event_type} - event_id: {event_id}, device: {device_name}")
            
        # Process and store the event
        await self._capture_engine.capture(event)
    
    async def _handle_event(self, event) -> None:
        """
        Handle events from the Ring API.
        
        Args:
            event: Event from the Ring API
        """
        # Log the event
        if hasattr(event, 'kind'):
            logger.info(f"Received event of type: {event.kind} - event_id: {getattr(event, 'id', 'unknown')}, device: {getattr(event, 'device_name', 'unknown')}")
        else:
            logger.info(f"Received unknown event type")
            
        # Process and store the event
        await self._capture_engine.capture(event)
    
    async def start(self) -> None:
        """
        Start the application.
        
        Raises:
            Exception: If starting fails
        """
        if self._running:
            logger.info("Application is already running")
            return
        
        logger.info("Starting Ring Doorbell application")
        
        # Start the event listener
        try:
            await self._event_listener.start()
            self._running = True
            
            # Start sleep prevention if enabled
            if self._sleep_prevention:
                if self._sleep_prevention.start():
                    mode_name = str(self._sleep_prevention.mode).split('.')[-1]
                    if self._sleep_prevention.mode == SleepMode.PREVENT_ALL:
                        logger.info(f"Sleep prevention activated with mode: {mode_name} - "
                                  f"system and display will not sleep")
                    elif self._sleep_prevention.mode == SleepMode.PREVENT_SYSTEM_ONLY:
                        logger.info(f"Sleep prevention activated with mode: {mode_name} - "
                                  f"system will not sleep but display can sleep to save power")
                    else:
                        logger.info(f"Sleep prevention activated with mode: {mode_name}")
                else:
                    logger.warning("Failed to activate sleep prevention - system may sleep")
            
            logger.info("Ring Doorbell application started successfully")
        except Exception as e:
            logger.error(f"Failed to start application: {e}")
            raise
    
    async def stop(self) -> None:
        """Stop the application."""
        if not self._running:
            logger.info("Application is not running")
            return
        
        logger.info("Stopping Ring Doorbell application")
        
        # Stop the event listener with timeout
        try:
            # Set a timeout for stopping the event listener
            async with asyncio.timeout(10):  # 10 second timeout
                await self._event_listener.stop()
                logger.info("Event listener stopped successfully")
        except asyncio.TimeoutError:
            logger.error("Timeout while stopping event listener - forcing shutdown")
        except Exception as e:
            logger.error(f"Error stopping event listener: {e}")
        
        # Clear any references that might prevent cleanup
        self._devices.clear()
        
        # Stop sleep prevention if active
        if self._sleep_prevention and self._sleep_prevention.is_active:
            await self._sleep_prevention.stop_async()
            logger.info("Sleep prevention deactivated - system can sleep normally")
        
        # Force garbage collection to help with resource cleanup
        try:
            import gc
            gc.collect()
        except Exception:
            pass
        
        self._running = False
        logger.info("Ring Doorbell application stopped")
    
    def _log_devices(self) -> None:
        """Log information about discovered Ring devices."""
        # Log doorbell devices
        if self._devices.get("doorbots"):
            for doorbell in self._devices["doorbots"]:
                logger.info(f"Found Ring doorbell - id: {doorbell.id}, name: {doorbell.name}, type: doorbell")
        
        # Log camera devices
        if self._devices.get("stickup_cams"):
            for camera in self._devices["stickup_cams"]:
                logger.info(f"Found Ring camera - id: {camera.id}, name: {camera.name}, type: camera")
        
        # Log chime devices
        if self._devices.get("chimes"):
            for chime in self._devices["chimes"]:
                logger.info(f"Found Ring chime - id: {chime.id}, name: {chime.name}, type: chime")
    
    def set_sleep_mode(self, mode: SleepMode) -> bool:
        """
        Change the sleep prevention mode dynamically.
        
        Args:
            mode: The new sleep prevention mode to use
            
        Returns:
            bool: True if the mode was changed successfully, False otherwise
        """
        if not self._sleep_prevention:
            logger.warning("Sleep prevention is disabled, cannot change mode")
            return False
            
        # If we're running, we need to restart sleep prevention
        was_active = self._sleep_prevention.is_active
        
        if was_active:
            self._sleep_prevention.stop()
            
        # Set the new mode
        self._sleep_prevention.set_mode(mode)
        logger.info(f"Sleep prevention mode changed to {str(mode).split('.')[-1]}")
        
        # If it was active, restart it
        result = True
        if was_active:
            result = self._sleep_prevention.start()
            if result:
                mode_name = str(mode).split('.')[-1]
                if mode == SleepMode.PREVENT_ALL:
                    logger.info(f"Sleep prevention restarted with mode: {mode_name} - "
                              f"system and display will not sleep")
                elif mode == SleepMode.PREVENT_SYSTEM_ONLY:
                    logger.info(f"Sleep prevention restarted with mode: {mode_name} - "
                              f"system will not sleep but display can sleep to save power")
                else:
                    logger.info(f"Sleep prevention restarted with mode: {mode_name}")
            else:
                logger.warning("Failed to restart sleep prevention after mode change")
                
        return result
    
    def get_sleep_mode(self) -> Optional[SleepMode]:
        """
        Get the current sleep prevention mode.
        
        Returns:
            Optional[SleepMode]: The current sleep mode, or None if sleep prevention is disabled
        """
        if not self._sleep_prevention:
            return None
            
        return self._sleep_prevention.mode
