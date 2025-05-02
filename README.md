# Ring Doorbell Recorder

A modern, event-driven application for capturing and storing events from Ring Doorbell devices. This application automatically records and organizes your Ring Doorbell events with a robust architecture that ensures reliable data capture.

## Project Overview

This application captures events (doorbell rings, motion detection, etc.) from Ring Doorbell and camera devices, processes them into structured data, and stores them securely. It uses a clean architecture approach with well-defined components and clear separation of concerns.

Key features:

- Token-based authentication with 2FA support
- Event-driven architecture using the Observer pattern
- Multiple storage backends (Database & File)
- Structured event data validation using Pydantic
- Comprehensive logging

## Installation

### Prerequisites

- Python 3.11+ (required)
- Conda (for environment management)
- Ring account credentials

### Setup

1. Clone the repository:

   ```bash
   git clone https://github.com/andremolnar/ring-doorbell-recorder.git
   cd ring-doorbell-recorder
   ```

2. Create and activate the conda environment:

   ```bash
   conda env create -f environment.yml
   conda activate ringdoorbell
   ```

3. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

4. Set up environment variables:
   ```bash
   # Create a .env file with your Ring credentials
   echo "RING_EMAIL=your_email@example.com" > .env
   echo "RING_PASSWORD=your_password" >> .env
   ```

## Usage

### Basic Usage

1. Activate the Conda environment:

   ```bash
   conda activate ringdoorbell
   ```

2. Run the application:

   ```bash
   python src/main.py
   ```

3. The application will:
   - Authenticate with Ring API
   - Discover your devices
   - Start listening for events
   - Capture and store events to configured storage backends

## Future Development

This project is actively seeking ways to make it more extensible for other users. Future enhancements will include:

- Plug-and-play architecture for custom event capture mechanisms
- User-defined storage locations and strategies
- Event transformation pipelines
- Integration with home automation systems
- Support for additional doorbell/camera vendors

If you're interested in contributing to these efforts, please open an issue or submit a pull request.

### Configuration

The application can be configured using environment variables:

| Variable          | Description              | Default               |
| ----------------- | ------------------------ | --------------------- |
| `RING_EMAIL`      | Ring account email       | -                     |
| `RING_PASSWORD`   | Ring account password    | -                     |
| `RING_TOKEN_PATH` | Path to token cache file | `~/.ring_token.cache` |
| `DATABASE_PATH`   | Path to SQLite database  | `./ringdoorbell.db`   |
| `STORAGE_PATH`    | Path for file storage    | `./captured_media`    |
| `LOGGING_LEVEL`   | Logging level            | `INFO`                |

## Architecture

The application follows a clean, modular architecture with well-defined components:

### Core Components

| Component             | Responsibility                                        |
| --------------------- | ----------------------------------------------------- |
| **App Manager**       | Bootstraps the system, wires components together      |
| **Auth Manager**      | Handles device authentication lifecycle               |
| **Low-Level API**     | Wrapper over Ring API protocol                        |
| **Event Listener**    | Subscribes to API events, dispatches to CaptureEngine |
| **Capture Engine**    | Processes events, fans out to storage implementations |
| **Storage Interface** | Abstract interface for storage implementations        |

### Event Handling

The application supports different processing strategies for different event types:

- **Ding Events**: Doorbell button presses
- **Motion Events**: Motion detection from cameras
- **On-Demand Events**: Manual live-view requests
- **Other Events**: Any other event types from the Ring API

Each event type can be processed differently, allowing for custom handling based on event characteristics.

### Storage Implementations

The application supports multiple storage backends:

- **DatabaseStorage**: SQLAlchemy-based database storage
- **FileStorage**: JSON file storage with date-based organization
- **NetworkStorage**: Remote storage (S3, SFTP) using fsspec

### Design Patterns

The application leverages several design patterns:

1. **Dependency Injection**

   - Components receive dependencies via constructor
   - Improves testability and flexibility

2. **Observer / Event Bus**

   - Event-driven architecture using PyEE
   - Decoupled event producers and consumers

3. **Strategy Pattern**

   - Interface for storage implementations
   - Easily swap or combine storage strategies

4. **Factory Pattern**
   - App Manager and main.py create and wire components

## API Documentation

### Core Interfaces

The application defines several core interfaces in `core/interfaces.py`:

- `IStorage`: Interface for storage implementations
- `IEventListener`: Interface for event listeners
- `IAuthManager`: Interface for authentication managers

### Event Data Models

Events are structured using Pydantic models:

- `EventData`: Base model for all events
- `DingEventData`: Model for doorbell rings
- `MotionEventData`: Model for motion detection
- `OnDemandEventData`: Model for live view requests

## Troubleshooting

### Common Issues

1. **Authentication Failures**

   - Check your Ring credentials in the environment variables
   - Delete the token cache file and try again
   - Ensure you can respond to 2FA prompts if enabled

2. **Storage Errors**

   - Ensure the storage paths exist and are writable
   - Check database connection strings
   - Verify network storage credentials

3. **Event Listener Issues**
   - Ensure your Ring devices are online
   - Check your network connection
   - Verify your Ring account has the necessary permissions

## Contributing

Contributions to this project are welcome! Please follow these steps:

1. Fork the repository
2. Create a feature branch
3. Add your changes
4. Run tests
5. Submit a pull request

Please follow our coding standards:

- PEP 8 for code style
- PEP 484 for type hints
- PEP 257 for docstrings

## License

This project is licensed under the MIT License - see the LICENSE file for details.
