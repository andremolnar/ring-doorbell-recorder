"""LiveViewClient for WebRTC-based Ring doorbell live view streaming."""

import asyncio
import json
import logging
import time
import uuid
import aiohttp
from websockets.asyncio.client import connect

from aiortc import (
    RTCPeerConnection, RTCSessionDescription,
    RTCConfiguration, RTCIceServer, 
    RTCIceCandidate
)

from ..core.interfaces import VideoSink, IAuthManager
from ..utils.connection_monitor import ConnectionMonitor

# Configure structured logging
logger = logging.getLogger("ring.live")


class LiveViewClient:
    """
    Live View Client for Ring doorbell cameras using WebRTC.
    
    This class handles the WebRTC negotiation with Ring's servers and
    pipes the received video frames to the provided VideoSink.
    """
    
    KEEPALIVE_SEC = 9
    MAX_DURATION = 590  # battery cams die at 10 min, stop at 9 m 50 s
    WS_PARAMS = "api_version=4.0&auth_type=ring_solutions"  # Removed auth_type=ring_solutions
    # Maximum number of connection retries before giving up
    MAX_RETRIES = 3
    # Initial backoff time in seconds
    INITIAL_BACKOFF = 2
    # Maximum backoff time in seconds
    MAX_BACKOFF = 30
    # How often to check if ticket renewal is needed (in seconds)
    TICKET_CHECK_INTERVAL = 1800  # 30 minutes - tickets typically expire after 1 hour
    # How often to check connection status (in seconds)
    CONNECTION_CHECK_INTERVAL = 15

    def __init__(self, auth_token: str, device_id: str, video_sink: VideoSink, auth_manager: IAuthManager = None, 
                 enable_wake_detection: bool = True):
        """
        Initialize the LiveViewClient.
        
        Args:
            auth_token: Ring API authentication token
            device_id: Ring device ID to stream from
            video_sink: Sink implementation for receiving video frames
            auth_manager: Optional authentication manager for advanced auth operations
            enable_wake_detection: Whether to enable wake detection to reconnect after system sleep
        """
        self._token = auth_token
        self._dev = device_id
        self._sink = video_sink
        self._auth_manager = auth_manager
        self._pc = None
        self._ws = None
        self._stop = asyncio.Event()
        self._track_added = False
        self._dialog_id = str(uuid.uuid4())
        self._session_id = str(uuid.uuid4())
        self._account_id = None
        self._seq = 1
        self._connection_attempts = 0
        self._connection_backoff = self.INITIAL_BACKOFF
        self._ticket = None
        self._region = None
        self._ticket_updated_at = 0  # Start with immediate refresh
        self._enable_wake_detection = enable_wake_detection
        self._connection_monitor = None
        
    async def _check_and_refresh_ticket(self) -> tuple:
        """
        Check if the signalsocket ticket needs to be refreshed and get a new one if needed.
        
        Returns:
            A tuple of (ticket, region) - refreshed if necessary
            
        Raises:
            ValueError: If unable to get a valid ticket after retries
        """
        # If it's been less than TICKET_CHECK_INTERVAL since last update, use current ticket
        current_time = time.time()
        time_since_refresh = current_time - self._ticket_updated_at
        
        # If we have a valid ticket that's not too old, use it
        if self._ticket and time_since_refresh < self.TICKET_CHECK_INTERVAL:
            logger.debug(f"Using existing ticket (age: {time_since_refresh:.1f}s)")
            return self._ticket, self._region
            
        logger.info(f"Refreshing signalsocket ticket (age: {time_since_refresh:.1f}s)...")
        
        # Attempt to get a new ticket using our max retries
        attempt = 0
        last_error = None
        
        while attempt < self.MAX_RETRIES:
            attempt += 1
            try:
                # Try to refresh auth token first if we have an auth manager
                if self._auth_manager and attempt > 1:
                    fresh_token = self._auth_manager.get_token()
                    if fresh_token:
                        self._token = fresh_token
                        logger.info("Refreshed auth token for ticket request")
                
                # Get a fresh ticket using _get_ticket method
                ticket, region, auth_error = await self._get_ticket()
                
                # Handle authentication error specially
                if auth_error:
                    if attempt < self.MAX_RETRIES:
                        logger.warning(f"Authentication issue detected during ticket refresh (attempt {attempt}/{self.MAX_RETRIES}), retrying...")
                        await asyncio.sleep(1)
                        continue
                    else:
                        raise ValueError("Authentication failed after multiple attempts")
                    
                # If no ticket was returned
                if not ticket:
                    if attempt < self.MAX_RETRIES:
                        logger.warning(f"Failed to get ticket (attempt {attempt}/{self.MAX_RETRIES}), retrying...")
                        await asyncio.sleep(1)
                        continue
                    else:
                        raise ValueError("Failed to get signalsocket ticket after multiple attempts")
                
                # Update our stored ticket and timestamp
                self._ticket = ticket
                self._region = region
                self._ticket_updated_at = current_time
                logger.info(f"Signalsocket ticket refreshed successfully")
                
                return ticket, region
                
            except Exception as e:
                last_error = e
                logger.error(f"Error refreshing signalsocket ticket (attempt {attempt}/{self.MAX_RETRIES}): {e}")
                await asyncio.sleep(1)
        
        # If we have an existing ticket despite refresh failure, use it as a last resort
        if self._ticket:
            logger.warning(f"Using existing ticket as last resort after {self.MAX_RETRIES} failed refresh attempts")
            return self._ticket, self._region
            
        # We couldn't get a ticket after multiple attempts
        raise ValueError(f"Failed to obtain a signalsocket ticket: {last_error}")
            
    async def _get_account_id(self):
        """Get the Ring account ID using the authentication token or auth manager."""
        if self._account_id:
            return self._account_id
            
        logger.info("Retrieving Ring account ID...")
        
        # Try to get account ID from auth manager if available
        if self._auth_manager:
            try:
                account_id_str = await self._auth_manager.get_account_id()
                self._account_id = int(account_id_str)
                logger.info(f"Retrieved account ID from auth manager: {self._account_id}")
                return self._account_id
            except Exception as e:
                logger.debug(f"Error getting account ID from auth manager: {e}")
                # No fallback - we need the real account ID
                raise ValueError("Could not retrieve account ID from Auth Manager")
            

    async def _get_ticket(self):
        """
        Request a signalsocket ticket from the Ring API.
        
        Returns:
            Tuple of (ticket, region, auth_error) where auth_error is a boolean
            indicating whether an authentication error occurred
        """
        logger.info("Requesting signalsocket ticket...")
        try:
            async with aiohttp.ClientSession() as session:
                response = await session.post(
                    "https://app.ring.com/api/v1/clap/ticket/request/signalsocket",
                    headers={"Authorization": f"Bearer {self._token}"}
                )
                if response.status != 200:
                    error_text = await response.text()
                    error_msg = f"Failed to get ticket: {response.status} - {error_text}"
                    
                    # Handle authentication errors specially
                    if response.status in (401, 403):
                        logger.warning(f"Authentication error when requesting ticket: {error_msg}")
                        # Check if auth manager is available to refresh token
                        if self._auth_manager and self._connection_attempts < self.MAX_RETRIES:
                            logger.info("Attempting to refresh authentication token...")
                            fresh_token = self._auth_manager.get_token()
                            if fresh_token and fresh_token != self._token:
                                self._token = fresh_token
                                logger.info("Authentication token refreshed, will retry ticket request")
                                # Signal that auth error occurred without raising exception
                                return None, None, True  # Third param indicates auth error
                        
                        # Return auth error if we couldn't refresh
                        return None, None, True
                        
                    raise ValueError(error_msg)
                    
                data = await response.json()
                logger.debug(f"Received ticket response: {data}")
                
                # Check if the response contains a ticket
                if "ticket" not in data:
                    logger.warning("Ticket response missing ticket field")
                    raise ValueError("Ticket response missing required 'ticket' field")
                    
                # Return the ticket and region (region might be None) with auth_error=False
                return data["ticket"], data.get("region"), False
        except Exception as e:
            if "Authentication error" in str(e) or "401" in str(e) or "403" in str(e):
                logger.warning(f"Authentication error: {e}")
                return None, None, True
            else:
                logger.error(f"Error getting signalsocket ticket: {e}")
                raise

    async def start(self):
        """
        Start a WebRTC live view session with Ring:
        1. Create WebRTC peer connection and generate offer
        2. Connect to WebSocket and send the offer
        3. Handle SDP answer and ICE candidates
        4. Start media pipeline
        
        Will retry on failures with exponential backoff.
        """
        # Keep track of connection attempts
        self._connection_attempts += 1
        
        try:
            # Print a clear message showing we're starting
            print("\n📹 Starting Ring LiveView client...")
            print(f"🔑 Using device ID: {self._dev}")
            print(f"🔄 Connection attempt {self._connection_attempts} of {self.MAX_RETRIES}")
            
            # Check token if auth manager provided (token still needed for getting tickets)
            if self._auth_manager:
                fresh_token = self._auth_manager.get_token()
                if fresh_token:
                    # Always update the token regardless of whether it seems changed
                    # since the formatting or encoding might differ
                    self._token = fresh_token
                    logger.info("Using refreshed auth token")
                    # Force ticket refresh on the next attempt
                    self._ticket_updated_at = 0
                else:
                    logger.warning("Auth manager returned no token, using existing token")
            
            # Ensure we have the account ID
            try:
                account_id = await self._get_account_id()
                print(f"👤 Using account ID: {account_id}")
            except Exception as e:
                logger.error(f"Cannot proceed without account ID: {e}")
                print(f"❌ Cannot proceed without account ID: {e}")
                raise ValueError("Account ID is required for Ring WebRTC streaming")
            
            # Generate session and dialog IDs
            self._session_id = str(uuid.uuid4())
            self._dialog_id = str(uuid.uuid4())
            self._seq = 1
            
            print(f"🔄 Session ID: {self._session_id[:8]}...")
            print(f"🔄 Dialog ID: {self._dialog_id[:8]}...")
            
            # Get fresh auth ticket and determine WebSocket URL
            self._ticket, self._region = await self._check_and_refresh_ticket()
            ws_url = await self._build_ws_url(self._ticket, self._region)
            logger.info(f"Connecting to WebSocket URL: {ws_url[:60]}...")
            
            # Create RTCPeerConnection with ICE servers for better connectivity
            rtc_config = RTCConfiguration([
                RTCIceServer(urls=["stun:stun.l.google.com:19302"]),
                RTCIceServer(urls=["stun:stun1.l.google.com:19302"]),
                RTCIceServer(urls=["stun:stun2.l.google.com:19302"]),
            ])
            self._pc = RTCPeerConnection(configuration=rtc_config)
            
            # Add transceiver in receive-only mode for video
            self._pc.addTransceiver("video", direction="recvonly")
            
            # Set up track handler
            @self._pc.on("track")
            async def on_track(track):
                logger.info(f"Track received: {track.kind}")
                # Create a task and store it for proper cleanup later
                self._track_task = asyncio.create_task(self._on_track(track))
                self._track_task.add_done_callback(
                    lambda _: logger.debug("Track task completed")
                )
            
            # Create offer
            offer = await self._pc.createOffer()
            await self._pc.setLocalDescription(offer)
            
            # Wait for ICE gathering to complete
            await self._wait_for_ice_gathering()
            
            # Connect to WebSocket and start signaling
            try:
                self._ws = await connect(
                    ws_url,
                    ping_interval=None,
                    subprotocols=("aws.iot.webrtc.signalling.lightcone",),
                    user_agent_header="Mozilla/5.0 (RingPython)"
                )
                print("🔌 WebSocket connection established")
                # Reset connection attempts counter on success
                self._connection_attempts = 0
                self._connection_backoff = self.INITIAL_BACKOFF
            except Exception as ws_error:
                # Handle WebSocket connection errors specifically
                logger.error(f"WebSocket connection error: {ws_error}")
                
                # Check for all types of auth-related errors
                auth_error = any(code in str(ws_error) for code in ["401", "403", "404"])
                
                if auth_error and self._connection_attempts < self.MAX_RETRIES:
                    if "401" in str(ws_error) or "403" in str(ws_error):
                        logger.warning("HTTP 401/403 error detected. Authentication problem likely. Will try with refreshed token.")
                        # Try to get a fresh auth token if auth manager is available
                        if self._auth_manager:
                            fresh_token = self._auth_manager.get_token()
                            if fresh_token:
                                self._token = fresh_token
                                logger.info("Auth token refreshed due to 401/403 error")
                    else:
                        logger.warning("HTTP 404 error, likely ticket expired. Will retry with fresh ticket.")
                        
                    # Force ticket refresh regardless of timing
                    self._ticket_updated_at = 0
                    await self.stop()
                    
                    # Calculate backoff time
                    backoff_time = min(self._connection_backoff, self.MAX_BACKOFF)
                    logger.info(f"Retrying in {backoff_time} seconds...")
                    print(f"🔄 Will retry with fresh credentials in {backoff_time} seconds...")
                    
                    await asyncio.sleep(backoff_time)
                    # Increase backoff for next attempt
                    self._connection_backoff *= 2
                    
                    # Try again recursively
                    return await self.start()
                elif self._connection_attempts >= self.MAX_RETRIES:
                    logger.error(f"Maximum retry attempts ({self.MAX_RETRIES}) reached.")
                
                # Re-raise the exception to be handled by the outer try/except
                raise ws_error
            
            # Set up ICE candidate handler for sending to Ring
            @self._pc.on("icecandidate")
            async def on_ice_candidate(candidate):
                if candidate and self._ws and not self._stop.is_set():
                    await self._send_ice_candidate(candidate)
            
            # Start the signaling process
            session_jwt = await self._start_webrtc_session()
            
            # Start connection monitoring
            self._monitor_task = asyncio.create_task(self._monitor_connection_state())
            
            # Start keepalive task
            self._keepalive_task = asyncio.create_task(
                self._keepalive_webrtc_session(session_jwt)
            )
            
            # Start timeout guard
            self._timeout_task = asyncio.create_task(self._timeout_guard())
            
            # Start message handler
            self._message_handler_task = asyncio.create_task(self._monitor_message_handler())
            
            # Start network connection monitor to detect wake from sleep
            if self._enable_wake_detection:
                self._setup_wake_detection()
            
            # Add a ticket refresh task that periodically checks and refreshes the signalsocket ticket
            self._ticket_refresh_task = asyncio.create_task(self._ticket_refresh_loop())
            
            print("✅ Ring live view session started successfully")
            return True
            
        except Exception as e:
            logger.error(f"Error starting live view: {e}")
            print(f"❌ Error starting live view: {e}")
            
            # Check if we should retry
            if self._connection_attempts < self.MAX_RETRIES and not self._stop.is_set():
                # Calculate backoff time
                backoff_time = min(self._connection_backoff, self.MAX_BACKOFF)
                logger.info(f"Will retry in {backoff_time} seconds (attempt {self._connection_attempts} of {self.MAX_RETRIES})...")
                print(f"🔄 Will retry in {backoff_time} seconds...")
                
                await self.stop()
                await asyncio.sleep(backoff_time)
                
                # Increase backoff for next attempt
                self._connection_backoff *= 2
                
                # Try again recursively
                return await self.start()
            else:
                # We've exhausted our retries or were explicitly stopped
                logger.error("Giving up after failed connection attempts")
                await self.stop()
                return False

    async def _build_ws_url(self, ticket, region):
        """Build the WebSocket URL based on ticket and region."""
        # We must have a ticket to proceed - there is no legacy fallback
        if not ticket:
            raise ValueError("No ticket available for WebSocket connection")
            
        # Create a client ID
        client_id = f"ring_site-{uuid.uuid4()}"
        
        # Determine the host based on region
        if region:
            host = f"api.{region}.prod.signalling.ring.devices.a2z.com"
        else:
            host = "api.prod.signalling.ring.com"
        
        # Build the full WebSocket URL
        ws_url = (
            f"wss://{host}/ws?"
            f"{self.WS_PARAMS}&client_id={client_id}&token={ticket}"
        )
        print(f"🌐 Using Ring API endpoint with ticket-based authentication")
        logger.info(f"Using signalsocket ticket endpoint with region: {region or 'default'}")
        
        return ws_url

    async def _wait_for_ice_gathering(self):
        """Wait for ICE gathering to complete or until we have usable candidates."""
        logger.info("Waiting for ICE candidates to be gathered...")
        
        # Create futures to signal completion or having enough candidates
        gather_complete = asyncio.Future()
        have_candidates = asyncio.Future()
        candidate_count = 0
        
        # Track candidates as they come in
        @self._pc.on("icecandidate")
        def on_ice_candidate(candidate):
            nonlocal candidate_count
            if candidate:
                candidate_count += 1
                logger.debug(f"ICE candidate gathered: {candidate.candidate}")
                
                # After we have at least 2 candidates, we can proceed
                if candidate_count >= 2 and not have_candidates.done():
                    have_candidates.set_result(None)
        
        # Handle ICE gathering state changes
        @self._pc.on("icegatheringstatechange")
        def on_ice_gathering_state_change():
            if self._pc.iceGatheringState == "complete":
                if not gather_complete.done():
                    gather_complete.set_result(None)
        
        # Wait for either gathering completion or enough candidates
        try:
            # We'll wait for either condition with a timeout
            done, pending = await asyncio.wait(
                [gather_complete, have_candidates], 
                timeout=6.0,  # Increased timeout slightly
                return_when=asyncio.FIRST_COMPLETED
            )
            
            if gather_complete in done:
                logger.info("ICE gathering completed fully")
            elif have_candidates in done:
                logger.info(f"Proceeding with {candidate_count} ICE candidates")
            else:
                logger.warning("ICE gathering timed out, proceeding with available candidates")
                
        except Exception as e:
            logger.warning(f"Error during ICE gathering: {e}, proceeding anyway")
    
    async def _send_ice_candidate(self, candidate):
        """Send an ICE candidate to Ring."""
        if not self._ws or self._stop.is_set():
            return
            
        logger.debug(f"Sending ICE candidate: {candidate.candidate}")
        
        try:
            await self._ws.send(json.dumps({
                "dialog_id": self._dialog_id,
                "riid": uuid.uuid4().hex,
                "method": "icecandidate",
                "body": {
                    "doorbot_id": int(self._dev),
                    "candidate": {
                        "candidate": candidate.candidate,
                        "sdpMid": candidate.sdpMid,
                        "sdpMLineIndex": candidate.sdpMLineIndex,
                    }
                }
            }))
        except Exception as e:
            logger.error(f"Error sending ICE candidate: {e}")
    
    async def _start_webrtc_session(self):
        """
        Start the WebRTC session by sending the SDP offer.
        Returns the session JWT for keepalives.
        """
        if not self._ws or not self._pc:
            raise RuntimeError("WebSocket or PeerConnection not initialized")
            
        # Make sure we have a local description (SDP offer)
        if not self._pc.localDescription:
            raise ValueError("No local SDP description available")
            
        logger.info("Starting WebRTC session with SDP offer")
        
        # Send the initial live_view request with our SDP offer
        await self._ws.send(json.dumps({
            "dialog_id": self._dialog_id,
            "riid": uuid.uuid4().hex,
            "method": "live_view",
            "body": {
                "doorbot_id": int(self._dev),
                "sdp": self._pc.localDescription.sdp,
                "stream_options": {
                    "audio_enabled": False,
                    "video_enabled": True,
                    "ptz_enabled": False
                }
            }
        }))            # Handle responses from Ring
        session_jwt = None
        camera_started = False
        while True:
            if self._stop.is_set():
                raise RuntimeError("Client stopped during session setup")
                
            packet = await self._ws.recv()
            try:
                data = json.loads(packet)
            except json.JSONDecodeError:
                logger.error(f"Non-JSON reply: {packet[:120]}")
                raise ValueError("Invalid response from Ring server")
                
            logger.debug(f"Received message: {data.get('method')}")
            
            method = data.get("method")
            
            # Handle session created message
            if method == "session_created":
                session_jwt = data["body"]["session_id"]
                logger.info(f"Received session JWT: {session_jwt[:10]}...")
                continue
                
            # Handle SDP answer in live_view response
            if method == "live_view" and "sdp" in data["body"]:
                logger.info("Received SDP answer in live_view response")
                await self._pc.setRemoteDescription(
                    RTCSessionDescription(data["body"]["sdp"], "answer")
                )
                # We don't return yet - we wait for camera_started
                continue
                
            # Direct SDP message
            if method == "sdp":
                logger.info("Received direct SDP message")
                if "sdp" in data.get("body", {}):
                    await self._pc.setRemoteDescription(
                        RTCSessionDescription(data["body"]["sdp"], "answer")
                    )
                continue
                
            # Handle camera_started event - this indicates we're ready to receive video
            if method == "camera_started":
                logger.info("📷 Camera started and ready to stream")
                camera_started = True
                if session_jwt:
                    # Only return after we've both established the session and 
                    # confirmed the camera is started
                    return session_jwt
                continue
                
            # Handle notification messages
            if method == "notification":
                notification = data.get("body", {})
                text = notification.get("text", "No text")
                logger.info(f"📢 Received notification: {text}")
                
                # Check for important status notifications
                if "ready" in text.lower():
                    logger.info("Camera indicates it's ready")
                continue
                
            # Handle ICE candidates from Ring
            if method == "icecandidate":
                try:
                    c = data["body"]["candidate"]
                    await self._pc.addIceCandidate(
                        RTCIceCandidate(
                            sdpMid=c["sdpMid"],
                            sdpMLineIndex=c["sdpMLineIndex"],
                            candidate=c["candidate"]
                        )
                    )
                    logger.debug("Added ICE candidate from Ring")
                    continue
                except Exception as e:
                    logger.warning(f"Error adding ICE candidate: {e}")
                    continue
                    
            # Handle close messages
            if method == "close":
                if data.get("body", {}).get("reason", {}).get("code") == 26:
                    # Not ready yet, wait and continue
                    logger.debug("Got 'not ready yet' (code 26), waiting 300ms")
                    await asyncio.sleep(0.3)
                    continue
                else:
                    # Other close reason
                    reason = data.get("body", {}).get("reason", "No reason given")
                    raise RuntimeError(f"Ring closed connection: {reason}")
                    
            # Unknown message - log it but don't fail
            logger.info(f"Unrecognized message method: {method} - {json.dumps(data)[:100]}")
        
    async def _keepalive_webrtc_session(self, session_jwt):
        """Send periodic keepalive messages for the WebRTC session."""
        # The Ring session needs a ping every 5 seconds to keep the connection alive
        PING_INTERVAL = 5  # seconds
        ACTIVITY_INTERVAL = 15  # If no activity for 15 seconds, send a refresh
        consecutive_errors = 0
        max_errors = 3  # Maximum consecutive errors before triggering reconnection
        last_activity_time = time.time()
        
        while not self._stop.is_set():
            try:
                current_time = time.time()
                logger.debug("Sending ping keepalive")
                
                # Check if we need to send a "refresh" message due to inactivity
                if current_time - last_activity_time > ACTIVITY_INTERVAL:
                    logger.debug("Sending refresh due to inactivity")
                    try:
                        # Send a refresh message to prevent unanswered_timeout
                        await self._ws.send(json.dumps({
                            "method": "refresh",
                            "dialog_id": self._dialog_id,
                            "body": {
                                "doorbot_id": int(self._dev),
                                "session_id": session_jwt
                            }
                        }))
                        last_activity_time = current_time
                    except Exception as e:
                        logger.warning(f"Failed to send refresh message: {e}")
                
                # Send the ping message in the format from the TypeScript library
                await self._ws.send(json.dumps({
                    "method": "ping",
                    "dialog_id": self._dialog_id,
                    "body": {
                        "doorbot_id": int(self._dev),
                        "session_id": session_jwt
                    }
                }))
                
                # Reset error counter on successful ping
                consecutive_errors = 0
                
                # Wait for next ping interval with short timeouts to be responsive to cancellation
                remaining = PING_INTERVAL
                while remaining > 0 and not self._stop.is_set():
                    sleep_time = min(0.5, remaining)  # Sleep at most 0.5 seconds at a time
                    await asyncio.sleep(sleep_time)
                    remaining -= sleep_time
                
            except asyncio.CancelledError:
                logger.info("Keepalive task cancelled")
                break
            except Exception as e:
                if self._stop.is_set():
                    # Don't log errors if we're already stopping
                    break
                    
                consecutive_errors += 1
                logger.error(f"Keepalive error: {e} (attempt {consecutive_errors} of {max_errors})")
                
                if consecutive_errors >= max_errors:
                    logger.warning(f"Too many consecutive errors ({consecutive_errors}), triggering reconnection")
                    # Only stop the client and don't reconnect if we hit max_errors
                    # The outer loop in capture_engine will handle the reconnection
                    await self.stop()
                    break
                
                # For fewer consecutive errors, wait a bit and continue
                await asyncio.sleep(1)

    async def _ticket_refresh_loop(self):
        """Periodically check and refresh the signalsocket ticket."""
        backoff_time = 5  # Start with 5 seconds backoff
        
        while not self._stop.is_set():
            try:
                # Check if ticket needs refreshing (this will refresh if needed)
                await self._check_and_refresh_ticket()
                
                # Reset backoff on success
                backoff_time = 5
                
                # Wait for next check interval with short timeouts to be responsive to cancellation
                remaining = self.TICKET_CHECK_INTERVAL
                while remaining > 0 and not self._stop.is_set():
                    sleep_time = min(1.0, remaining)  # Sleep at most 1 second at a time
                    await asyncio.sleep(sleep_time)
                    remaining -= sleep_time
                    
            except asyncio.CancelledError:
                logger.debug("Ticket refresh loop cancelled")
                break
            except Exception as e:
                logger.error(f"Error in ticket refresh loop: {e}")
                
                # Use exponential backoff for errors
                logger.info(f"Will retry ticket refresh in {backoff_time} seconds")
                await asyncio.sleep(backoff_time)
                
                # Increase backoff time for next attempt (with a max)
                backoff_time = min(backoff_time * 2, self.MAX_BACKOFF)

    async def stop(self):
        """Stop the client and clean up resources."""
        if self._stop.is_set():
            return
            
        self._stop.set()
        logger.info("Stopping LiveViewClient")
        
        # Cancel all running tasks first
        for task_name in ('_keepalive_task', '_timeout_task', '_monitor_task', '_track_task', 
                         '_message_handler_task', '_ticket_refresh_task'):
            if hasattr(self, task_name) and getattr(self, task_name):
                task = getattr(self, task_name)
                if not task.done():
                    logger.debug(f"Canceling {task_name} task")
                    task.cancel()
                    try:
                        await asyncio.wait_for(task, timeout=2.0)
                    except (asyncio.CancelledError, asyncio.TimeoutError):
                        logger.debug(f"Task {task_name} canceled or timed out")
                    except Exception as e:
                        logger.warning(f"Error waiting for {task_name} task: {e}")
                setattr(self, task_name, None)
        
        # Close WebRTC connection with a timeout to prevent hanging
        if self._pc:
            logger.debug("Closing RTCPeerConnection")
            try:
                close_task = asyncio.create_task(self._pc.close())
                await asyncio.wait_for(close_task, timeout=3.0)
            except asyncio.TimeoutError:
                logger.warning("RTCPeerConnection close timed out")
            except Exception as e:
                logger.warning(f"Error closing RTCPeerConnection: {e}")
            self._pc = None
            
        # Close WebSocket connection
        if self._ws:
            logger.debug("Closing WebSocket connection")
            try:
                await self._ws.close()
            except Exception as e:
                logger.warning(f"Error closing WebSocket connection: {e}")
            self._ws = None
            
        # Close video sink
        try:
            logger.debug("Closing video sink")
            await self._sink.close()
        except Exception as e:
            logger.warning(f"Error closing video sink: {e}")
            
        # Stop connection monitor if active
        if self._connection_monitor:
            try:
                await self._connection_monitor.stop()
                self._connection_monitor = None
                logger.debug("Connection monitor stopped")
            except Exception as e:
                logger.warning(f"Error stopping connection monitor: {e}")
        
        logger.info("LiveViewClient stopped")

    # ——————————————————————————————————— internal helpers ——————————————————————————————————— #

    async def _on_track(self, track):
        """Forward decoded frames (or raw RTP if you prefer) to sink."""
        logger.info(f"Track {track.kind} received")
        
        # For MediaRecorder-based sinks, we need to add the track
        if hasattr(self._sink, '_rec') and hasattr(self._sink._rec, 'addTrack') and not self._track_added:
            self._sink._rec.addTrack(track)
            self._track_added = True
            logger.info("Added track to MediaRecorder")
            
            # Start the sink if it has a start method
            if hasattr(self._sink, 'start') and callable(self._sink.start):
                await self._sink.start()
                logger.info("Started video sink")
        
        frame_count = 0
        start_time = time.time()
        
        try:
            while not self._stop.is_set():
                try:
                    # Use wait_for with a timeout to make cancellation more responsive
                    frame = await asyncio.wait_for(track.recv(), timeout=1.0)
                    frame_count += 1
                    
                    # Log frame info at reasonable intervals
                    if frame_count == 1 or frame_count % 100 == 0:
                        elapsed = time.time() - start_time
                        fps = frame_count / elapsed if elapsed > 0 else 0
                        logger.info(f"Receiving video: {frame_count} frames, {fps:.1f} fps")
                    
                    await self._sink.write(frame)
                except asyncio.TimeoutError:
                    # Just a timeout, check stop flag and continue
                    continue
                except asyncio.CancelledError:
                    logger.info("Track receiving cancelled")
                    break
                except Exception as e:
                    if self._stop.is_set():
                        # If we're stopping, don't log expected errors
                        break
                    
                    logger.error(f"Error receiving frame: {e}")
                    if "Connection" in str(e) or any(x in str(e).lower() for x in ["closed", "shutdown", "reset"]):
                        # Connection errors should trigger a stop
                        logger.warning("Connection error in track handling, stopping client")
                        
                        # If this is a connection reset error, force ticket refresh on next attempt
                        if "reset by peer" in str(e).lower():
                            logger.warning("Connection reset by peer detected - forcing ticket refresh on next attempt")
                            self._ticket_updated_at = 0  # Force ticket refresh
                            
                        await self.stop()
                        break
                    
                    # For other errors, we'll log but continue trying
                    await asyncio.sleep(0.1)
        finally:
            logger.info(f"Track handler exiting after {frame_count} frames")
            if hasattr(track, 'stop') and callable(track.stop):
                try:
                    track.stop()
                except Exception as e:
                    logger.debug(f"Error stopping track: {e}")
            
            # Release any resources associated with the track
            if hasattr(self, '_track_task') and self._track_task:
                self._track_task = None

    async def _monitor_connection_state(self):
        """Monitor the ICE connection state and take action when it changes."""
        prev_state = None
        connection_established = False
        
        try:
            while not self._stop.is_set():
                state = self._pc.iceConnectionState if self._pc else None
                if not state:
                    await asyncio.sleep(0.5)
                    continue
                    
                # Log state changes
                if state != prev_state:
                    logger.info(f"ICE connection state changed: {state}")
                    prev_state = state
                    
                    # Handle specific states
                    if state == "failed":
                        logger.error("❌ ICE connection failed - the stream may not work")
                        # We don't stop immediately - sometimes Ring recovers
                        # If it doesn't recover within 10 seconds, we'll stop
                        try:
                            # Wait for recovery
                            recovery_timeout = 10  # seconds
                            recovery_deadline = asyncio.get_event_loop().time() + recovery_timeout
                            
                            while (asyncio.get_event_loop().time() < recovery_deadline and 
                                   not self._stop.is_set()):
                                await asyncio.sleep(1)
                                # Check if state has improved
                                if self._pc and self._pc.iceConnectionState in ["connected", "completed"]:
                                    logger.info("✅ ICE connection recovered")
                                    break
                            
                            # If we're still failed after the timeout, stop
                            if self._pc and self._pc.iceConnectionState == "failed" and not self._stop.is_set():
                                logger.error("❌ ICE connection failed permanently, stopping")
                                await self.stop()
                                break
                        except Exception as e:
                            logger.error(f"Error during connection recovery: {e}")
                        
                    elif state == "connected" or state == "completed":
                        if not connection_established:
                            connection_established = True
                            logger.info("🎉 WebRTC connection established successfully")
                    
                # Use shorter sleep time for better responsiveness to cancellation
                await asyncio.sleep(0.5)
        except asyncio.CancelledError:
            logger.debug("Connection monitor task cancelled")
        except Exception as e:
            if not self._stop.is_set():
                logger.error(f"Error in connection monitor: {e}")
                # Don't stop the client here, just let the monitor task end

    async def _monitor_message_handler(self):
        """Monitor WebSocket messages for errors and notifications."""
        consecutive_errors = 0
        max_errors = 3  # Maximum consecutive errors before triggering reconnection
        
        try:
            while not self._stop.is_set() and self._ws:
                try:
                    # Set a timeout to make this responsive to cancellation
                    message_task = asyncio.create_task(self._ws.recv())
                    try:
                        packet = await asyncio.wait_for(message_task, timeout=2.0)
                        
                        # Reset error counter on successful message
                        consecutive_errors = 0
                        
                        # Parse the message
                        try:
                            data = json.loads(packet)
                        except json.JSONDecodeError:
                            # Skip non-JSON messages silently
                            continue
                        
                        # Handle various message types
                        if "method" in data:
                            method = data["method"]
                            
                            # Skip logging for ping and pong messages
                            if method in ["ping", "pong"]:
                                continue
                                
                            logger.debug(f"Received message method: {method}")
                            
                            # Handle close messages as critical
                            if method == "close":
                                reason = data.get("body", {}).get("reason", {})
                                code = reason.get("code")
                                text = reason.get("text", "Unknown reason")
                                
                                logger.warning(f"Received close message: code={code}, reason={text}")
                                if code not in [26]:  # 26 is "not ready" which is handled elsewhere
                                    logger.error(f"Ring closed connection: {reason}")
                                    await self.stop()
                                    break
                            
                            # Log important messages at info level
                            if method in ["notification", "camera_started"]:
                                body = data.get("body", {})
                                text = body.get("text", "")
                                if text:
                                    logger.info(f"📢 Received notification: {text}")
                        
                    except asyncio.TimeoutError:
                        # Just a timeout, continue checking stop flag
                        continue
                        
                except asyncio.CancelledError:
                    logger.debug("Message monitor cancelled")
                    break
                    
                except Exception as e:
                    if self._stop.is_set():
                        # Don't log errors if we're stopping
                        break
                    
                    consecutive_errors += 1
                    
                    # Check if it's a known connection error
                    is_connection_error = "Connection" in str(e) or any(
                        x in str(e).lower() for x in ["closed", "shutdown", "reset", "404", "connection reset"]
                    )
                    
                    # Log connection errors but not too verbosely
                    if is_connection_error:
                        logger.warning(f"WebSocket connection error: {e} (attempt {consecutive_errors} of {max_errors})")
                        
                        # If we detect a connection reset or 404 error, it might be related to an expired ticket
                        if "reset by peer" in str(e).lower() or "404" in str(e):
                            logger.warning("Connection reset or 404 detected - likely expired ticket. Forcing refresh.")
                            # Force ticket refresh immediately
                            self._ticket_updated_at = 0
                            
                        if consecutive_errors >= max_errors:
                            logger.error("Too many consecutive WebSocket errors, stopping client")
                            await self.stop()
                            break
                    else:
                        # For other errors, log once but not repeatedly
                        logger.warning(f"WebSocket message error: {e}")
                        
                    # Wait a bit then continue
                    await asyncio.sleep(0.2)
                    
        except asyncio.CancelledError:
            logger.debug("Message monitor task cancelled")
        except Exception as e:
            if not self._stop.is_set():
                logger.error(f"Unhandled error in message monitor: {e}")
                await self.stop()

    def _setup_wake_detection(self):
        """Set up wake detection to reconnect after system sleep."""
        if self._connection_monitor is None:
            # Create the connection monitor
            self._connection_monitor = ConnectionMonitor(
                check_interval=self.CONNECTION_CHECK_INTERVAL
            )
            
            # Register wake callback
            self._connection_monitor.on_wake(self._handle_wake_event)
            
            # Start the connection monitor
            asyncio.create_task(self._connection_monitor.start())
            logger.info("Wake detection enabled - will reconnect after system sleep")
    
    async def _handle_wake_event(self):
        """Handle wake event by forcing a reconnection."""
        logger.info("System wake detected - reconnecting Ring livestream")
        
        # Force ticket refresh
        self._ticket_updated_at = 0
        
        # Try to stop gracefully, then restart
        try:
            await self.stop()
            
            # Wait a moment for network to stabilize
            await asyncio.sleep(2)
            
            # Reset connection counters to avoid hitting limits
            self._connection_attempts = 0
            self._connection_backoff = self.INITIAL_BACKOFF
            
            # Attempt to restart
            logger.info("Attempting to restart livestream after wake")
            restart_task = asyncio.create_task(self.start())
        except Exception as e:
            logger.error(f"Error handling wake event: {e}")
