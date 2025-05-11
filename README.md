# Ring Doorbell Recorder

A modern, event-driven application for capturing and storing events from Ring Doorbell devices. This application automatically records and organizes your Ring Doorbell events with a robust architecture that ensures reliable data capture and video storage.

## Project Overview

This application captures events (doorbell rings, motion detection, etc.) from Ring Doorbell and camera devices, processes them into structured data, and stores them securely. As events happen, recordings are started and saved along with the event data. The application uses a clean architecture approach with well-defined components and clear separation of concerns.

Key features:

- Token-based authentication with 2FA support
- Event-driven architecture using the Observer pattern
- Multiple storage backends (Database & File)
- Automatic video download and storage for recorded events
- Structured event data validation using Pydantic
- Comprehensive logging
- Utility script for downloading historical videos

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

5. Initialize the database and run migrations:

   ```bash
   # Install alembic if not already installed
   pip install alembic

   # Generate the database and run all migrations
   alembic upgrade head
   ```

## Usage

### Basic Usage

1. Activate the Conda environment:

   ```bash
   conda activate ringdoorbell
   ```

2. Run the application:

   ```bash
   python src/run.py
   ```

3. The application will:
   - Authenticate with Ring API
   - Discover your devices
   - Start listening for events
   - Capture and store events to configured storage backends

### Testing Live View Video Recording

The repository includes a standalone script `live_view_example.py` to test on-demand video recording from your Ring doorbell or camera. This allows you to verify WebRTC connectivity and test the LiveView functionality separately from the main application.

```bash
# Activate the Conda environment first
conda activate ringdoorbell

# List all available Ring devices
python live_view_example.py --device-id list

# Capture a 30-second video from a specific device (default duration)
python live_view_example.py --device-id YOUR_DEVICE_ID

# Capture with custom duration (in seconds)
python live_view_example.py --device-id YOUR_DEVICE_ID --duration 60

# Save to a custom output directory
python live_view_example.py --device-id YOUR_DEVICE_ID --output-dir ./my_videos
```

Arguments:

- `--device-id` or `-d`: Ring device ID to stream from (required)
- `--duration` or `-t`: Duration of the stream in seconds (default: 30)
- `--output-dir` or `-o`: Directory to save the captured video (default: captured_media)

The captured video will be saved as an MP4 file with a timestamp filename in the specified output directory.

### Sleep Prevention Options

The application includes features to prevent system sleep while running to maintain network connectivity for continuous monitoring. You can control this behavior with command-line arguments:

```bash
# Run with default settings (prevent system sleep but allow display sleep)
python src/run.py

# Run with display sleep prevented (keeps screen on)
python src/run.py --sleep-mode all

# Run with only disk sleep prevented
python src/run.py --sleep-mode disk

# Run with sleep prevention completely disabled
python src/run.py --no-sleep-prevention
# or
python src/run.py --sleep-mode none
```

Sleep mode options:

- `--sleep-mode all`: Prevents all sleep (system, display, and disk)
- `--sleep-mode system`: Default - Prevents system sleep but allows display sleep (saves power)
- `--sleep-mode disk`: Prevents only disk sleep
- `--sleep-mode none`: Disables sleep prevention entirely
- `--no-sleep-prevention`: Disables sleep prevention entirely

#### How Sleep Prevention Works

The application uses platform-specific methods to prevent system sleep:

- On **macOS**: Uses the `caffeinate` utility with appropriate flags
- On **Linux**: Uses `systemd-inhibit` or falls back to `xdg-screensaver suspend`

Network connectivity is monitored to detect wake from sleep events, which allows the application to automatically reconnect when the system wakes up.

### Manual Event Testing

The repository includes standalone test scripts to simulate Ring events and verify the recording functionality:

- `test_motion_event.py`: Simulates a motion detection event and tests the full capture flow
- `test_ding_event.py`: Simulates a doorbell ring event and tests the full capture flow

To run these test scripts:

```bash
# Activate the Conda environment first
conda activate ringdoorbell

# Simulate a motion event
python test_motion_event.py

# Simulate a doorbell ring event
python test_ding_event.py
```

These scripts are useful for verifying that the capture engine correctly processes different event types and stores the associated video recordings.

### Database Management

The application uses SQLAlchemy with Alembic for database management:

1. Check migration status:

   ```bash
   alembic current
   ```

2. Create a new migration after model changes:

   ```bash
   alembic revision --autogenerate -m "Description of changes"
   ```

3. Apply migrations:

   ```bash
   alembic upgrade head
   ```

4. Rollback to a previous migration:

   ```bash
   alembic downgrade -1  # Go back one revision
   ```

5. View migration history:
   ```bash
   alembic history
   ```

## Future Development

This project is actively seeking ways to make it more extensible for other users. Future enhancements will include:

- Plug-and-play architecture for custom event capture mechanisms
- User-defined storage locations and strategies

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
| `PREVENT_SLEEP`   | Enable sleep prevention  | `true`                |

For more detailed configuration options, particularly regarding sleep prevention, see [Sleep Prevention Documentation](docs/sleep_prevention.md).

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
| **LiveView Client**   | Establishes WebRTC connections to Ring devices        |
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

## Documentation

Detailed documentation for specific components is available:

- [LiveView Client Documentation](docs/live_view_client.md): Explains the WebRTC-based live view functionality
- [Troubleshooting 4002 Errors](docs/troubleshooting_4002_error.md): Solutions for common WebRTC connection errors
- [Sleep Prevention Documentation](docs/sleep_prevention.md): Explains the sleep prevention and wake detection features

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

3. **WebRTC Connection Errors**

   - If you see a 4002 error when connecting to live view, see [Troubleshooting 4002 Errors](docs/troubleshooting_4002_error.md)
   - For detailed information about the WebRTC live view implementation, see [LiveView Client Documentation](docs/live_view_client.md)
   - Ensure your account ID is correctly retrieved
   - Check your message format matches Ring's 2025 API requirements

4. **Event Listener Issues**
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

## Prior Art

This project builds upon and was inspired by several excellent open-source libraries:

### [python-ring-doorbell](https://github.com/python-ring-doorbell/python-ring-doorbell)

This library provides core Ring API functionality and authentication support. Our project leverages it primarily for authentication and basic device interaction, while implementing our own event handling and video capture mechanisms.

### [ring-client-api](https://github.com/dgreif/ring/tree/main/packages/ring-client-api/streaming)

This JavaScript/TypeScript library by Dusty Greif provided significant insights into the WebRTC streaming implementation. Our LiveViewClient's WebRTC negotiation process was heavily inspired by the approach used in this library, adapted for Python with aiortc.

### [go2rtc](https://pkg.go.dev/github.com/AlexxIT/go2rtc/pkg/ring)

This Go library by AlexxIT provided valuable reference for understanding the Ring API's WebRTC implementation

## License

This project is licensed under the MIT License - see the LICENSE file for details.
