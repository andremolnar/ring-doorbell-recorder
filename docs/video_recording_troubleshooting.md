# Ring Doorbell Video Recording Troubleshooting

This document provides guidance for troubleshooting issues with the Ring Doorbell application's video recording functionality.

## Common Issues

### Cannot Access Ring API Token

If you're seeing an error message like "Cannot access Ring API token" when a motion or ring event is detected, it's likely due to authentication issues.

**Solution:**

1. Make sure your Ring account credentials are correctly configured in your `.env` file or configuration
2. Check that you have a valid `ring_token.cache` file in your application directory
3. Try running the application with the `--refresh-token` flag to force a token refresh

### Videos Not Associated with Events

Sometimes videos are recorded but not properly associated with their corresponding events.

**Symptoms:**

- Videos appear in the `live_view` directory but not in event-specific directories
- Events don't show video playback options in the UI
- Event JSON files have `has_video` set to `false`

**Solution:**

1. Run the automatic fix utility:
   ```bash
   python fix_video_associations.py
   ```
2. For specific events or time ranges:

   ```bash
   python fix_video_associations.py --since 2025-05-01 --device-id 589851570
   ```

3. To see what would be fixed without making changes:
   ```bash
   python fix_video_associations.py --dry-run
   ```

### No Videos Being Recorded

If no videos are being recorded at all:

**Troubleshooting steps:**

1. Check Ring API connectivity by running `test_motion_event.py`
2. Ensure you have proper permissions for the `captured_media` directory
3. Look for errors in the application logs related to WebRTC or LiveView
4. Verify your Ring subscription allows for video recordings

## Advanced Troubleshooting

### Manual Video Association

If the automatic fix utility doesn't resolve your issue, you can manually copy videos:

1. Find the source video in the `live_view` directory
2. Create or locate the event directory in `captured_media/[device_id]/[event_type]/[event_id]`
3. Copy the video file to the event directory and rename it to `video.mp4`
4. Update the event's JSON file to set `has_video` to `true` and `video_path` to the new location

### Live View Debug Mode

To debug live view issues:

```bash
python live_view_example.py --device-id YOUR_DEVICE_ID --debug
```

This will run a standalone live view session and output detailed debugging information.

## Reporting Issues

When reporting issues with video recording:

1. Include the specific error messages from the logs
2. Run `test_motion_event.py` and include its output
3. Note which directories do or don't contain video files
4. Specify your Ring subscription type

For additional help, please file an issue on the GitHub repository with these details.
