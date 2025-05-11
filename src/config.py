"""Configuration settings for the Ring Doorbell Capture Application."""

import os
from pathlib import Path

class Config:
    """Configuration class for the Ring Doorbell application."""
    
    # Class-level storage for dynamic updates
    _dynamic_settings = {}
    
    def __init__(self):
        """Initialize configuration with environment variables and defaults."""
        # Project identification
        self.user_agent = os.getenv('RING_USER_AGENT', "RingDoorbellProject-1.0")
        
        # Ring API credentials
        self.ring_email = os.getenv('RING_EMAIL', 'your_email@example.com')
        self.ring_password = os.getenv('RING_PASSWORD', 'your_password')
        
        # Token storage - use project root directory
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
        self.token_path = os.getenv('RING_TOKEN_PATH', 
                               os.path.join(project_root, 'ring_token.cache'))
        
        # Storage paths
        self.database_path = os.getenv('RING_DB_PATH', 
                                 str(Path.home() / 'ringdoorbell.db'))
        self.nas_storage_path = os.getenv('RING_NAS_PATH', 
                                    str(Path.home() / 'ring_videos'))
        
        # Database configuration
        self.database_path = os.getenv('DATABASE_PATH', 
                                  os.path.join(os.path.dirname(__file__), '..', 'ringdoorbell.db'))
        
        # Storage configuration
        self.nas_storage_path = os.getenv('NAS_STORAGE_PATH', 
                                     os.path.join(os.path.dirname(__file__), '..', 'captured_media'))
        
        # Ensure storage path exists
        os.makedirs(self.nas_storage_path, exist_ok=True)
        
        # Logging configuration
        self.logging_level = os.getenv('LOGGING_LEVEL', 'INFO')
        
        # Capture settings
        self.capture_interval = int(os.getenv('CAPTURE_INTERVAL', '60'))  # Time in seconds between captures
        self.max_storage_size = int(os.getenv('MAX_STORAGE_SIZE', str(1024 * 1024 * 1024)))  # 1 GB default
        
        # System sleep settings
        self.prevent_sleep = os.getenv('PREVENT_SLEEP', 'true').lower() != 'false'
    
    def get(self, key, default=None):
        """Get a configuration value with fallback to default."""
        # First check dynamic settings
        if key in self._dynamic_settings:
            return self._dynamic_settings[key]
        
        # Then check instance attributes
        if hasattr(self, key):
            return getattr(self, key)
        
        # Finally return default
        return default
    
    @classmethod
    def update(cls, settings_dict):
        """Update configuration with dynamic settings."""
        cls._dynamic_settings.update(settings_dict)
        return cls._dynamic_settings

# Global config instance
_config = None

def get_config():
    """Get the global configuration object.
    
    Returns:
        dict: A dictionary with configuration values
    """
    global _config
    if _config is None:
        config_obj = Config()
        _config = {
            "database_url": f"sqlite:///{config_obj.database_path}",
            "nas_storage_path": config_obj.nas_storage_path,
            "capture_interval": config_obj.capture_interval,
            "max_storage_size": config_obj.max_storage_size,
            "logging_level": config_obj.logging_level,
            "ring_email": config_obj.ring_email,
            "ring_password": config_obj.ring_password,
            "token_path": config_obj.token_path,
            "user_agent": config_obj.user_agent,
            "prevent_sleep": config_obj.prevent_sleep
        }
        
        # Add any dynamic settings
        _config.update(Config._dynamic_settings)
    
    return _config