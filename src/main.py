"""Main entry point for the Ring Doorbell Capture Application."""

import os
import sys
import asyncio
import logging
import signal
import structlog
import gc
import weakref
from pathlib import Path

# Add the project root to sys.path
project_root = str(Path(__file__).parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Import local modules with absolute imports
from src.auth.auth_manager import RingAuthManager
from src.api.event_listener import RingEventListener 
from src.storage.storage_impl import DatabaseStorage, FileStorage, NetworkStorage
from src.capture.capture_engine import CaptureEngine
from src.app.app_manager import AppManager
from src.utils.sleep_prevention import SleepMode
from src.config import Config as AppConfig


# Configure structured logging
import sys
from structlog.stdlib import LoggerFactory

# Set up the log file handler
log_file_path = Path(__file__).parent / "ring_doorbell.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(str(log_file_path))
    ]
)

# Configure structlog
shared_processors = [
    structlog.contextvars.merge_contextvars,
    structlog.processors.add_log_level,
    structlog.processors.TimeStamper(fmt="iso"),
]

structlog.configure(
    processors=shared_processors + [
        structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
    ],
    logger_factory=LoggerFactory(),
    cache_logger_on_first_use=True,
)

# Set up different renderers for console and file outputs
console_formatter = structlog.stdlib.ProcessorFormatter(
    processor=structlog.dev.ConsoleRenderer(),
    foreign_pre_chain=shared_processors,
)

file_formatter = structlog.stdlib.ProcessorFormatter(
    processor=structlog.processors.JSONRenderer(),
    foreign_pre_chain=shared_processors,
)

# Get console handler and apply formatter
console_handler = logging.getLogger().handlers[0]
console_handler.setFormatter(console_formatter)

# Get file handler and apply formatter
file_handler = logging.getLogger().handlers[1]
file_handler.setFormatter(file_formatter)

logger = structlog.get_logger()


def parse_arguments():
    """Parse command line arguments."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Ring Doorbell Capture Application")
    
    # Sleep mode options
    sleep_group = parser.add_argument_group("Sleep prevention options")
    sleep_group.add_argument(
        "--no-sleep-prevention", 
        action="store_false",
        dest="prevent_sleep",
        help="Disable sleep prevention entirely (default: enabled)"
    )
    
    sleep_group.add_argument(
        "--sleep-mode",
        type=str,
        choices=["all", "system", "disk", "none"],
        default="system",
        help=(
            "Sleep prevention mode: "
            "'all' prevents system, display and disk sleep; "
            "'system' prevents system sleep but allows display sleep; "
            "'disk' prevents only disk sleep; "
            "'none' same as --no-sleep-prevention (default: system)"
        )
    )
    
    args = parser.parse_args()
    
    # Convert sleep mode string to enum
    sleep_mode_map = {
        "all": SleepMode.PREVENT_ALL,
        "system": SleepMode.PREVENT_SYSTEM_ONLY,
        "disk": SleepMode.PREVENT_DISK_ONLY,
        "none": None  # Will be handled by prevent_sleep=False
    }
    
    # If sleep mode is none, ensure prevent_sleep is False
    if args.sleep_mode == "none":
        args.prevent_sleep = False
    
    return {
        "prevent_sleep": args.prevent_sleep,
        "sleep_mode": sleep_mode_map.get(args.sleep_mode, SleepMode.PREVENT_SYSTEM_ONLY)
    }


async def cleanup_aiohttp_resources():
    """Clean up any remaining aiohttp resources."""
    # Find and close any unclosed aiohttp client sessions
    try:
        import aiohttp
        import importlib
        import sys
        import gc
        
        # Force a garbage collection to ensure all objects are properly tracked
        gc.collect()
        
        # Try to access the internal _sessions list in aiohttp
        try:
            # In newer versions of aiohttp, access to internal resources may work differently
            if hasattr(aiohttp, '_sessions') and isinstance(aiohttp._sessions, set):
                for session in list(aiohttp._sessions):
                    if not session.closed:
                        print(f"Closing session from aiohttp._sessions: {session!r}")
                        await session.close()
        except (AttributeError, ImportError):
            pass  # Not available in this version
        
        # Get all objects in memory
        closed_sessions = 0
        closed_connectors = 0
        
        for obj in gc.get_objects():
            # Look for aiohttp client sessions
            if isinstance(obj, aiohttp.ClientSession):
                if not obj.closed:
                    try:
                        print(f"Closing unclosed aiohttp ClientSession: {obj!r}")
                        await obj.close()
                        closed_sessions += 1
                    except Exception as e:
                        print(f"Error closing aiohttp ClientSession: {e}")
            
            # Look for TCPConnector objects
            elif isinstance(obj, aiohttp.TCPConnector):
                if not obj.closed:
                    try:
                        print(f"Closing unclosed aiohttp TCPConnector: {obj!r}")
                        await obj.close()
                        closed_connectors += 1
                    except Exception as e:
                        print(f"Error closing aiohttp TCPConnector: {e}")
        
        print(f"Cleanup summary: closed {closed_sessions} sessions and {closed_connectors} connectors")
        
        # Allow asyncio to run briefly to finalize closures
        await asyncio.sleep(0.5)
        
    except Exception as e:
        print(f"Error during aiohttp cleanup: {e}")


async def main():
    """Main application function."""
    print("Starting main() function execution")
    logger.info("🔔 Ring Doorbell Capture Application")
    logger.info("-------------------------------------")
    
    # Application state
    shutdown_event = asyncio.Event()
    app_manager = None
    auth_manager = None
    
    # Initialize the application configuration
    config = AppConfig()
    
    # Create storage implementations
    storages = []
    
    # Database storage
    db_url = f"sqlite+aiosqlite:///{config.database_path}"
    storages.append(DatabaseStorage(db_url))
    
    # File storage
    storages.append(FileStorage(config.nas_storage_path))
    
    # Add network storage if configured
    if hasattr(config, 'network_storage_url') and config.network_storage_url:
        storages.append(NetworkStorage(config.network_storage_url))
    
    # Create the auth manager
    auth_manager = RingAuthManager(
        user_agent=config.user_agent,
        token_path=config.token_path,
        email=config.ring_email,
        password=config.ring_password,
        fcm_token_path=os.path.join(os.path.dirname(config.token_path), 'ring_fcm.cache')
    )
    
    # Setup signal handlers for graceful shutdown
    def signal_handler():
        logger.info("Signal received, initiating graceful shutdown...")
        shutdown_event.set()
    
    # Register signal handlers
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, signal_handler)
    
    try:
        # Initialize core components
        await auth_manager.authenticate()
        
        # Get the authenticated Ring API
        ring_api = auth_manager.api
        
        # Create the capture engine with the authenticated Ring API and auth manager
        capture_engine = CaptureEngine(storages, ring_api, auth_manager)
        
        # Create the event listener
        event_listener = RingEventListener(ring_api, auth_manager)
        
        # Use sleep prevention settings from config
        prevent_sleep = config.get('prevent_sleep', True)
        sleep_mode = config.get('sleep_mode', SleepMode.PREVENT_SYSTEM_ONLY)
        
        logger.info(f"Sleep prevention: {'Enabled' if prevent_sleep else 'Disabled'}")
        if prevent_sleep and sleep_mode:
            mode_name = str(sleep_mode).split('.')[-1]
            logger.info(f"Sleep mode: {mode_name}")
        
        # Create the application manager
        app_manager = AppManager(
            auth_manager, 
            event_listener, 
            capture_engine,
            prevent_sleep=prevent_sleep,
            sleep_mode=sleep_mode
        )
        
        # Initialize and start the application
        await app_manager.initialize()
        await app_manager.start()
        
        # Keep the application running until interrupted
        logger.info("Application running. Press Ctrl+C to stop...")
        await shutdown_event.wait()
            
    except Exception as e:
        logger.error(f"An error occurred: {e}")
        return 1
    finally:
        # Remove signal handlers
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.remove_signal_handler(sig)
        
        logger.info("Performing cleanup...")
        
        # Clean up application resources
        if app_manager:
            try:
                logger.info("Stopping application services...")
                await app_manager.stop()
                logger.info("Application services stopped")
            except Exception as e:
                logger.error(f"Error during application shutdown: {e}")
        
        # Close auth manager (which will close the Ring API session)
        if auth_manager:
            try:
                logger.info("Closing authentication session...")
                await auth_manager.close()
                logger.info("Authentication session closed")
            except Exception as e:
                logger.error(f"Error closing authentication session: {e}")
        
        # Clean up aiohttp resources
        await cleanup_aiohttp_resources()
        
        logger.info("Cleanup complete. Application stopped")
    
    return 0


if __name__ == "__main__":
    # Run with asyncio
    print("Script is being executed directly")
    
    # Use try/except to ensure clean exit even if asyncio.run fails
    try:
        # Parse command-line arguments
        args = parse_arguments()
        
        # Update config with parsed arguments
        AppConfig.update(args)
        
        exit_code = asyncio.run(main())
        sys.exit(exit_code or 0)
    except KeyboardInterrupt:
        print("\nShutdown requested by keyboard interrupt")
        # Don't re-raise to avoid long traceback
        sys.exit(130)  # Standard exit code for SIGINT
    except Exception as e:
        print(f"Unhandled exception: {e}")
        sys.exit(1)
