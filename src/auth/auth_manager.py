"""Authentication Manager for Ring API."""

import asyncio
import getpass
import json
import logging
import aiohttp
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from ring_doorbell import Auth, Ring, Requires2FAError, AuthenticationError

from ..core.interfaces import IAuthManager

# Configure structured logging
logger = logging.getLogger("ring.auth")


class RingAuthManager(IAuthManager):
    """Authentication Manager for Ring API."""
    
    def __init__(
        self,
        user_agent: str,
        token_path: str,
        email: Optional[str] = None,
        password: Optional[str] = None,
        fcm_token_path: Optional[str] = None
    ):
        """
        Initialize the RingAuthManager.
        
        Args:
            user_agent: User agent string for Ring API calls
            token_path: Path to store the auth token
            email: Ring account email (optional)
            password: Ring account password (optional)
            fcm_token_path: Path to store FCM credentials (optional)
        """
        self._user_agent = user_agent
        self._token_path = token_path
        self._email = email
        self._password = password
        self._auth = None
        self._ring = None
        self._fcm_token_path = fcm_token_path or token_path.replace('.cache', '_fcm.cache')
        self._fcm_credentials = None
        self._cached_account_id = None  # Store account ID in memory
        
        # Path for caching account ID
        self._account_id_path = token_path.replace('.cache', '_account_id.cache')
        
        # Create token callback
        self._token_callback = self._create_token_callback(token_path)
        
        # Load FCM credentials if they exist
        self._load_fcm_credentials()
        
        # Load cached account ID if it exists
        self._load_cached_account_id()
    
    def _create_token_callback(self, token_path: str) -> Callable:
        """
        Create a token callback function.
        
        Args:
            token_path: Path to store the token
            
        Returns:
            Callback function
        """
        def save_token(token):
            Path(token_path).write_text(json.dumps(token))
        return save_token
    
    def _load_fcm_credentials(self) -> None:
        """
        Load Firebase Cloud Messaging credentials from disk if they exist.
        """
        fcm_path = Path(self._fcm_token_path)
        if fcm_path.is_file():
            try:
                self._fcm_credentials = json.loads(fcm_path.read_text())
                logger.info(f"Loaded FCM credentials from {fcm_path}")
            except Exception as e:
                logger.error(f"Failed to load FCM credentials: {e}")
                self._fcm_credentials = None
    
    def _load_cached_account_id(self) -> None:
        """
        Load cached account ID from disk if it exists.
        """
        account_id_path = Path(self._account_id_path)
        if account_id_path.is_file():
            try:
                self._cached_account_id = account_id_path.read_text().strip()
                logger.info(f"Loaded cached account ID: {self._cached_account_id}")
            except Exception as e:
                logger.error(f"Failed to load cached account ID: {e}")
                self._cached_account_id = None
    
    def _save_cached_account_id(self, account_id: str) -> None:
        """
        Save account ID to disk for future use.
        
        Args:
            account_id: Account ID to save
        """
        try:
            Path(self._account_id_path).write_text(account_id)
            self._cached_account_id = account_id
            logger.info(f"Saved account ID to {self._account_id_path}")
        except Exception as e:
            logger.error(f"Failed to save account ID: {e}")
    
    def _save_fcm_credentials(self, credentials: Dict[str, Any]) -> None:
        """
        Save Firebase Cloud Messaging credentials to disk.
        
        Args:
            credentials: FCM credentials to save
        """
        try:
            Path(self._fcm_token_path).write_text(json.dumps(credentials))
            self._fcm_credentials = credentials
            logger.info(f"Saved FCM credentials to {self._fcm_token_path}")
        except Exception as e:
            logger.error(f"Failed to save FCM credentials: {e}")
    
    async def authenticate(self) -> None:
        """
        Authenticate with the Ring API.
        
        Raises:
            AuthenticationError: If authentication fails
        """
        token_path_obj = Path(self._token_path)
        
        # Try token authentication first
        if token_path_obj.is_file():
            try:
                self._auth = Auth(
                    self._user_agent, 
                    json.loads(token_path_obj.read_text()), 
                    self._token_callback
                )
                self._ring = Ring(self._auth)
                await self._ring.async_create_session()
                logger.info("Successfully authenticated using saved token")
                return
            except Exception as e:
                logger.warning(f"Token authentication failed: {e}")
                # Fall through to username/password auth
        
        # No saved token or token failed, authenticate with username/password
        if self._email and self._email != 'your_email@example.com' and self._password and self._password != 'your_password':
            logger.info("Authenticating with configured credentials")
            try:
                await self._authenticate_with_credentials(self._email, self._password)
                return
            except Exception as e:
                logger.error(f"Authentication failed: {e}")
                # Fall through to manual authentication
        
        # If we reach here, prompt user for credentials
        logger.info("Prompting user for login credentials")
        print("\n🔑 Please log in to your Ring account:")
        manual_email = input("Email: ")
        manual_password = getpass.getpass("Password: ")
        
        # Try with manual credentials, but raise the exception if it fails
        await self._authenticate_with_credentials(manual_email, manual_password, raise_error=True)
    
    async def _authenticate_with_credentials(
        self, 
        email: str, 
        password: str, 
        raise_error: bool = False
    ) -> None:
        """
        Authenticate with the Ring API using email and password.
        
        Args:
            email: Ring account email
            password: Ring account password
            raise_error: Whether to raise exceptions
            
        Raises:
            AuthenticationError: If authentication fails and raise_error is True
        """
        self._auth = Auth(self._user_agent, None, self._token_callback)
        self._ring = Ring(self._auth)
        
        try:
            await self._ring.auth.async_fetch_token(email, password)
            logger.info("Authentication successful")
        except Requires2FAError:
            logger.info("Two-factor authentication required")
            print("⚠️ Two-factor authentication required")
            code = input("Enter the 2FA code from your email/text: ")
            try:
                await self._ring.auth.async_fetch_token(email, password, code)
                logger.info("Two-factor authentication successful")
                print("✓ Two-factor authentication successful")
            except Exception as e:
                error_msg = f"Two-factor authentication failed: {e}"
                if raise_error:
                    raise AuthenticationError(error_msg)
                logger.error(f"Two-factor authentication failed: {e}")
                print(f"× {error_msg}")
                self._auth = None
                self._ring = None
        except Exception as e:
            error_msg = f"Authentication failed: {e}"
            if raise_error:
                raise AuthenticationError(error_msg)
            logger.error(f"Authentication failed: {e}")
            print(f"× {error_msg}")
            self._auth = None
            self._ring = None
    
    async def is_authenticated(self) -> bool:
        """
        Check if the API is authenticated.
        
        Returns:
            True if authenticated, False otherwise
        """
        if not self._ring:
            return False
        
        try:
            # Simple test to check authentication
            await self._ring.async_update_data()
            return True
        except Exception:
            return False
    
    @property
    def api(self) -> Ring:
        """
        Get the authenticated Ring API instance.
        
        Returns:
            Authenticated Ring API instance
            
        Raises:
            AuthenticationError: If not authenticated
        """
        if not self._ring:
            raise AuthenticationError("Not authenticated")
        return self._ring
    
    async def close(self) -> None:
        """Close the authentication session and cleanup resources."""
        if self._auth:
            try:
                # Get direct access to the aiohttp session if it exists
                session = None
                if self._ring and hasattr(self._ring, 'auth') and hasattr(self._ring.auth, '_session'):
                    session = self._ring.auth._session
                
                # Close the auth session first
                await self._auth.async_close()
                
                # Explicitly close the aiohttp session if it's still open
                if session and not session.closed:
                    await asyncio.sleep(0.5)  # Small delay to allow other tasks to finish
                    await session.close()
                    # Wait for all connections to be closed
                    await asyncio.sleep(0.5)
                
                # Clear reference to the Ring API instance to help with garbage collection
                self._ring = None
                self._auth = None
                logger.info("Authentication session closed successfully")
            except Exception as e:
                logger.error(f"Error closing authentication session: {e}")
                # Setting to None even if there was an error to help with garbage collection
                self._ring = None
                self._auth = None
    
    @property
    def fcm_credentials(self) -> Optional[Dict[str, Any]]:
        """
        Get the FCM credentials.
        
        Returns:
            FCM credentials if available, None otherwise
        """
        return self._fcm_credentials
    
    def get_token(self) -> Optional[str]:
        """
        Get the Ring API access token.
        
        Returns:
            Access token if available, None otherwise
        """
        if self._auth and hasattr(self._auth, '_token'):
            return self._auth._token.get("access_token")
        
        # Try to load from the token file as fallback
        try:
            token_path = Path(self._token_path)
            if token_path.exists():
                token_data = json.loads(token_path.read_text())
                return token_data.get("access_token")
        except Exception as e:
            logger.error(f"Failed to load token from file: {e}")
            
        return None
    
           
    async def get_account_id(self) -> str:
        """
        Get the Ring account ID for the authenticated user.
        
        Returns:
            Account ID for the authenticated user
            
        Raises:
            AuthenticationError: If account ID cannot be retrieved
        """
        # Return cached account ID if available
        if self._cached_account_id:
            logger.info(f"Using cached account ID: {self._cached_account_id}")
            return self._cached_account_id
            
        try:
            # Get the account ID directly from the API using the reliable devices endpoint
            async with aiohttp.ClientSession() as session:
                headers = {"Authorization": f"Bearer {self.get_token()}"}
                
                logger.info("Getting account ID from ring_devices endpoint")
                response = await session.get(
                    "https://api.ring.com/clients_api/ring_devices",
                    headers=headers
                )
                
                # Check response status
                if response.status != 200:
                    error_msg = f"Failed to get account ID: API returned status {response.status}"
                    logger.error(f"Failed to get account ID from API: status {response.status}")
                    raise ValueError(error_msg)
                
                # Parse the response JSON
                devices_data = await response.json()
                
                # Process device data to find account ID
                # Look for doorbot devices first (Ring doorbells)
                if "doorbots" in devices_data and isinstance(devices_data["doorbots"], list) and len(devices_data["doorbots"]) > 0:
                    for doorbot in devices_data["doorbots"]:
                        if "owner" in doorbot and isinstance(doorbot["owner"], dict) and "id" in doorbot["owner"]:
                            owner_id = doorbot["owner"]["id"]
                            logger.info(f"Found account ID from doorbot: {owner_id}")
                            # Cache the account ID for future use
                            self._save_cached_account_id(str(owner_id))
                            return str(owner_id)
                
                # If no doorbots, try chimes
                if "chimes" in devices_data and isinstance(devices_data["chimes"], list) and len(devices_data["chimes"]) > 0:
                    for chime in devices_data["chimes"]:
                        if "owner" in chime and isinstance(chime["owner"], dict) and "id" in chime["owner"]:
                            owner_id = chime["owner"]["id"]
                            logger.info(f"Found account ID from chime: {owner_id}")
                            # Cache the account ID for future use
                            self._save_cached_account_id(str(owner_id))
                            return str(owner_id)
                
                # If no doorbots or chimes, check other device types
                for device_type in devices_data:
                    if isinstance(devices_data[device_type], list):
                        for device in devices_data[device_type]:
                            if isinstance(device, dict):
                                if "owner" in device and isinstance(device["owner"], dict) and "id" in device["owner"]:
                                    owner_id = device["owner"]["id"]
                                    logger.info(f"Found account ID from {device_type} device: {owner_id}")
                                    # Cache the account ID for future use
                                    self._save_cached_account_id(str(owner_id))
                                    return str(owner_id)
                                if "owner_id" in device:
                                    logger.info(f"Found direct owner_id property: {device['owner_id']}")
                                    # Cache the account ID for future use
                                    self._save_cached_account_id(str(device["owner_id"]))
                                    return str(device["owner_id"])
                
                # If we got here, no account ID was found in the response
                error_msg = "No account ID found in the devices response"
                logger.error("No account ID found in API response")
                raise ValueError(error_msg)
                
        except Exception as e:
            raise AuthenticationError(f"Failed to get account ID: {e}")
    
    def get_fcm_credentials_callback(self) -> Callable[[Dict[str, Any]], None]:
        """
        Get a callback function for FCM credential updates.
        
        Returns:
            Callback function for FCM credential updates
        """
        def credentials_updated(credentials: Dict[str, Any]) -> None:
            self._save_fcm_credentials(credentials)
        
        return credentials_updated
    
    async def refresh_token(self) -> bool:
        """
        Explicitly refresh the Ring API access token.
        
        This method forces a token refresh using the refresh token in the current token data.
        It's useful for proactively refreshing tokens before they expire or when a token
        related error occurs.
        
        Returns:
            bool: True if token was successfully refreshed, False otherwise
            
        Raises:
            AuthenticationError: If there's no active authentication to refresh
        """
        if not self._auth or not self._ring:
            raise AuthenticationError("No active authentication to refresh")
            
        try:
            logger.info("Refreshing Ring API token")
            # Request the underlying Auth instance to refresh its token
            # This will implicitly call our token_callback when successful
            if hasattr(self._auth, 'async_refresh_tokens') and callable(getattr(self._auth, 'async_refresh_tokens')):
                await self._auth.async_refresh_tokens()
                logger.info("Token refreshed successfully")
                return True
            else:
                # Fallback: If the Auth class doesn't have a dedicated refresh method,
                # we can try to create a new session which often triggers token validation/refresh
                await self._ring.async_create_session()
                logger.info("Session refreshed successfully")
                return True
        except Exception as e:
            logger.error(f"Token refresh failed: {e}")
            
            # If refresh fails, but we still have credentials, try to re-authenticate
            if self._email and self._email != 'your_email@example.com' and self._password and self._password != 'your_password':
                try:
                    logger.info("Attempting re-authentication with stored credentials")
                    await self._authenticate_with_credentials(self._email, self._password)
                    logger.info("Re-authentication successful")
                    return True
                except Exception as re_auth_error:
                    logger.error(f"Re-authentication failed: {re_auth_error}")
            
            return False
