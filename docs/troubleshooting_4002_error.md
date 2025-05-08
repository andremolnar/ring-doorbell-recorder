# Troubleshooting 4002 Errors in Ring WebRTC Connections

Error 4002 is a generic WebSocket message error that occurs when there's an issue with the WebRTC signaling process between your application and Ring's servers. This guide will help you diagnose and resolve these errors.

## Common Causes for 4002 Errors

### Incorrect Message Format

The most common cause of 4002 errors is using an outdated or incorrect message format. Ring occasionally updates their API, and message formats can change.

**Solution**:

- Ensure your messages follow the the format documented in the [LiveView Client Documentation (verified working May 20025)](live_view_client.md) - or another reputable source of the most up to date message information.
- Pay special attention to the WebSocket message structure, especially for live_view and ping messages.

### Key Format Issues to Check

1. **Message structure**: Verify that all required fields are present and correctly formatted

2. **Data Types**: Common errors include:

   - Sending `doorbot_id` as a string instead of an integer
   - Incorrect format for the `session_id` (should be the JWT token received from Ring)
   - Malformed SDP offer or ICE candidates

3. **Method Names**: Make sure you're using the correct method names:
   - The initial connection message should use `"method": "live_view"`
   - Keepalive messages should use `"method": "ping"`

### Example of Correct Message Formats

**Initial Offer Message**:

```json
{
  "method": "live_view",
  "dialog_id": "uuid-v4-string",
  "riid": "random-hex-string",
  "body": {
    "doorbot_id": 123456789,
    "sdp": "v=0...",
    "stream_options": {
      "audio_enabled": false,
      "video_enabled": true,
      "ptz_enabled": false
    }
  }
}
```

**Ping Keepalive Message**:

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

## Incorrect Request Sequence

Another common cause of 4002 errors is sending messages in the wrong order.

**Solution**:
Follow this exact sequence:

1. Connect to the WebSocket server
2. Send the SDP offer with a live_view message
3. Wait for and process the SDP answer
4. Wait for the session_created message to get the session JWT
5. Wait for the camera_started message
6. Begin regular ping keepalive messages
7. Handle ICE candidates in both directions

## Specific Error Codes

When you receive a close message, it may include a specific error code. Here's what they mean:

- **Error 26**: "Not ready yet" - The camera is not yet ready to stream. The client should wait a short time (300ms recommended) and try again.

- **Other Error Codes**: Unfortunately, Ring doesn't publicly document all their error codes. If you encounter an error code not listed here:
  - Enable debug logging to capture the full error message
  - Check the log for the specific "reason text" that accompanies the code
  - Analyze the message flow leading up to the error

## Authentication Issues

Some 4002 errors happen when there's an issue with authentication:

1. **Invalid or Expired Token**: Your authentication token may be expired
2. **Missing Account ID**: The LiveViewClient requires a valid account ID
3. **Region Mismatch**: Using the wrong regional endpoint for your account

**Solution**:

- Regenerate your authentication token
- Make sure your auth_manager correctly provides the account ID
- Let the client automatically determine the correct regional endpoint

## Network and Connectivity Issues

Sometimes a 4002 error may occur due to:

1. **Firewall Blocking WebSocket or WebRTC**: Ensure your firewall allows outgoing WebSocket connections and UDP traffic for WebRTC
2. **NAT Traversal Issues**: On complex networks, STUN servers might not be sufficient for NAT traversal

**Solution**:

- Check your network configuration
- If on a corporate network, you may need to request exceptions for WebRTC traffic

## Debugging Strategies

1. **Enable Debug Logging**:

   ```python
   import logging
   logging.basicConfig(level=logging.DEBUG)
   logging.getLogger("ring.live").setLevel(logging.DEBUG)
   ```

2. **Use WebSocket Inspection Tools**:

   - Tools like [Wireshark](https://www.wireshark.org/) can capture and analyze WebSocket traffic
   - Filter for WebSocket packets to see the exact messages being sent and received

3. **Validate Your SDP Offer**:

   - WebRTC SDP offers must be correctly formatted
   - Ensure you're creating a receive-only video transceiver

4. **Compare to Working Implementation**:
   - Study the `LiveViewClient` implementation in `src/capture/live_view_client.py`
   - Try using the provided example in `live_view_example.py`

## Still Having Issues?

If you've gone through all these steps and still encounter 4002 errors, please:

1. Capture the full logs with debug logging enabled
2. Note the exact sequence of steps leading to the error
3. Document the error code and reason text if present
4. Check if Ring has updated their API recently
5. Review the `live_view_client.md` documentation for any updates

Remember that Ring's API is proprietary and subject to change without notice. The project maintainers will probably not keep the client code updated as the API evolves unless they need to for their own needs :P - BUT, pull requests are welcome.
