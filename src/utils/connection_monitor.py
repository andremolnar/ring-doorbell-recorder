"""Network connection monitor for detecting sleep/wake events."""

import asyncio
import logging
import time
import platform
import socket
from typing import Callable, Optional, List

logger = logging.getLogger(__name__)

class ConnectionMonitor:
    """
    A utility class for monitoring network connection status.
    
    This class uses network connectivity checks to detect when a system
    has gone to sleep and woken up, or when network connectivity has been lost
    and restored.
    """
    
    # Default hosts to try pinging
    DEFAULT_HOSTS = [
        "8.8.8.8",       # Google DNS
        "1.1.1.1",       # Cloudflare DNS
        "208.67.222.222" # OpenDNS
    ]
    
    def __init__(self, 
                 check_interval: float = 15.0, 
                 hosts: Optional[List[str]] = None,
                 port: int = 53,  # DNS port
                 timeout: float = 3.0):
        """
        Initialize the connection monitor.
        
        Args:
            check_interval: Time in seconds between connectivity checks
            hosts: List of hosts to check for connectivity 
            port: Port to use for connection tests
            timeout: Connection timeout in seconds
        """
        self._check_interval = check_interval
        self._hosts = hosts or self.DEFAULT_HOSTS
        self._port = port
        self._timeout = timeout
        self._running = False
        self._task = None
        self._last_online = time.time()
        self._on_wake_callbacks = []
        self._on_sleep_callbacks = []
        
    async def start(self) -> None:
        """Start the connection monitoring."""
        if self._running:
            return
            
        self._running = True
        self._task = asyncio.create_task(self._monitor_loop())
        logger.info("Connection monitor started")
        
    async def stop(self) -> None:
        """Stop the connection monitoring."""
        if not self._running:
            return
            
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("Connection monitor stopped")
        
    def on_wake(self, callback: Callable) -> None:
        """
        Register a callback to be called when the system wakes from sleep.
        
        Args:
            callback: Async function to call when system wakes
        """
        self._on_wake_callbacks.append(callback)
        
    def on_sleep(self, callback: Callable) -> None:
        """
        Register a callback to be called when the system appears to go to sleep.
        
        Args:
            callback: Async function to call when system appears to sleep
        """
        self._on_sleep_callbacks.append(callback)
        
    async def _monitor_loop(self) -> None:
        """Main monitoring loop."""
        was_online = await self._check_connectivity()
        sleep_suspected = False
        
        while self._running:
            try:
                is_online = await self._check_connectivity()
                
                # Transition from offline to online - potential wake from sleep
                if not was_online and is_online:
                    # Calculate offline duration
                    offline_duration = time.time() - self._last_online
                    
                    # If offline for more than twice our check interval, likely a sleep/wake event
                    if offline_duration > (self._check_interval * 2) and sleep_suspected:
                        logger.info(f"System appears to have woken from sleep (offline for {offline_duration:.1f}s)")
                        await self._trigger_wake_callbacks()
                        sleep_suspected = False
                    else:
                        logger.info(f"Network connection restored after {offline_duration:.1f}s")
                
                # Transition from online to offline - potential sleep event
                elif was_online and not is_online:
                    self._last_online = time.time()
                    logger.info("Network connection lost - system may be going to sleep")
                    sleep_suspected = True
                    await self._trigger_sleep_callbacks()
                
                # Update state for next check
                was_online = is_online
                
                # If we're online, update the last_online timestamp
                if is_online:
                    self._last_online = time.time()
                
                # Wait for the next check
                await asyncio.sleep(self._check_interval)
                
            except asyncio.CancelledError:
                logger.debug("Connection monitor task cancelled")
                break
            except Exception as e:
                logger.error(f"Error in connection monitor: {e}")
                await asyncio.sleep(self._check_interval)
    
    async def _check_connectivity(self) -> bool:
        """
        Check if we have network connectivity.
        
        Returns:
            bool: True if network connectivity available, False otherwise
        """
        # Try each host in our list
        for host in self._hosts:
            try:
                # Create a socket
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(self._timeout)
                
                # Try to connect to the host
                result = sock.connect_ex((host, self._port))
                sock.close()
                
                # If connection was successful
                if result == 0:
                    return True
            except:
                # Catch any connection errors and try the next host
                continue
                
        return False
    
    async def _trigger_wake_callbacks(self) -> None:
        """Trigger all registered wake callbacks."""
        for callback in self._on_wake_callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback()
                else:
                    callback()
            except Exception as e:
                logger.error(f"Error in wake callback: {e}")
    
    async def _trigger_sleep_callbacks(self) -> None:
        """Trigger all registered sleep callbacks."""
        for callback in self._on_sleep_callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback()
                else:
                    callback()
            except Exception as e:
                logger.error(f"Error in sleep callback: {e}")
