import asyncio
import json
import datetime
import time
import sys
import os
import logging
from pathlib import Path
import shutil

# Set up basic logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Add the project root to sys.path
project_root = str(Path(__file__).parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from src.auth.auth_manager import RingAuthManager
from src.capture.capture_engine import CaptureEngine
from src.storage.storage_impl import FileStorage
from src.config import Config
from src.core.interfaces import EventData, MotionEventData


async def main():
    """Simulate a motion event and test video recording."""
    logger.info("Starting motion event simulation...")
    
    # Initialize the application configuration
    config = Config()
    
    # Create storage implementations
    storage_path = os.path.join(project_root, "captured_media")
    logger.info(f"Using storage path: {storage_path}")
    storage = FileStorage(storage_path)
    
    # Create the auth manager
    auth_manager = RingAuthManager(
        user_agent=config.user_agent,
        token_path=config.token_path,
        email=config.ring_email,
        password=config.ring_password,
        fcm_token_path=os.path.join(os.path.dirname(config.token_path), 'ring_fcm.cache')
    )
    
    # Create or use an existing event ID
    timestamp = int(time.time())
    event_id = f"test_motion_{timestamp}"
    device_id = "589851570"  # Replace with your actual device ID if different
    
    try:
        # Initialize auth
        logger.info("Authenticating...")
        await auth_manager.authenticate()
        
        # Get the authenticated Ring API
        ring_api = auth_manager.api
        logger.info("Ring API authenticated")
        
        # Verify token
        token = auth_manager.get_token()
        logger.info(f"Token available: {bool(token)}")
        if not token:
            logger.error("No token available, cannot continue")
            return
            
        # Print token information for debugging
        if token:
            import json
            try:
                logger.info(f"Token type: {type(token)}")
                if isinstance(token, dict):
                    logger.info(f"Token keys: {token.keys()}")
                elif isinstance(token, str):
                    logger.info(f"Token length: {len(token)}")
                else:
                    logger.info(f"Token representation: {repr(token)}")
            except Exception as e:
                logger.error(f"Error inspecting token: {e}")
        
        # Create the capture engine with explicit auth_manager
        logger.info("Creating capture engine")
        capture_engine = CaptureEngine([storage], ring_api, auth_manager=auth_manager)
        
        # Create a simulated motion event
        # Create mock event data
        event_data = {
            "id": event_id,
            "kind": "motion",
            "created_at": datetime.datetime.now().isoformat(),
            "doorbot": {
                "id": device_id,
                "description": "Front Door"
            },
            "cv_score": 0.9
        }
        
        # First, explicitly create and save the event in storage
        logger.info(f"Creating motion event with ID: {event_id}")
        event_obj = MotionEventData(
            id=event_id,
            kind="motion",
            created_at=datetime.datetime.now().isoformat(),
            device_id=device_id,
            device_name="Front Door",
            has_video=False
        )
        await storage.save_event(event_obj)
        
        # Verify the event was saved
        saved_event = await storage.retrieve_event(event_id)
        if saved_event:
            logger.info(f"Event saved successfully: {saved_event}")
        else:
            logger.error("Failed to save event")
            return
        
        logger.info(f"Simulating motion event with ID: {event_id}")
        
        # Process the event
        await capture_engine.capture(event_data)
        
        # Wait for recording to be in progress
        logger.info("Waiting 5 seconds for recording to start...")
        await asyncio.sleep(5)
        
        # Check if the live_view directory exists
        live_view_dir = os.path.join(storage_path, device_id, "live_view")
        if os.path.exists(live_view_dir):
            files = os.listdir(live_view_dir)
            mp4_files = [f for f in files if f.endswith(".mp4")]
            if mp4_files:
                # Get the most recent MP4 file
                mp4_files.sort(key=lambda f: os.path.getmtime(os.path.join(live_view_dir, f)), reverse=True)
                latest_mp4 = mp4_files[0]
                latest_path = os.path.join(live_view_dir, latest_mp4)
                file_size = os.path.getsize(latest_path)
                logger.info(f"Found MP4 file in live_view directory: {latest_mp4}, size: {file_size} bytes")
            else:
                logger.warning("No MP4 files found in live_view directory")
        else:
            logger.warning(f"Live view directory not found: {live_view_dir}")
        
        # Wait for recording and processing to complete
        logger.info("Waiting 30 seconds for recording and processing to complete...")
        await asyncio.sleep(30)
        
        # Check if video was created in the event directory
        logger.info("Checking for recorded video in the event directory...")
        
        # Path pattern where the video should be stored
        video_path_base = os.path.join(storage_path, device_id, "motion", event_id)
        
        if os.path.exists(video_path_base):
            files = os.listdir(video_path_base)
            logger.info(f"Event directory contents: {files}")
            
            video_files = [f for f in files if f.endswith(".mp4")]
            if video_files:
                video_path = os.path.join(video_path_base, video_files[0])
                file_size = os.path.getsize(video_path)
                logger.info(f"✅ Video recorded successfully: {video_path}, size: {file_size} bytes")
                
                # Check if the event was updated with video information
                event = await storage.retrieve_event(event_id)
                if event and event.has_video:
                    logger.info(f"✅ Event has video information: {event}")
                else:
                    logger.warning(f"❌ Event not updated with video information: {event}")
            else:
                logger.warning(f"❌ No video file found in {video_path_base}")
                logger.info(f"Directory contents: {files}")
                
                # Check the live_view directory again
                if os.path.exists(live_view_dir):
                    files = os.listdir(live_view_dir)
                    mp4_files = [f for f in files if f.endswith(".mp4")]
                    if mp4_files:
                        # Get the most recent MP4 file
                        mp4_files.sort(key=lambda f: os.path.getmtime(os.path.join(live_view_dir, f)), reverse=True)
                        latest_mp4 = mp4_files[0]
                        latest_path = os.path.join(live_view_dir, latest_mp4)
                        file_size = os.path.getsize(latest_path)
                        logger.info(f"Video is in live_view but not moved to event directory: {latest_path}, size: {file_size} bytes")
                
                # Check if the event was saved properly
                event = await storage.retrieve_event(event_id)
                if event:
                    logger.info(f"Event was saved: {event}")
                else:
                    logger.warning("Event was not found in storage")
        else:
            logger.warning(f"❌ Event directory not found: {video_path_base}")
            
            # Check the live_view directory again
            if os.path.exists(live_view_dir):
                files = os.listdir(live_view_dir)
                mp4_files = [f for f in files if f.endswith(".mp4")]
                if mp4_files:
                    # Get the most recent MP4 file
                    mp4_files.sort(key=lambda f: os.path.getmtime(os.path.join(live_view_dir, f)), reverse=True)
                    latest_mp4 = mp4_files[0]
                    latest_path = os.path.join(live_view_dir, latest_mp4)
                    file_size = os.path.getsize(latest_path)
                    logger.info(f"Video is in live_view but event directory not created: {latest_path}, size: {file_size} bytes")
                    
                    # Let's try to manually copy it
                    try:
                        # Create event directory
                        os.makedirs(video_path_base, exist_ok=True)
                        dest_path = os.path.join(video_path_base, "video.mp4")
                        
                        # Copy the file
                        shutil.copy2(latest_path, dest_path)
                        logger.info(f"✅ Manually copied video to event directory: {dest_path}")
                        
                        # Update the event with video information
                        event = await storage.retrieve_event(event_id)
                        if event:
                            # Create updated event object
                            event_dict = event.dict()
                            event_dict["has_video"] = True
                            event_dict["video_path"] = dest_path
                            
                            updated_event = MotionEventData(**event_dict)
                            
                            # Save the updated event
                            await storage.save_event(updated_event)
                            logger.info(f"✅ Manually updated event with video information")
                    except Exception as e:
                        logger.error(f"Error manually copying video: {e}")
            
    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
    finally:
        # Clean up
        if auth_manager:
            await auth_manager.close()
        
        if storage:
            await storage.close()
            
        logger.info("Test completed.")


if __name__ == "__main__":
    asyncio.run(main())
