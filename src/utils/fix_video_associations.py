"""
Script for manually fixing the association between motion events and recorded videos.

This script:
1. Searches for motion events that don't have videos associated with them
2. Looks for videos in the live_view directory that match the timestamp
3. Copies those videos to the appropriate event directory
4. Updates the event.json file with the video information
"""

import asyncio
import argparse
import os
import glob
import json
import shutil
import logging
from datetime import datetime, timedelta
from pathlib import Path
import sys

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Add project root to sys.path
project_root = str(Path(__file__).parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from src.storage.storage_impl import FileStorage


async def find_unassociated_events(storage_path, since=None, until=None, device_id=None):
    """
    Find events without associated videos.
    
    Args:
        storage_path: Path to the storage directory
        since: Only look for events after this datetime
        until: Only look for events before this datetime
        device_id: Only look for events from this device
        
    Returns:
        List of dicts containing event info
    """
    logger.info(f"Looking for events without videos in {storage_path}")
    
    # Initialize storage
    storage = FileStorage(storage_path)
    
    # Get all events
    events = await storage.list_events()
    logger.info(f"Found {len(events)} total events")
    
    # Filter events without videos
    events_without_videos = []
    for event in events:
        # Apply filters
        if device_id and event.device_id != device_id:
            continue
            
        event_time = datetime.fromisoformat(event.created_at)
        
        if since and event_time < since:
            continue
            
        if until and event_time > until:
            continue
            
        # Check if event has video
        if not event.has_video:
            events_without_videos.append({
                'id': event.id,
                'device_id': event.device_id,
                'kind': event.kind,
                'created_at': event.created_at,
                'timestamp': int(event_time.timestamp())
            })
            
    logger.info(f"Found {len(events_without_videos)} events without videos")
    return events_without_videos


def find_matching_videos(storage_path, event_info, time_window_seconds=30):
    """
    Find videos that might match an event based on timestamps.
    
    Args:
        storage_path: Path to the storage directory
        event_info: Event information dict
        time_window_seconds: How many seconds before/after event timestamp to search
        
    Returns:
        List of paths to potential matching videos
    """
    device_id = event_info['device_id']
    event_timestamp = event_info['timestamp']
    
    # Path to live_view directory for this device
    live_view_dir = os.path.join(storage_path, device_id, "live_view")
    
    if not os.path.exists(live_view_dir):
        logger.warning(f"Live view directory doesn't exist: {live_view_dir}")
        return []
        
    # Get all MP4 files in the directory
    video_files = glob.glob(os.path.join(live_view_dir, "*.mp4"))
    
    # Look for videos with timestamps close to the event timestamp
    matching_videos = []
    
    for video_file in video_files:
        # Extract timestamp from filename
        video_filename = os.path.basename(video_file)
        try:
            video_timestamp = int(os.path.splitext(video_filename)[0])
            
            # Check if timestamp is within window
            if abs(video_timestamp - event_timestamp) <= time_window_seconds:
                matching_videos.append({
                    'path': video_file,
                    'timestamp': video_timestamp,
                    'time_diff': abs(video_timestamp - event_timestamp)
                })
        except ValueError:
            # Filename doesn't contain a valid timestamp
            continue
            
    # Sort by timestamp difference (closest first)
    matching_videos.sort(key=lambda x: x['time_diff'])
    
    return matching_videos


def fix_event_video(storage_path, event_info, video_info):
    """
    Fix an event by copying the video to the event directory and updating the event.json.
    
    Args:
        storage_path: Path to the storage directory 
        event_info: Event information dict
        video_info: Video information dict
        
    Returns:
        Path to the copied video if successful, None otherwise
    """
    device_id = event_info['device_id']
    event_id = event_info['id']
    event_type = event_info['kind']
    
    # Source video path
    source_path = video_info['path']
    
    # Create the event directory
    event_dir = os.path.join(storage_path, device_id, event_type, event_id)
    os.makedirs(event_dir, exist_ok=True)
    
    # Create the destination path
    dest_path = os.path.join(event_dir, "video.mp4")
    
    # Copy the video file
    try:
        shutil.copy2(source_path, dest_path)
        logger.info(f"Copied video from {source_path} to {dest_path}")
        
        # Update event.json
        event_json_path = os.path.join(event_dir, "event.json")
        
        if os.path.exists(event_json_path):
            with open(event_json_path, 'r') as f:
                event_data = json.load(f)
        else:
            # Create a basic event data structure if it doesn't exist
            event_data = {
                "id": event_id,
                "kind": event_type,
                "created_at": event_info['created_at'],
                "device_id": device_id
            }
            
        # Update video information
        event_data["has_video"] = True
        event_data["video_path"] = dest_path
        
        # Save updated event data
        with open(event_json_path, 'w') as f:
            json.dump(event_data, f, default=str, indent=2)
            
        logger.info(f"Updated event.json with video information")
        return dest_path
    except Exception as e:
        logger.error(f"Error fixing event video: {e}")
        return None


async def main():
    parser = argparse.ArgumentParser(description="Fix missing video associations for Ring events")
    parser.add_argument("--storage", default=os.path.join(project_root, "captured_media"),
                        help="Path to the storage directory")
    parser.add_argument("--device", help="Only process events for this device ID")
    parser.add_argument("--since", help="Only process events after this date (YYYY-MM-DD)")
    parser.add_argument("--until", help="Only process events before this date (YYYY-MM-DD)")
    parser.add_argument("--window", type=int, default=30,
                        help="Time window in seconds to match videos to events")
    parser.add_argument("--dry-run", action="store_true",
                        help="Don't actually fix anything, just show what would be done")
    
    args = parser.parse_args()
    
    # Parse date arguments
    since = None
    until = None
    
    if args.since:
        since = datetime.strptime(args.since, "%Y-%m-%d")
        
    if args.until:
        until = datetime.strptime(args.until, "%Y-%m-%d").replace(hour=23, minute=59, second=59)
    
    try:
        # Find events without videos
        unassociated_events = await find_unassociated_events(
            args.storage, since, until, args.device
        )
        
        if not unassociated_events:
            logger.info("No unassociated events found")
            return
            
        fixed_count = 0
        
        # Process each unassociated event
        for event in unassociated_events:
            logger.info(f"Processing event {event['id']} ({event['kind']} on {event['created_at']})")
            
            # Find potential matching videos
            matching_videos = find_matching_videos(args.storage, event, args.window)
            
            if not matching_videos:
                logger.warning(f"No matching videos found for event {event['id']}")
                continue
                
            best_match = matching_videos[0]
            logger.info(f"Found best match: {os.path.basename(best_match['path'])} " +
                       f"(time difference: {best_match['time_diff']} seconds)")
            
            if args.dry_run:
                logger.info(f"[DRY RUN] Would fix event {event['id']} with video {best_match['path']}")
                continue
                
            # Fix the event
            if fix_event_video(args.storage, event, best_match):
                fixed_count += 1
                
        logger.info(f"Fixed {fixed_count} events out of {len(unassociated_events)} unassociated events")
        
    except Exception as e:
        logger.error(f"Error: {e}")


if __name__ == "__main__":
    asyncio.run(main())
