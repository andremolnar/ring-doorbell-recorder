# Sleep Prevention and Wake Detection

This document explains the sleep prevention and wake detection features in the Ring Doorbell application.

## Overview

To maintain reliable connections to Ring devices and prevent data loss, the application includes mechanisms to:

1. Prevent the system from entering sleep modes that would disrupt network connectivity
2. Detect when the system wakes from sleep and automatically reconnect

## Sleep Prevention Modes

The application supports different sleep prevention modes to balance power consumption with reliability:

| Mode                    | Description                                    | Usage Scenario                                                                   |
| ----------------------- | ---------------------------------------------- | -------------------------------------------------------------------------------- |
| **PREVENT_ALL**         | Prevents system, display, and disk sleep       | Use when absolute reliability is required and power consumption is not a concern |
| **PREVENT_SYSTEM_ONLY** | Prevents system sleep but allows display sleep | Default setting - balances power consumption with reliability                    |
| **PREVENT_DISK_ONLY**   | Prevents only disk from sleeping               | Minimal intervention, may not maintain connectivity                              |
| **CUSTOM**              | User-defined prevention flags                  | Advanced usage for specific requirements                                         |

## Platform-Specific Implementation

### macOS

On macOS, sleep prevention uses the `caffeinate` command-line utility:

| Flag | Function                                                |
| ---- | ------------------------------------------------------- |
| `-i` | Prevents idle system sleep                              |
| `-d` | Prevents display sleep                                  |
| `-m` | Prevents disk sleep                                     |
| `-s` | Prevents system sleep (including sleep when on battery) |

Example commands:

- Prevent all sleep: `caffeinate -i -d -m -s`
- Prevent system sleep only: `caffeinate -i -s`

### Linux

On Linux, sleep prevention uses `systemd-inhibit` or falls back to `xdg-screensaver`:

```bash
# Prevent all sleep
systemd-inhibit --what=sleep:idle:handle-lid-switch --who=RingDoorbell --why="Capturing video" --mode=block sleep infinity

# Prevent system sleep only
systemd-inhibit --what=sleep:idle --who=RingDoorbell --why="Capturing video" --mode=block sleep infinity
```

## Wake Detection

The application includes a `ConnectionMonitor` utility that monitors network connectivity to detect system wake events. When a wake event is detected:

1. The application forces a refresh of authentication tokens
2. Any active connections are properly closed
3. After a short delay to allow network stabilization, connections are reestablished
4. The application resumes normal operation

This approach ensures the application can recover gracefully from system sleep events without manual intervention.

## Configuration

Sleep prevention can be configured through:

1. Command-line arguments:

   ```bash
   # Prevent all sleep
   python src/run.py --sleep-mode all

   # Prevent system sleep only (default)
   python src/run.py --sleep-mode system

   # Disable sleep prevention
   python src/run.py --no-sleep-prevention
   ```

2. Environment variables:

   ```bash
   # Set to false to disable sleep prevention
   export PREVENT_SLEEP=false
   ```

3. Programmatically during runtime:
   ```python
   # Change sleep mode at runtime
   app_manager.set_sleep_mode(SleepMode.PREVENT_SYSTEM_ONLY)
   ```

## Power Consumption Considerations

Different sleep prevention modes have different impacts on power consumption:

- **PREVENT_ALL**: Highest power consumption, screen stays on
- **PREVENT_SYSTEM_ONLY**: Moderate power consumption, screen can turn off
- **PREVENT_DISK_ONLY**: Lowest power consumption, but may not maintain connectivity
- **None (disabled)**: No additional power consumption, but connection may be lost during sleep

Choose the mode that best balances your reliability needs with power constraints.

## Testing Sleep Prevention

The repository includes a test script to verify the sleep prevention functionality:

```bash
# Activate the conda environment first
conda activate ringdoorbell

# Test with default settings (system-only mode)
python test_sleep_prevention.py

# Test with display sleep prevention (all mode)
python test_sleep_prevention.py --mode all

# Test with a shorter duration (30 seconds)
python test_sleep_prevention.py --duration 30

# Test with custom flags (macOS example)
python test_sleep_prevention.py --mode custom --custom-flags "-i"
```

The test script will start sleep prevention with the specified mode, run for the specified duration, and then stop. This allows you to verify that the sleep prevention is working correctly on your system.

## Troubleshooting

### Common Issues

1. **System still sleeps despite prevention**:

   - Verify the application has appropriate permissions
   - Check system power settings for overrides
   - Try a more aggressive sleep prevention mode

2. **High power consumption**:

   - Switch to PREVENT_SYSTEM_ONLY mode to allow display sleep
   - Consider running on a device with constant power

3. **Application doesn't reconnect after wake**:
   - Check if wake detection is enabled (`enable_wake_detection=True`)
   - Verify network connectivity is available after wake
   - Increase delay before reconnection attempt (default: 2 seconds)
