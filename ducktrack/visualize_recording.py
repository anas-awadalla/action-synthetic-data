import cv2
import json
import argparse
import os
from collections import deque

# --- Configuration ---
TEXT_COLOR = (255, 255, 255)  # White text
FONT = cv2.FONT_HERSHEY_SIMPLEX
FONT_SCALE = 0.5
FONT_THICKNESS = 1
TEXT_POSITION = (30, 30)  # Starting position for text
LINE_HEIGHT = 25  # Space between lines of text
TEXT_DURATION_FRAMES = 1  # How many frames the text persists
VIDEO_FILENAME = "recording.mp4"
EVENTS_FILENAME = "events.jsonl"
OUTPUT_FILENAME = "visualization.mp4"
FRAMES_DEBUG_DIR = "frames_debug"
OUTPUT_FPS = 30.0

# --- Mouse visualization settings ---
CLICK_COLOR = (0, 0, 255)    # Red for clicks
MOVE_COLOR = (0, 255, 0)     # Green for moves
CURSOR_RADIUS = 10           # Size of the cursor indicator
CURSOR_THICKNESS = 2         # Thickness of the cursor circle
CLICK_HIGHLIGHT_FRAMES = 5   # How many frames to highlight a click

def load_events(jsonl_path):
    """Loads events from the JSONL file and normalizes timestamps."""
    events = []
    recording_dir = os.path.dirname(jsonl_path)
    metadata_path = os.path.join(recording_dir, "metadata.json")

    try:
        with open(jsonl_path, 'r') as f:
            for line in f:
                try:
                    events.append(json.loads(line.strip()))
                except json.JSONDecodeError:
                    print(f"Warning: Skipping invalid JSON line: {line.strip()}")
    except FileNotFoundError:
        print(f"Error: Events file not found at {jsonl_path}")
        return None, None

    if not events:
        print("Error: No events found in the file.")
        return None, None

    first_event_time = events[0]['time_stamp']
    baseline_timestamp_sec = None

    try:
        with open(metadata_path, 'r') as f:
            metadata = json.load(f)
            obs_start_ts_sec = metadata.get('obs_record_state_timings', {}).get('OBS_WEBSOCKET_OUTPUT_STARTED', [None])[0]
            if obs_start_ts_sec is not None:
                baseline_timestamp_sec = obs_start_ts_sec
                print(f"Using OBS recording start time ({obs_start_ts_sec:.3f}s) as baseline.")
            else:
                print("Warning: 'OBS_WEBSOCKET_OUTPUT_STARTED' not found in metadata.")
    except (FileNotFoundError, json.JSONDecodeError, KeyError, IndexError, TypeError) as e:
        print(f"Warning: Error reading OBS start time from metadata ({e}).")

    if baseline_timestamp_sec is None:
        print(f"Falling back to first event timestamp ({first_event_time:.3f}s) as baseline.")
        baseline_timestamp_sec = first_event_time

    for event in events:
        event['relative_time_sec'] = event['time_stamp'] - baseline_timestamp_sec
        
    events.sort(key=lambda x: x['relative_time_sec'])
    
    print(f"Loaded and normalized {len(events)} events.")
    
    t_start_sec = 0
    for event in events:
        if event.get('action'):
            t_start_sec = event['relative_time_sec']
            print(f"Action recording starts around {t_start_sec:.2f} seconds.")
            break
             
    return events, t_start_sec

def create_visualization(event, expiry_frame):
    """Creates a visualization entry for any event type."""
    # Capture any event with an action
    if not event.get('action'):
        return None
    
    # Skip scroll events where both dx and dy are 0
    if event.get('action') == 'scroll' and event.get('dx') == 0 and event.get('dy') == 0:
        return None
        
    # Create a visualization entry with the full event data
    visualization = {
        'expiry': expiry_frame,
        'event_data': event,
        'timestamp': event.get('relative_time_sec', 0)
    }

    return visualization

def get_event_identifier(event):
    """Generate a unique identifier for an event based on its type and target."""
    action = event.get('action')
    if action == 'press' or action == 'click':
        return f"{action}_{event.get('name')}"
    return None

def ensure_dir_exists(directory):
    """Create directory if it doesn't exist."""
    if not os.path.exists(directory):
        try:
            os.makedirs(directory)
            print(f"Created directory: {directory}")
        except OSError as e:
            print(f"Error creating directory {directory}: {e}")
            return False
    return True

def main(recording_dir):
    events_path = os.path.join(recording_dir, EVENTS_FILENAME)
    video_path = os.path.join(recording_dir, VIDEO_FILENAME)
    output_path = os.path.join(recording_dir, OUTPUT_FILENAME)
    debug_frames_dir = os.path.join(recording_dir, FRAMES_DEBUG_DIR)

    if not ensure_dir_exists(debug_frames_dir):
        debug_frames_dir = None
        print("Frame debug saving disabled due to directory creation failure.")

    if not os.path.isdir(recording_dir):
        print(f"Error: Recording directory not found: {recording_dir}")
        return
    if not os.path.isfile(video_path):
        print(f"Error: Video file not found: {video_path}")
        return

    events, recording_start_sec = load_events(events_path)
    if not events:
        return

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"Error: Could not open video file {video_path}")
        return

    fps = cap.get(cv2.CAP_PROP_FPS)
    frame_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    frame_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    
    if fps <= 0 or frame_width <= 0 or frame_height <= 0:
        print(f"Error: Invalid video properties (FPS: {fps}, Size: {frame_width}x{frame_height}).")
        cap.release()
        return

    frame_chunk_size = int(round(fps / OUTPUT_FPS))
    if frame_chunk_size < 1:
        frame_chunk_size = 1
    print(f"Input FPS: {fps:.2f}, Output FPS: {OUTPUT_FPS:.2f}, Writing every {frame_chunk_size}th frame.")
    print(f"Video properties: {frame_width}x{frame_height} @ {fps:.2f} FPS, Total Frames: {total_frames}")

    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter(output_path, fourcc, OUTPUT_FPS, (frame_width, frame_height))

    active_visualizations = deque()
    event_idx = 0
    frame_count = 0
    output_frame_count = 0
    frame_action_map = {}
    actions_in_chunk = []
    
    # Track press events to match with release events
    pending_press_events = {}  # key: event_id, value: (frame_num, event_data)
    completed_press_release_pairs = {}  # key: frame_num, value: list of (press_event, release_event) pairs

    # First pass: collect all press and release events to match them
    for i, event in enumerate(events):
        action = event.get('action')
        if action == 'press' or action == 'click':
            event_id = get_event_identifier(event)
            if event_id and event.get('pressed') is True:
                # This is a press event, store it
                frame_time = event['relative_time_sec']
                frame_num = int(frame_time * fps)
                pending_press_events[event_id] = (frame_num, event)
            elif event_id and event.get('pressed') is False:
                # This is a release event, find matching press
                frame_time = event['relative_time_sec']
                release_frame_num = int(frame_time * fps)
                
                if event_id in pending_press_events:
                    press_frame_num, press_event = pending_press_events[event_id]
                    
                    # If press and release are on different frames, add to completed pairs
                    if press_frame_num != release_frame_num:
                        if release_frame_num not in completed_press_release_pairs:
                            completed_press_release_pairs[release_frame_num] = []
                        completed_press_release_pairs[release_frame_num].append((press_event, event))
                        
                        # Remove from pending
                        del pending_press_events[event_id]

    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            break

        current_frame_time_sec = frame_count / fps
        frame_end_time_sec = (frame_count + 1) / fps

        # Remove expired visualizations
        while active_visualizations and active_visualizations[0]['expiry'] <= frame_count:
            active_visualizations.popleft()

        # Add new visualizations for this frame
        while event_idx < len(events):
            event = events[event_idx]
            event_time_sec = event['relative_time_sec']

            if event_time_sec >= frame_end_time_sec:
                break

            expiry_frame = frame_count + TEXT_DURATION_FRAMES
            
            # Check if this is a release event that should be merged with a press
            if event.get('action') in ['press', 'click'] and event.get('pressed') is False:
                event_id = get_event_identifier(event)
                if event_id and event_id in pending_press_events:
                    # Skip this release event as it will be handled in the merge logic below
                    event_idx += 1
                    continue
            
            viz = create_visualization(event, expiry_frame)
            if viz:
                active_visualizations.append(viz)
                actions_in_chunk.append(viz)
                
            event_idx += 1

        # Check if we need to merge press/release events for this frame
        if frame_count in completed_press_release_pairs:
            for press_event, release_event in completed_press_release_pairs[frame_count]:
                # Create a merged event
                merged_event = press_event.copy()
                merged_event['action'] = press_event.get('action') + "_complete"
                merged_event['press_time'] = press_event.get('relative_time_sec')
                merged_event['release_time'] = release_event.get('relative_time_sec')
                merged_event['duration'] = release_event.get('relative_time_sec') - press_event.get('relative_time_sec')
                
                # Add to this frame's visualizations
                viz = create_visualization(merged_event, frame_count + TEXT_DURATION_FRAMES)
                if viz:
                    active_visualizations.append(viz)
                    actions_in_chunk.append(viz)

        # Draw visualizations and write frame conditionally
        if frame_count % frame_chunk_size == 0:
            # Draw text for all actions in this chunk
            # Create a semi-transparent background for text
            text_overlay = frame.copy()
            cv2.rectangle(text_overlay, (10, 10), (frame_width - 10, 10 + (len(actions_in_chunk) + 1) * LINE_HEIGHT), 
                         (0, 0, 0), -1)
            alpha = 0.7
            frame = cv2.addWeighted(text_overlay, alpha, frame, 1 - alpha, 0)
            
            # Add frame number and timestamp
            cv2.putText(frame, f"Frame: {frame_count} | Time: {current_frame_time_sec:.2f}s", 
                       (TEXT_POSITION[0], TEXT_POSITION[1]), FONT, FONT_SCALE, TEXT_COLOR, FONT_THICKNESS, cv2.LINE_AA)
            
            # Highlight cursor positions for move and click events
            for viz in active_visualizations:
                event_data = viz['event_data']
                action_type = event_data.get('action', '')
                
                # Draw cursor indicators for move and click actions
                if action_type in ['move', 'click'] and 'x' in event_data and 'y' in event_data:
                    x, y = int(event_data.get('x')), int(event_data.get('y'))
                    
                    # Use different colors and styles for different action types
                    if action_type == 'click':
                        # Draw a more prominent indicator for clicks
                        cv2.circle(frame, (x, y), CURSOR_RADIUS, CLICK_COLOR, CURSOR_THICKNESS)
                        # Add crosshair
                        cv2.line(frame, (x - CURSOR_RADIUS - 5, y), (x + CURSOR_RADIUS + 5, y), CLICK_COLOR, 2)
                        cv2.line(frame, (x, y - CURSOR_RADIUS - 5), (x, y + CURSOR_RADIUS + 5), CLICK_COLOR, 2)
                    elif action_type == 'move':
                        # Simple circle for move events
                        cv2.circle(frame, (x, y), CURSOR_RADIUS, MOVE_COLOR, CURSOR_THICKNESS)
            
            # Add each action as text
            line_pos = TEXT_POSITION[1] + LINE_HEIGHT
            for idx, viz in enumerate(actions_in_chunk):
                event_data = viz['event_data']
                action_type = event_data.get('action', 'unknown')
                
                # Create a simple text representation
                if action_type == 'click':
                    text = f"Click: {event_data.get('name')} at ({event_data.get('x')}, {event_data.get('y')})"
                elif action_type == 'click_complete':
                    text = f"Click COMPLETE: {event_data.get('name')} at ({event_data.get('x')}, {event_data.get('y')}) [Duration: {event_data.get('duration'):.3f}s]"
                elif action_type == 'scroll':
                    text = f"Scroll: dx={event_data.get('dx')}, dy={event_data.get('dy')} at ({event_data.get('x')}, {event_data.get('y')})"
                elif action_type == 'move':
                    text = f"Move: ({event_data.get('x')}, {event_data.get('y')})"
                elif action_type == 'press':
                    text = f"Key: {event_data.get('name')} pressed={event_data.get('pressed')}"
                elif action_type == 'press_complete':
                    text = f"Key COMPLETE: {event_data.get('name')} [Duration: {event_data.get('duration'):.3f}s]"
                elif action_type == 'move':
                    text = f"Move: ({event_data.get('x')}, {event_data.get('y')})"
                else:
                    # Just convert the whole event to a string if we don't have special handling
                    text = str(event_data)
                    # Truncate if too long
                    if len(text) > 80:
                        text = text[:77] + "..."
                
                cv2.putText(frame, text, (TEXT_POSITION[0], line_pos), FONT, FONT_SCALE, 
                           TEXT_COLOR, FONT_THICKNESS, cv2.LINE_AA)
                line_pos += LINE_HEIGHT
            
            # Update frame_action_map
            current_chunk_actions_for_map = []
            for viz in actions_in_chunk:
                # Store the original event data in the map
                current_chunk_actions_for_map.append(viz['event_data'])
                
            if current_chunk_actions_for_map:
                frame_action_map[frame_count] = current_chunk_actions_for_map
            
            # Write frame to video
            out.write(frame)
            
            # Save debug frame
            if debug_frames_dir:
                debug_frame_path = os.path.join(debug_frames_dir, f"frame_{output_frame_count:06d}.png")
                try:
                    cv2.imwrite(debug_frame_path, frame)
                except Exception as e:
                    print(f"Error saving debug frame {output_frame_count}: {e}")
                    
            output_frame_count += 1
            actions_in_chunk = []

        frame_count += 1
        if frame_count % 100 == 0:
             print(f"Processed frame {frame_count}/{total_frames} ({current_frame_time_sec:.1f}s)")

    # Cleanup
    cap.release()
    out.release()
    print(f"Visualization complete. Output saved to: {output_path}")
    print(f"Saved {output_frame_count} debug frames to {debug_frames_dir}")

    # Save frame action map
    map_output_path = os.path.join(recording_dir, "frame_action_map.json")
    try:
        with open(map_output_path, 'w') as f:
            json.dump(frame_action_map, f, indent=4)
        print(f"Frame-action map saved to: {map_output_path}")
    except Exception as e:
        print(f"Error saving frame-action map: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Overlay DuckTrack actions onto the screen recording.")
    parser.add_argument("recording_dir", help="Path to the recording directory containing events.jsonl and recording.mp4")
    args = parser.parse_args()

    main(args.recording_dir) 