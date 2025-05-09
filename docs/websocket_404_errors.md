# Troubleshooting WebSocket 404 Errors and Ticket Renewal

## Problem

After running the Ring Doorbell application for some time, the LiveViewClient may encounter a `404 error` when connecting to the WebSocket:

```
Error starting live view: server rejected WebSocket connection: HTTP 404
```

This is typically caused by one of the following issues:

1. **Signalsocket ticket expiration**: The WebRTC signalsocket ticket has expired and needs to be renewed
2. **Connection issues**: Temporary network connectivity problems
3. **API endpoint changes**: Changes in Ring's backend service endpoints

## Solution

We've implemented several improvements to make the LiveViewClient more resilient:

### 1. Automatic Ticket Renewal

The LiveViewClient now periodically refreshes the signalsocket ticket that's required for WebRTC connections. Unlike auth tokens (which can last for weeks), these tickets typically expire after a short while.

This automatic renewal is handled through the `_check_and_refresh_ticket` method, which fetches a fresh ticket every few minutes (by default, every 3 minutes).

### 2. Robust Reconnection Logic

If a connection fails:

- The client will automatically retry with exponential backoff
- A maximum of 3 retry attempts will be made before giving up
- Each retry will use a fresh ticket
- Connection attempt tracking ensures we don't get stuck in an infinite retry loop

### 3. Connection Monitoring

The client now monitors its connections more closely:

- Checks for consecutive errors in message handling
- Monitors keepalive ping responses
- Gracefully handles WebSocket close events from the server

## Manual Intervention

If you still encounter issues despite these improvements, you can try:

1. **Force refresh your Ring token and ticket**:

   - Delete the `ring_token.cache` file
   - Restart the application to go through authentication again

2. **Check network connectivity**:

   - Ensure your Ring device has a stable internet connection
   - Verify that your local network can reach Ring's servers

3. **Check logs for specific errors**:
   - Look for patterns in the logs that might indicate a particular failure mode
   - Note any specific error codes that might help diagnose the issue

## Additional Information

The original issue was discovered by observing that the WebSocket connections would intermittently fail with 404 errors after some period of time. This is consistent with ticket expiration behavior, where previously valid connection endpoints no longer recognize the authentication credentials.

The solution is based on examining the TypeScript client implementation for Ring by dgreif, which handles ticket refreshing and connection management in a similar way. Our implementation now follows industry best practices for maintaining long-lived WebSocket connections to services that use ticket-based authentication for WebRTC sessions.

## Technical Details

### Signalsocket Ticket vs. Auth Token

It's important to understand the difference between these two authentication mechanisms:

1. **Auth Token**: Long-lived authentication token for the Ring API (lasts weeks/months)

   - Obtained during initial login
   - Stored in `ring_token.cache`
   - Used for general API requests

2. **Signalsocket Ticket**: Short-lived ticket specifically for WebRTC connections (lasts minutes)
   - Obtained by making a request to `https://app.ring.com/api/v1/clap/ticket/request/signalsocket`
   - Used only for establishing WebSocket connections for live streaming
   - Must be refreshed frequently

The 404 error occurs when trying to connect to the WebSocket endpoint with an expired signalsocket ticket. Our new system ensures this ticket is refreshed before it can expire.

## Customizing Refresh Parameters

You can adjust the following parameters in `live_view_client.py` to change the refresh behavior:

```python
# How often to check if ticket renewal is needed (in seconds)
TICKET_CHECK_INTERVAL = 2400 # 40 minutes

# Maximum number of connection retries before giving up
MAX_RETRIES = 3

# Initial backoff time in seconds
INITIAL_BACKOFF = 2

# Maximum backoff time in seconds
MAX_BACKOFF = 30
```

Adjust these values if you're experiencing either too many reconnections or not enough refreshes.
