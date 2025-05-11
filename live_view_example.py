#!/usr/bin/env python
"""
Example script to demonstrate live view capture using WebRTC.

This script shows how to use the LiveViewClient and RecorderSink
to capture a live stream from a Ring doorbell or camera.
"""

import asyncio
import argparse
import logging
import os
import sys
import time
from datetime import datetime

# Add the package to the path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '.')))

from src.auth.auth_manager import RingAuthManager
from src.capture.capture_engine import CaptureEngine
from src.storage.storage_impl import FileStorage
from src.capture.live_view_client import LiveViewClient
from src.capture.video_sinks import RecorderSink

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger("ring-live-view")

async def main():
    """Run the example live view capture."""
    parser = argparse.ArgumentParser(description="Capture a live view from a Ring device using WebRTC.")
    parser.add_argument("--device-id", "-d", help="Ring device ID to stream from", required=True)
    parser.add_argument("--duration", "-t", type=int, default=30, 
                      help="Duration of the stream in seconds (default: 30)")
    parser.add_argument("--output-dir", "-o", default="captured_media",
                      help="Directory to save the captured video (default: captured_media)")
    args = parser.parse_args()
    
    # Initialize auth manager - use project root for token
    project_root = os.path.dirname(os.path.abspath(__file__))
    token_path = os.path.join(project_root, "ring_token.cache")
    auth_manager = RingAuthManager(
        user_agent="RingDoorbell/LiveView",
        token_path=token_path
    )
    
    try:
        # Authenticate with Ring
        logger.info("Authenticating with Ring...")
        await auth_manager.authenticate()
        
        # Initialize storage
        output_dir = os.path.join(args.output_dir, "live_view")
        os.makedirs(output_dir, exist_ok=True)
        storage = FileStorage(storage_path=output_dir)
        
        # Initialize capture engine with storage
        capture_engine = CaptureEngine([storage], auth_manager.api)
        
        # Get list of available devices
        ring_api = auth_manager.api
        await ring_api.async_update_data()
        devices = ring_api.devices()
        
        # List available devices if none specified
        if args.device_id.lower() == "list":
            logger.info("Available Ring devices:")
            for device in devices.doorbots + devices.stickup_cams:
                logger.info(f"ID: {device.id} - Name: {device.name} - Kind: {device.kind}")
            return
        
        # Start live view
        logger.info(f"Starting live view for device {args.device_id} for {args.duration} seconds...")
        
        # Get the token directly from the auth manager to make the Live View connection
        token = auth_manager.get_token()
        if not token:
            logger.error("Failed to get authentication token")
            return
            
        # Debug token information
        logger.info(f"Token type: {type(token)}")
        logger.info(f"Token length: {len(token) if token else 0}")
        if token:
            logger.info(f"Token prefix: {token[:20]}...")
            
        # Create recorder sink
        timestamp = int(time.time())
        video_path = os.path.join(args.output_dir, f"{timestamp}.mp4")
        os.makedirs(os.path.dirname(video_path), exist_ok=True)
        
        # Create sink and client
        sink = RecorderSink(video_path)
        client = LiveViewClient(token, args.device_id, sink, auth_manager=auth_manager)
        
        # Set duration
        if args.duration:
            client.MAX_DURATION = min(590, args.duration)
            
        # Start client
        try:
            logger.info("Starting live view connection, this might take a moment...")
            success = await client.start()
            
            if success:
                logger.info(f"Capturing live view for {args.duration} seconds...")
                try:
                    # Wait for the specified duration with better cancellation handling
                    remaining = args.duration
                    while remaining > 0:
                        # Sleep in smaller chunks to be more responsive to cancellation
                        sleep_time = min(1, remaining)
                        await asyncio.sleep(sleep_time)
                        remaining -= sleep_time
                        
                        # Check if we've received any frames (for user feedback)
                        if hasattr(sink, 'frame_count') and sink.frame_count > 0 and sink.frame_count % 60 == 0:
                            logger.info(f"Received {sink.frame_count} frames so far. Remaining time: {remaining}s")
                            
                except asyncio.CancelledError:
                    logger.info("Capture was canceled by user")
                finally:
                    # Stop the client explicitly
                    logger.info("Stopping live view client...")
                    await client.stop()
                    
                    # Give the file a moment to close and flush
                    await asyncio.sleep(1)
                
            # Verify the recording was successful
            if os.path.exists(video_path):
                file_size = os.path.getsize(video_path)
                if file_size > 10000:  # 10KB minimum for a valid video
                    logger.info(f"✅ Live view captured successfully to {video_path}")
                    logger.info(f"   File size: {file_size / 1024:.1f} KB ({sink.frame_count} frames)")
                    return video_path
                else:
                    logger.error(f"❌ Video file is too small: {file_size} bytes")
            else:
                logger.error("❌ Failed to capture live view - file not found")
        except Exception as e:
            logger.error(f"Error during live view capture: {e}")
            import traceback
            logger.debug(traceback.format_exc())
        
    except Exception as e:
        logger.error(f"Error: {e}")
        import traceback
        logger.debug(traceback.format_exc())
    finally:
        # Ensure cleanup
        await auth_manager.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Process interrupted by user")
        sys.exit(0)
