# Changelog

All notable changes to the Ring Doorbell project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Event-specific handling for different Ring event types (ding, motion, on-demand)
- Support for "other" event type category to handle non-standard events
- Enhanced test suite for event-specific handling
- Event deduplication mechanism to prevent database constraint violations
- Improved error handling for storage operations
- Return values from storage save operations to indicate success/failure
- Updated documentation for event-specific processing capabilities

### Changed

- Modified event dispatching to prevent duplicate event processing
- Enhanced logging to differentiate between new events and duplicates
- Updated IStorage interface to return boolean status from save operations
- Refactored AppManager to use event-specific handler methods

### Fixed

- Fixed issue with duplicate event processing causing database errors
- Improved error handling in storage implementations

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
