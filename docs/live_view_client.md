# Ring LiveView Client Documentation

This document describes how the WebRTC-based live view functionality works with Ring doorbell and camera devices. It covers the connection flow, protocol details, and implementation details.

## Overview

The LiveViewClient class establishes a WebRTC connection to a Ring doorbell or camera to receive live video. The implementation follows Ring's WebRTC protocol to ensure compatibility with their servers. This allows capturing real-time video from Ring devices without using the official Ring app.

## Connection Flow

The LiveViewClient follows these steps to establish a connection:

1. **Authentication and Preparation**

   - Obtain the user's Ring account ID
   - Generate a signalsocket ticket from Ring's API
   - Determine the correct WebSocket URL based on region

2. **WebRTC Offer Generation**

   - Create an RTCPeerConnection with STUN servers
   - Add a receive-only video transceiver
   - Generate an SDP offer and set as local description
   - Gather ICE candidates

3. **Signaling via WebSocket**

   - Connect to Ring's WebSocket server
   - Send the SDP offer in a "live_view" message
   - Process incoming messages including SDP answers, ICE candidates, session tokens

4. **Session Maintenance**
   - Send regular "ping" keepalive messages every 5 seconds
   - Monitor connection state changes
   - Process incoming frames and forward to video sink
   - Auto-stop after maximum duration (default 590s) to prevent battery drain

## Protocol Details

### WebSocket Message Types

The Ring WebRTC protocol uses several types of messages:

- **live_view**: Initial message with SDP offer, and Ring's response with SDP answer
- **session_created**: Contains the session JWT needed for keepalives
- **camera_started**: Indicates the camera is ready to stream
- **icecandidate**: Exchanges ICE candidates between peers
- **ping**: Keepalive message to maintain the connection
- **notification**: Various status updates from the camera
- **close**: Indicates session closure with reason codes

### Message Format

Messages follow this general structure:

```json
{
  "method": "live_view", // or other method
  "dialog_id": "uuid-v4-string",
  "riid": "random-hex-string",
  "body": {
    "doorbot_id": 123456789,
    "sdp": "v=0...", // SDP offer or answer
    "stream_options": {
      "audio_enabled": false,
      "video_enabled": true,
      "ptz_enabled": false
    }
  }
}
```

Ping messages have a simpler format:

```json
{
  "method": "ping",
  "dialog_id": "uuid-v4-string",
  "body": {
    "doorbot_id": 123456789,
    "session_id": "jwt-token"
  }
}
```

### ICE Servers

The implementation uses Google's public STUN servers for NAT traversal:

- stun:stun.l.google.com:19302
- stun:stun1.l.google.com:19302
- stun:stun2.l.google.com:19302

No TURN servers are needed for most home network configurations.

## Implementation Details

### Key Components

- **LiveViewClient**: Main class that handles the WebRTC connection
- **RecorderSink**: Video sink implementation that saves frames to an MP4 file
- **MediaRecorder**: Used by RecorderSink to create MP4 files from WebRTC tracks

### Important Methods

- `start()`: Initiates the connection process
- `stop()`: Terminates the connection and cleans up resources
- `_on_track()`: Handles incoming video tracks and forwards frames to the sink
- `_keepalive_webrtc_session()`: Sends regular ping messages to maintain the connection
- `_monitor_connection_state()`: Watches WebRTC connection state for issues
- `_monitor_message_handler()`: Processes incoming WebSocket messages

### Error Handling

The implementation includes robust error handling:

- Connection failures are detected and reported
- Timeouts prevent the client from hanging indefinitely
- ICE connection issues are monitored and recovery is attempted
- Graceful cleanup on shutdown to prevent resource leaks

## Usage Example

Basic usage of the LiveViewClient:

```python
import asyncio
from src.capture.live_view_client import LiveViewClient
from src.capture.video_sinks import RecorderSink

async def main():
    # Create a sink to receive video frames
    sink = RecorderSink("video.mp4")

    # Create the client with authentication token and device ID
    client = LiveViewClient(
        auth_token="your-ring-token",
        device_id="your-device-id",
        video_sink=sink
    )

    # Start the client (this establishes the connection)
    success = await client.start()

    if success:
        print("Connected! Recording for 30 seconds...")
        # Wait for some time to capture video
        await asyncio.sleep(30)

        # Stop the client and clean up resources
        await client.stop()
        print("Recording completed")

# Run the example
asyncio.run(main())
```

See `live_view_example.py` for a complete working example.

## Troubleshooting

### Common Issues

1. **4002 Invalid Message Errors**

   - Check the format of keepalive messages (should use "method": "ping")
   - Ensure proper session_id is included in messages
   - Verify doorbot_id is sent as an integer, not a string

   For a detailed guide on resolving these errors, see [Troubleshooting 4002 Errors](troubleshooting_4002_error.md).

2. **ICE Connection Failures**

   - Ensure UDP traffic is not blocked by firewalls
   - Try adding more STUN servers to the configuration
   - Check for VPN or network issues affecting WebRTC traffic

3. **Empty or Missing Video Files**
   - Ensure the MediaRecorder is properly started and stopped
   - Verify that frames are being received (check logs for frame counts)
   - Allow sufficient time for recording before stopping the client

### Debugging

Enable debug logging to see detailed information about the connection process:

```python
import logging
logging.basicConfig(level=logging.DEBUG)
logging.getLogger("ring.live").setLevel(logging.DEBUG)
```

## References

This implementation is based on:

- The dgreif/ring TypeScript library
- WebRTC and WebSocket protocol standards
- Packet captures and analysis of Ring's web dashboard
- Testing against Ring's production servers

## Limitations

- Battery-powered Ring devices will disconnect after approximately 10 minutes
- Video quality and resolution are determined by the Ring device
- Audio is currently not supported (video-only)
- Some advanced features (PTZ control, two-way audio) are not implemented
