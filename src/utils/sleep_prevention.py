"""Utility for preventing system sleep while the application is running."""

import logging
import platform
import subprocess
import os
import signal
import asyncio
from typing import Optional, Set
from enum import Enum, auto

logger = logging.getLogger(__name__)

class SleepMode(Enum):
    """Sleep prevention modes."""
    PREVENT_ALL = auto()        # Prevent idle, display, and disk sleep
    PREVENT_SYSTEM_ONLY = auto() # Prevent idle/system sleep but allow display sleep
    PREVENT_DISK_ONLY = auto()   # Prevent disk sleep only
    CUSTOM = auto()              # Custom configuration based on flags

class SleepPrevention:
    """
    Utility class for preventing system sleep on macOS and Linux platforms.
    
    This class can start and stop processes that prevent the system from
    sleeping while the Ring Doorbell application is running. It supports
    different sleep prevention modes, allowing for example to prevent system
    sleep but allow display sleep to conserve power.
    """
    
    def __init__(self, mode: SleepMode = SleepMode.PREVENT_SYSTEM_ONLY):
        """
        Initialize the sleep prevention utility.
        
        Args:
            mode: The sleep prevention mode to use
        """
        self._process = None
        self._platform = platform.system()
        self._active = False
        self._mode = mode
        self._custom_flags: Set[str] = set()
    
    @property
    def is_active(self) -> bool:
        """Return whether sleep prevention is active."""
        return self._active
    
    def set_mode(self, mode: SleepMode) -> None:
        """
        Set the sleep prevention mode.
        
        Args:
            mode: The sleep prevention mode to use
        """
        if self._active:
            logger.warning("Changing sleep mode while active - stopping current prevention")
            self.stop()
            
        self._mode = mode
    
    def set_custom_flags(self, flags: Set[str]) -> None:
        """
        Set custom flags for caffeinate (macOS) or systemd-inhibit (Linux).
        
        Args:
            flags: Set of flags to use (e.g., {"-i", "-m"} for macOS)
        """
        self._custom_flags = flags
        if self._mode != SleepMode.CUSTOM:
            logger.info("Setting custom flags automatically sets mode to CUSTOM")
            self._mode = SleepMode.CUSTOM
    
    def start(self) -> bool:
        """
        Start sleep prevention based on the configured mode.
        
        Returns:
            bool: True if successfully started, False otherwise
        """
        if self._active:
            return True
            
        result = False
        try:
            if self._platform == "Darwin":  # macOS
                # On macOS, use the caffeinate command-line utility
                # Flag definitions:
                # -i = prevent idle sleep (system sleep)
                # -d = prevent display sleep
                # -m = prevent disk sleep
                # -s = prevent system sleep (sleep on battery)
                
                # Determine flags based on mode
                flags = []
                if self._mode == SleepMode.PREVENT_ALL:
                    flags = ["-i", "-d", "-m", "-s"]
                elif self._mode == SleepMode.PREVENT_SYSTEM_ONLY:
                    flags = ["-i", "-s"]  # Prevent idle/system sleep but allow display sleep
                elif self._mode == SleepMode.PREVENT_DISK_ONLY:
                    flags = ["-m"]
                elif self._mode == SleepMode.CUSTOM and self._custom_flags:
                    flags = list(self._custom_flags)
                else:
                    # Default to system-only prevention if no valid option
                    flags = ["-i", "-s"]
                
                # Start caffeinate with the selected flags
                command = ["caffeinate"] + flags
                self._process = subprocess.Popen(
                    command,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
                logger.info(f"Caffeinate process started with flags {flags} (PID: {self._process.pid})")
                result = True
            elif self._platform == "Linux":
                # On Linux, we can use systemd-inhibit
                # Possible values for --what: sleep, idle, shutdown, handle-power-key,
                # handle-suspend-key, handle-hibernate-key, handle-lid-switch
                
                # Determine flags based on mode
                what_flags = ""
                if self._mode == SleepMode.PREVENT_ALL:
                    what_flags = "sleep:idle:handle-lid-switch"
                elif self._mode == SleepMode.PREVENT_SYSTEM_ONLY:
                    what_flags = "sleep:idle"  # Prevent system sleep but allow display sleep
                elif self._mode == SleepMode.PREVENT_DISK_ONLY:
                    what_flags = "idle"
                elif self._mode == SleepMode.CUSTOM and self._custom_flags:
                    # For Linux custom, we expect the full --what string
                    # e.g., "sleep:idle"
                    custom_what = next((f for f in self._custom_flags if f), "sleep:idle")
                    what_flags = custom_what
                else:
                    # Default to system-only prevention
                    what_flags = "sleep:idle"
                
                try:
                    self._process = subprocess.Popen(
                        ["systemd-inhibit", f"--what={what_flags}", "--who=RingDoorbell", 
                         "--why=Capturing video from Ring devices", "--mode=block", "sleep", "infinity"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL
                    )
                    logger.info(f"Sleep inhibit process started with flags '{what_flags}' (PID: {self._process.pid})")
                    result = True
                except (FileNotFoundError, subprocess.SubprocessError) as e:
                    logger.warning(f"Failed to start systemd-inhibit: {e}")
                    # Optional fallback if xdg-screensaver is available
                    try:
                        self._process = subprocess.Popen(
                            ["xdg-screensaver", "suspend", str(os.getpid())],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL
                        )
                        logger.info(f"xdg-screensaver suspend process started (PID: {self._process.pid})")
                        result = True
                    except (FileNotFoundError, subprocess.SubprocessError) as e:
                        logger.warning(f"Failed to start xdg-screensaver: {e}")
            else:
                logger.warning(f"Sleep prevention not supported on {self._platform}")
                
            self._active = result
            return result
        except Exception as e:
            logger.error(f"Error starting sleep prevention: {e}")
            return False
    
    def stop(self) -> None:
        """Stop sleep prevention."""
        if not self._active or not self._process:
            return
            
        try:
            # Terminate the process
            os.kill(self._process.pid, signal.SIGTERM)
            logger.info(f"Sleep prevention process (PID: {self._process.pid}) terminated")
        except Exception as e:
            logger.warning(f"Failed to terminate sleep prevention process: {e}")
        finally:
            self._process = None
            self._active = False
    
    async def stop_async(self) -> None:
        """Stop sleep prevention asynchronously."""
        self.stop()
        # Allow a moment for process to terminate
        await asyncio.sleep(0.1)
    
    @property
    def mode(self) -> SleepMode:
        """Get the current sleep prevention mode."""
        return self._mode
    
    def __str__(self) -> str:
        """Get a string representation of the sleep prevention status."""
        if not self._active:
            return "Sleep prevention: inactive"
            
        mode_str = str(self._mode).split('.')[-1]
        if self._platform == "Darwin":
            return f"Sleep prevention: active (macOS caffeinate, mode: {mode_str}, PID: {self._process.pid if self._process else 'None'})"
        elif self._platform == "Linux":
            return f"Sleep prevention: active (Linux {self._process.args[0] if self._process and hasattr(self._process, 'args') else 'inhibit'}, mode: {mode_str}, PID: {self._process.pid if self._process else 'None'})"
        else:
            return f"Sleep prevention: active (unsupported platform {self._platform})"
    
    @property
    def is_active(self) -> bool:
        """
        Check if sleep prevention is active.
        
        Returns:
            bool: True if active, False otherwise
        """
        return self._active
