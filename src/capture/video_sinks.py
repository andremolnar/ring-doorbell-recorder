"""Video sink implementations for the LiveViewClient."""

import asyncio
import logging
import os
from pathlib import Path
from typing import List, Optional, Union

from aiortc.contrib.media import MediaRecorder

from ..core.interfaces import VideoSink, IStorage

logger = logging.getLogger("ring.video")


class RecorderSink(VideoSink):
    """
    Video sink that records to an MP4 file using aiortc's MediaRecorder.
    
    This is the simplest sink that just delegates to MediaRecorder.
    """
    
    def __init__(self, path: Union[str, Path]):
        """
        Initialize the RecorderSink.
        
        Args:
            path: Path to the MP4 file to create
        """
        self._path = str(path)
        # Ensure the directory exists
        os.makedirs(os.path.dirname(self._path), exist_ok=True)
        # Create the MediaRecorder
        self._rec = MediaRecorder(self._path)
        self.frame_count = 0  # Track the number of frames processed
        self._started = False
        logger.info(f"RecorderSink initialized with path: {self._path}")
        
    async def start(self):
        """Start the media recorder."""
        if not self._started and self._rec:
            await self._rec.start()
            self._started = True
            logger.debug("MediaRecorder started")
        return self

    async def write(self, frame) -> None:
        """
        Process a video frame.
        
        For MediaRecorder, we don't need to do anything here as it
        handles frames automatically once the track is added.
        
        Args:
            frame: Video frame from aiortc
        """
        # MediaRecorder wants tracks, not frames
        # LiveViewClient._on_track calls self._rec.addTrack(track) instead
        self.frame_count += 1  # Increment frame counter
        
        # Log frame count at useful intervals
        if self.frame_count == 1 or self.frame_count % 100 == 0:
            logger.debug(f"RecorderSink received {self.frame_count} frames")

    async def close(self) -> None:
        """Close the sink and finalize the MP4 file."""
        if hasattr(self, '_rec') and self._rec:
            try:
                logger.info(f"Stopping MediaRecorder for {self._path}")
                
                try:
                    # Make sure the recorder is started
                    if not self._started:
                        logger.debug("MediaRecorder was never started, starting it now")
                        await self.start()
                        
                    # Give a small delay to ensure any buffered frames are written
                    await asyncio.sleep(0.5)
                    
                    # Create a task to stop the recorder
                    await self._rec.stop()
                    logger.debug("MediaRecorder stopped")
                    
                except Exception as e:
                    logger.error(f"Error stopping MediaRecorder: {e}")
                
                self._rec = None
                
                # Verify file exists and has content
                if os.path.exists(self._path):
                    size = os.path.getsize(self._path)
                    logger.info(f"MediaRecorder completed. Output file size: {size} bytes")
                    if size < 1000:  # Check for a minimum file size
                        logger.warning(f"Warning: Output file is too small: {self._path} ({size} bytes)")
                else:
                    logger.warning(f"Warning: Output file does not exist: {self._path}")
                
                return self._path
            except Exception as e:
                logger.error(f"Error closing MediaRecorder: {e}")
                # Still return the path even if there was an error
                return self._path


class CVFanoutSink(VideoSink):
    """
    Video sink that distributes frames to multiple storage backends.
    
    This is useful for both storing video and processing frames for
    computer vision tasks simultaneously.
    """
    
    def __init__(self, *storage_backends: IStorage):
        """
        Initialize the CVFanoutSink.
        
        Args:
            *storage_backends: Multiple storage backends to receive frames
        """
        self._subs = storage_backends
        logger.info(f"CVFanoutSink initialized with {len(storage_backends)} backends")

    async def write(self, frame) -> None:
        """
        Distribute frame to all storage backends.
        
        Args:
            frame: Video frame from aiortc
        """
        # Fan-out to N coroutines (e.g., NAS + disk + in-memory queue for CV model)
        if hasattr(frame, "to_ndarray") and callable(frame.to_ndarray):
            # For VideoFrame objects, convert to something storage can handle
            tasks = []
            for s in self._subs:
                if hasattr(s, 'write_frame') and callable(s.write_frame):
                    tasks.append(s.write_frame(frame))
            if tasks:
                await asyncio.gather(*tasks)

    async def close(self) -> None:
        """Close all storage backends."""
        tasks = []
        for s in self._subs:
            if hasattr(s, 'close') and callable(s.close):
                tasks.append(s.close())
        if tasks:
            await asyncio.gather(*tasks)
