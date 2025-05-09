# Changelog

All notable changes to the Ring Doorbell project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Improved WebRTC live view client implementation:
  - Periodic signalsocket ticket refresh to prevent 404 errors
  - Robust reconnection logic with exponential backoff
  - Detailed documentation on WebSocket 404 error troubleshooting
- Enhanced AuthManager with account ID caching:
  - Added persistent cache for account ID to reduce API calls
  - Added memory and disk caching of account ID
  - Improved performance by eliminating redundant API requests
- Changed cache file locations from user's home directory to project root for better portability

### Fixed

- Fixed WebSocket 404 errors related to expired signalsocket tickets
- Implemented automatic ticket renewal for long-running sessions
- Added retry mechanism with exponential backoff for failed connections
- Improved detection of connection reset errors to trigger immediate ticket refresh
- Enhanced error handling in ticket refresh loop with exponential backoff

## [0.2.0] - 2025-05-08

### Added

- Event-specific handling for different Ring event types (ding, motion, on-demand)
- Support for "other" event type category to handle non-standard events
- Enhanced test suite for event-specific handling
- Event deduplication mechanism to prevent database constraint violations
- Improved error handling for storage operations
- Return values from storage save operations to indicate success/failure
- Updated documentation for event-specific processing capabilities

### Changed

- Enhanced WebRTC connection management:
  - Support for both modern and legacy Ring API endpoints
  - Automatic region detection for optimal server selection
  - Proper WebRTC negotiation following Ring's protocol
  - Real-time video streaming with frame rate monitoring
  - Configurable recording duration with battery-safe defaults
  - Resilient error handling and connection monitoring
- Modified event dispatching to prevent duplicate event processing
- Enhanced logging to differentiate between new events and duplicates
- Updated IStorage interface to return boolean status from save operations
- Refactored AppManager to use event-specific handler methods

### Fixed

- Fixed issue with duplicate event processing causing database errors
- Improved error handling in storage implementations
- Fixed ding event video recording by properly passing event_id to start_live_view method
- Fixed WebRTC connection issues by completely revising the Ring LiveViewClient:
  - Reversed the SDP offer/answer flow to follow Ring's expected pattern
  - Updated keepalive format from "action" to "method" with "ping" messages
  - Fixed ICE candidate gathering and exchange process
  - Added proper STUN servers for better connectivity
  - Improved connection monitoring and error recovery
- Added proper handling of video frames in the RecorderSink
- Ensured MediaRecorder is properly started and stopped asynchronously
- Added detailed connection state monitoring for WebRTC sessions

## [0.1.0] - 2025-04-26

### Added

- Initial project structure
- Ring API integration
- Event capture engine
- Multiple storage backends (Database, File, Network)
- Basic event processing
- Authentication management
- Device discovery
- Structured logging
