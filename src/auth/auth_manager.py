"""Authentication Manager for Ring API."""

import asyncio
import getpass
import json
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from ring_doorbell import Auth, Ring, Requires2FAError, AuthenticationError

from ..core.interfaces import IAuthManager


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
        
        # Create token callback
        self._token_callback = self._create_token_callback(token_path)
        
        # Load FCM credentials if they exist
        self._load_fcm_credentials()
    
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
                print(f"✓ Loaded FCM credentials from {fcm_path}")
            except Exception as e:
                print(f"× Failed to load FCM credentials: {e}")
                self._fcm_credentials = None
    
    def _save_fcm_credentials(self, credentials: Dict[str, Any]) -> None:
        """
        Save Firebase Cloud Messaging credentials to disk.
        
        Args:
            credentials: FCM credentials to save
        """
        try:
            Path(self._fcm_token_path).write_text(json.dumps(credentials))
            self._fcm_credentials = credentials
            print(f"✓ Saved FCM credentials to {self._fcm_token_path}")
        except Exception as e:
            print(f"× Failed to save FCM credentials: {e}")
    
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
                print("✓ Successfully authenticated using saved token")
                return
            except Exception as e:
                print(f"× Token authentication failed: {e}")
                # Fall through to username/password auth
        
        # No saved token or token failed, authenticate with username/password
        if self._email and self._email != 'your_email@example.com' and self._password and self._password != 'your_password':
            print("Authenticating with configured credentials...")
            try:
                await self._authenticate_with_credentials(self._email, self._password)
                return
            except Exception as e:
                print(f"× Authentication failed: {e}")
                # Fall through to manual authentication
        
        # If we reach here, prompt user for credentials
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
            print("✓ Authentication successful")
        except Requires2FAError:
            print("⚠️ Two-factor authentication required")
            code = input("Enter the 2FA code from your email/text: ")
            try:
                await self._ring.auth.async_fetch_token(email, password, code)
                print("✓ Two-factor authentication successful")
            except Exception as e:
                error_msg = f"Two-factor authentication failed: {e}"
                if raise_error:
                    raise AuthenticationError(error_msg)
                print(f"× {error_msg}")
                self._auth = None
                self._ring = None
        except Exception as e:
            error_msg = f"Authentication failed: {e}"
            if raise_error:
                raise AuthenticationError(error_msg)
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
                print("✓ Authentication session closed successfully")
            except Exception as e:
                print(f"× Error closing authentication session: {e}")
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
    
    def get_fcm_credentials_callback(self) -> Callable[[Dict[str, Any]], None]:
        """
        Get a callback function for FCM credential updates.
        
        Returns:
            Callback function for FCM credential updates
        """
        def credentials_updated(credentials: Dict[str, Any]) -> None:
            self._save_fcm_credentials(credentials)
        
        return credentials_updated
