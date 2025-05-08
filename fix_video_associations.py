#!/usr/bin/env python3
"""
Ring Doorbell Video Association Fixer

This script finds Ring event videos that were recorded but not properly linked to their events,
and fixes the connections by copying videos to the correct event directories.

Usage:
    python fix_video_associations.py [--since YYYY-MM-DD] [--device-id DEVICE_ID]

Options:
    --since YYYY-MM-DD    Only process events after this date
    --until YYYY-MM-DD    Only process events before this date
    --device-id ID        Only process events from this device
    --dry-run             Don't make any changes, just report what would be done
"""

import os
import sys
import asyncio
import argparse
import logging
import glob
import json
import shutil
from datetime import datetime, timedelta
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("video-fixer")

# Add project root to path
project_root = Path(__file__).resolve().parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.storage.storage_impl import FileStorage
from src.core.interfaces import EventData, MotionEventData, DingEventData


async def find_events_without_videos(storage, since=None, until=None, device_id=None):
    """Find events that don't have associated videos."""
    logger.info("Looking for events without videos...")
    
    all_events = await storage.list_events()
    logger.info(f"Found {len(all_events)} total events")
    
    events_without_videos = []
    for event in all_events:
        # Apply filters
        if device_id and event.device_id != device_id:
            continue
            
        event_time = datetime.fromisoformat(event.created_at.split('.')[0] if '.' in event.created_at else event.created_at)
        
        if since and event_time < since:
            continue
            
        if until and event_time > until:
            continue
            
        # Check if event has video
        if not event.has_video:
            events_without_videos.append(event)
            
    logger.info(f"Found {len(events_without_videos)} events without videos")
    return events_without_videos


def find_matching_videos(storage_dir, event, window_seconds=30):
    """
    Find videos in the live_view directory that might match an event based on timestamp.
    Returns a list of potential matching video paths, sorted by likelihood.
    """
    device_id = event.device_id
    
    # Convert event timestamp to epoch
    event_time = datetime.fromisoformat(event.created_at.split('.')[0] if '.' in event.created_at else event.created_at)
    event_timestamp = int(event_time.timestamp())
    
    # Path to live_view directory for this device
    live_view_dir = os.path.join(storage_dir, device_id, "live_view")
    
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
            time_diff = abs(video_timestamp - event_timestamp)
            if time_diff <= window_seconds:
                matching_videos.append({
                    'path': video_file,
                    'timestamp': video_timestamp,
                    'time_diff': time_diff
                })
        except ValueError:
            # Filename doesn't contain a valid timestamp
            continue
            
    # Sort by timestamp difference (closest first)
    matching_videos.sort(key=lambda x: x['time_diff'])
    
    return matching_videos


def fix_event_video(storage_dir, event, video_info, dry_run=False):
    """Copy video to event directory and update event with video information."""
    device_id = event.device_id
    event_id = event.id
    event_type = event.kind
    
    # Source video path
    source_path = video_info['path']
    
    # Create the event directory
    event_dir = os.path.join(storage_dir, device_id, event_type, event_id)
    
    # Create the destination path
    dest_path = os.path.join(event_dir, "video.mp4")
    
    # Log what we're going to do
    logger.info(f"{'[DRY RUN] Would copy' if dry_run else 'Copying'} video from {source_path} to {dest_path}")
    
    if dry_run:
        return True
    
    # Actually make the changes
    try:
        # Create directory if it doesn't exist
        os.makedirs(event_dir, exist_ok=True)
        
        # Copy the video file
        shutil.copy2(source_path, dest_path)
        logger.info(f"✅ Copied video successfully")
        
        # Update or create event.json
        event_json_path = os.path.join(event_dir, "event.json")
        
        # Get event data as dictionary
        event_dict = event.dict() if hasattr(event, 'dict') else vars(event)
        
        # Update video information
        event_dict["has_video"] = True
        event_dict["video_path"] = dest_path
        
        # Write event data
        with open(event_json_path, 'w') as f:
            json.dump(event_dict, f, default=str, indent=2)
            
        logger.info(f"✅ Updated event.json with video information")
        return True
        
    except Exception as e:
        logger.error(f"❌ Error fixing event video: {e}")
        return False


async def main():
    parser = argparse.ArgumentParser(description="Fix Ring Doorbell video associations")
    parser.add_argument("--since", help="Only process events after this date (YYYY-MM-DD)")
    parser.add_argument("--until", help="Only process events before this date (YYYY-MM-DD)")
    parser.add_argument("--device-id", help="Only process events from this device")
    parser.add_argument("--window", type=int, default=60,
                       help="Time window in seconds to match videos to events (default: 60)")
    parser.add_argument("--storage-dir", default=os.path.join(project_root, "captured_media"),
                       help="Path to the storage directory")
    parser.add_argument("--dry-run", action="store_true",
                       help="Don't actually make any changes, just show what would be done")
    
    args = parser.parse_args()
    
    # Parse date arguments
    since = None
    until = None
    
    if args.since:
        try:
            since = datetime.strptime(args.since, "%Y-%m-%d")
            logger.info(f"Looking for events since {since.strftime('%Y-%m-%d')}")
        except ValueError:
            logger.error("Invalid --since date format. Use YYYY-MM-DD")
            return 1
        
    if args.until:
        try:
            until = datetime.strptime(args.until, "%Y-%m-%d").replace(hour=23, minute=59, second=59)
            logger.info(f"Looking for events until {until.strftime('%Y-%m-%d')}")
        except ValueError:
            logger.error("Invalid --until date format. Use YYYY-MM-DD")
            return 1
    
    if args.device_id:
        logger.info(f"Filtering for device ID: {args.device_id}")
        
    if args.dry_run:
        logger.info("DRY RUN mode: No changes will be made")
    
    # Initialize storage
    storage_dir = args.storage_dir
    storage = FileStorage(storage_dir)
    
    try:
        # Find events without videos
        events_without_videos = await find_events_without_videos(
            storage, since, until, args.device_id
        )
        
        if not events_without_videos:
            logger.info("No events without videos found")
            return 0
            
        # Process each event
        fixed_count = 0
        for event in events_without_videos:
            logger.info(f"Processing event: {event.id} ({event.kind} on {event.created_at})")
            
            # Find potential matching videos
            matching_videos = find_matching_videos(storage_dir, event, args.window)
            
            if not matching_videos:
                logger.warning(f"No matching videos found for event {event.id}")
                continue
                
            # Get the best match (closest in time)
            best_match = matching_videos[0]
            logger.info(f"Found best match: {os.path.basename(best_match['path'])} (time difference: {best_match['time_diff']} seconds)")
            
            # Fix the event
            if fix_event_video(storage_dir, event, best_match, args.dry_run):
                fixed_count += 1
                
        # Summary
        if args.dry_run:
            logger.info(f"Would have fixed {fixed_count} out of {len(events_without_videos)} events")
        else:
            logger.info(f"Fixed {fixed_count} out of {len(events_without_videos)} events")
        
        # Update events in storage
        if fixed_count > 0 and not args.dry_run:
            logger.info("Refresh your application to see the fixed video associations")
            
    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        return 1
    finally:
        # Clean up
        await storage.close()
    
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
