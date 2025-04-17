import json
import random
import time
import sys
import traceback
import subprocess
import platform
import pyautogui
from playwright.sync_api import sync_playwright, Error as PlaywrightError
import pygetwindow as gw
import argparse
from PIL import Image, ImageDraw
import io
import datetime
import string
from random_word import RandomWords
from urllib.parse import urlparse

SEED_WEBSITES_FILE = 'seed_websites.json'
MIN_WAIT_SECONDS = 5
MAX_WAIT_SECONDS = 15
INTERACTION_TIMEOUT_MS = 10000
INTERACTION_DELAY_MIN = 1.5
INTERACTION_DELAY_MAX = 3.0
NUM_INTERACTIONS = 50
BROWSER_TYPE = 'chromium'

# Define hotkeys for pyautogui to trigger (matching those in ducktrack app)
RECORD_HOTKEY = ['ctrl', 'alt', 'r'] 
STOP_HOTKEY = ['ctrl', 'alt', 's'] # Using the same key for toggle
RECORDING_APP_NAME = "DuckTrack" # Name of the recording application

# Input types that should trigger typing instead of just clicking
TYPING_INPUT_TYPES = ['text', 'email', 'password', 'search', 'url', 'tel', 'number']

# Define selectors
INTERACTIVE_SELECTOR = (
    'a:visible, button:visible, select:visible, ' # Links, buttons, dropdowns
    'input:visible[type="button"], input:visible[type="submit"], ' # Input buttons
    'input:visible[type="checkbox"], input:visible[type="radio"], '   # Checkboxes, Radio buttons
    '[role="button"]:visible, [role="link"]:visible, [role="checkbox"]:visible, ' # ARIA roles
    '[role="radio"]:visible, [role="combobox"]:visible, [role="option"]:visible, ' # More ARIA roles
    '[role="menuitem"]:visible, [role="tab"]:visible, [onclick]:visible' # ARIA roles + elements with explicit onclick handlers
)
TYPING_SELECTOR = (
    # Standard input types
    'textarea:visible, ' +
    ', '.join([f'input:visible[type="{t}"]' for t in TYPING_INPUT_TYPES]) + ', ' +
    # Input elements defaulting to type="text"
    'input:visible:not([type]), ' +
    # Common ARIA roles for text input
    '[role="textbox"]:visible, [role="searchbox"]:visible, ' +
    # Elements made editable via attribute
    '[contenteditable="true"]:visible'
)

# Enhanced random text generation
ALL_CHARS = string.ascii_letters + string.digits + string.punctuation + ' ' * 15 # More spaces

# Adjust timing constants for smoother interactions
INTERACTION_DELAY_MIN = 1.5  # Increased from 0.5
INTERACTION_DELAY_MAX = 3.0  # Increased from 1.0
MOUSE_MOVE_DURATION_MIN = 0.8  # New constant for minimum mouse movement duration
MOUSE_MOVE_DURATION_MAX = 1.5  # New constant for maximum mouse movement duration
CLICK_PAUSE_BEFORE = 0.3  # Pause before clicking
CLICK_PAUSE_AFTER = 0.5   # Pause after clicking

class MacWindow:
    """Helper class to store macOS window info and provide activate method."""
    def __init__(self, title, x, y, width, height, app_name):
        self.title = title
        self.left = int(x)
        self.top = int(y)
        self.width = int(width)
        self.height = int(height)
        self.app_name = app_name
        # Mimic pygetwindow attributes where possible
        self.box = (self.left, self.top, self.left + self.width, self.top + self.height)
        self.size = (self.width, self.height)
        self.isActive = False # We'll need a separate script to check this reliably if needed, activate brings it to front

    def activate(self):
        """Uses AppleScript to activate the application and bring the window to front."""
        # Escape quotes in title for AppleScript
        safe_title = self.title.replace('"', '\\"')
        script = f'''
            tell application "{self.app_name}"
                activate
                try
                    set theWindow to the first window whose name is "{safe_title}"
                    set index of theWindow to 1 -- Bring to front
                    return "OK"
                on error errMsg number errorNum
                    -- Fallback: try activating the app without focusing specific window if title match failed
                    activate application "{self.app_name}"
                    return "Fallback Activation: " & errMsg
                end try
            end tell
        '''
        try:
            print(f"Attempting to activate '{self.title}' of app '{self.app_name}' via AppleScript...")
            # Using osascript -e to execute the script string directly
            process = subprocess.run(['osascript', '-e', script], capture_output=True, text=True, check=True, timeout=5)
            print(f"AppleScript activate output: {process.stdout.strip()}")
            self.isActive = True # Assume activation succeeded if no error
            time.sleep(0.3) # Small delay after activation
        except subprocess.CalledProcessError as e:
            print(f"Error activating window via AppleScript: {e}")
            print(f"Stderr: {e.stderr}")
            # Try a simpler activation if the specific window failed (e.g., title changed slightly)
            try:
                 subprocess.run(['osascript', '-e', f'tell application "{self.app_name}" to activate'], check=True, timeout=3)
                 print("Performed simple fallback app activation.")
                 time.sleep(0.2)
            except Exception as fallback_e:
                 print(f"Simple fallback activation also failed: {fallback_e}")

        except subprocess.TimeoutExpired:
            print("Error: AppleScript activation command timed out.")
        except Exception as e:
            print(f"Unexpected error during AppleScript activation: {e}")

    def __repr__(self):
        return f"MacWindow(title='{self.title}', app='{self.app_name}', pos=({self.left},{self.top}), size=({self.width},{self.height}))"

def get_browser_window_macos(browser_type):
    """Uses AppleScript to find browser windows on macOS."""
    possible_apps = []
    if browser_type == 'chromium':
        possible_apps.extend(["Chromium"])
    elif browser_type == 'firefox':
        possible_apps.extend(["Firefox"])
    else:
        # Add other browser app names if needed
        print(f"Warning: Unsupported browser type '{browser_type}' for macOS AppleScript lookup.")
        return None

    app_list_str = ', '.join([f'"{app}"' for app in possible_apps]) # Format for AppleScript list

    # Simplified AppleScript that builds the output string directly
    script = f'''
        set final_output to ""
        set target_apps to {{{app_list_str}}}
        
        tell application "System Events"
            repeat with app_name in target_apps
                try
                    if exists application process app_name then
                        log "Found application: " & app_name
                        tell application process app_name
                            set window_count to count of windows
                            log "Window count for " & app_name & ": " & window_count
                            
                            repeat with win_idx from 1 to window_count
                                try
                                    set win to window win_idx
                                    set win_title to name of win
                                    log "Window title: " & win_title
                                    
                                    -- Get position and size directly as variables
                                    set win_position to position of win
                                    set pos_x to item 1 of win_position
                                    set pos_y to item 2 of win_position
                                    
                                    set win_size to size of win
                                    set size_w to item 1 of win_size
                                    set size_h to item 2 of win_size
                                    
                                    -- Check if window is minimized
                                    set is_min to false
                                    try
                                        set is_min to value of attribute "AXMinimized" of win
                                    on error
                                        -- If we can't get minimized state, assume not minimized
                                        set is_min to false
                                    end try
                                    
                                    log "Window position: " & pos_x & "," & pos_y & " size: " & size_w & "x" & size_h & " minimized: " & is_min
                                    
                                    -- Basic visibility check (not minimized, has size)
                                    if not is_min and size_w > 100 and size_h > 100 then
                                        -- Add data directly to output string
                                        -- Replace any pipe characters in the title with hyphens
                                        set safe_title to ""
                                        set oldDelimiters to AppleScript's text item delimiters
                                        set AppleScript's text item delimiters to "|"
                                        set title_parts to every text item of win_title
                                        set AppleScript's text item delimiters to "-"
                                        set safe_title to title_parts as string
                                        set AppleScript's text item delimiters to oldDelimiters
                                        
                                        -- Add this window directly to output
                                        set final_output to final_output & safe_title & "|" & pos_x & "|" & pos_y & "|" & size_w & "|" & size_h & "|" & app_name & linefeed
                                    end if
                                on error err_msg
                                    log "Error processing window " & win_idx & ": " & err_msg
                                end try
                            end repeat
                        end tell
                    else
                        log "Application not found: " & app_name
                    end if
                on error err_msg
                    log "Error processing application " & app_name & ": " & err_msg
                end try
            end repeat
        end tell
        
        return final_output
    '''

    try:
        print("Running AppleScript to find windows...") # Debug
        process = subprocess.run(['osascript', '-e', script], capture_output=True, text=True, check=True, timeout=10)
        output = process.stdout.strip()
        print(f"AppleScript Output:\n{output}") # Debug

        if not output:
            print("AppleScript found no matching browser windows. Trying simpler fallback script...")
            # Try a simpler fallback script that just gets basic window info
            fallback_script = f'''
                set output to ""
                repeat with app_name in {{{app_list_str}}}
                    try
                        tell application app_name
                            if it is running then
                                log "Found running app: " & app_name
                                set window_list to every window
                                repeat with w in window_list
                                    try
                                        set w_name to name of w
                                        log "Window: " & w_name
                                        set output to output & w_name & "|0|0|800|600|" & app_name & linefeed
                                    on error e
                                        log "Error getting window name: " & e
                                    end try
                                end repeat
                            end if
                        end tell
                    on error e
                        log "Error with app " & app_name & ": " & e
                    end try
                end repeat
                return output
            '''
            try:
                print("Running simplified AppleScript...")
                fallback_process = subprocess.run(['osascript', '-e', fallback_script], 
                                               capture_output=True, text=True, check=True, timeout=10)
                fallback_output = fallback_process.stdout.strip()
                print(f"Fallback AppleScript Output:\n{fallback_output}")
                
                if fallback_output:
                    output = fallback_output  # Use the fallback output
                    print("Using fallback script output")
                else:
                    print("Even the fallback script found no windows. This suggests permissions issues.")
                    # Check if the browser is actually running
                    browser_check_script = f'''
                        set is_running to false
                        repeat with app_name in {{{app_list_str}}}
                            tell application "System Events"
                                if exists application process app_name then
                                    set is_running to true
                                    return "Browser running: " & app_name
                                end if
                            end tell
                        end repeat
                        if not is_running then
                            return "No target browsers seem to be running."
                        end if
                    '''
                    browser_check = subprocess.run(['osascript', '-e', browser_check_script], 
                                                capture_output=True, text=True, check=False)
                    print(f"Browser check: {browser_check.stdout.strip()}")
                    print("Please ensure:")
                    print("1. Your browser is actually running")
                    print("2. You have granted Accessibility permissions in System Settings > Privacy & Security")
                    print("3. Try running this script directly from Terminal, not from an IDE")
                    return None
            except Exception as fallback_err:
                print(f"Fallback script also failed: {fallback_err}")
                return None

        found_windows = []
        all_visible_titles = []
        for line in output.splitlines():
            if not line: continue
            try:
                parts = line.split('|')
                if len(parts) >= 6:  # Make sure we have enough parts
                    title, x, y, w, h, app = parts[0], parts[1], parts[2], parts[3], parts[4], parts[5]
                    # Convert strings to integers, with fallback values if conversion fails
                    try:
                        x_val = int(float(x))  # Handle both integer and float strings
                    except ValueError:
                        x_val = 0
                    try:
                        y_val = int(float(y))
                    except ValueError:
                        y_val = 0
                    try:
                        w_val = int(float(w))
                    except ValueError:
                        w_val = 800
                    try:
                        h_val = int(float(h))
                    except ValueError:
                        h_val = 600
                    
                    # Only add window if it has a reasonable size
                    if w_val > 100 and h_val > 100:
                        window = MacWindow(title, x_val, y_val, w_val, h_val, app)
                        found_windows.append(window)
                        all_visible_titles.append(f"'{title}' ({w_val}x{h_val}) App: {app}")
            except ValueError as val_err:
                print(f"Warning: Could not parse AppleScript output line: {line} - Error: {val_err}")
            except Exception as parse_err:
                print(f"Error parsing window line '{line}': {parse_err}")

        if found_windows:
            print(f"Found {len(found_windows)} likely browser window(s) via AppleScript:")
            for info in all_visible_titles:
                print(f"      - {info}")
            # Heuristic: Return the first one found (often the most recently active or only one)
            # More sophisticated selection logic could be added here if needed (e.g. matching title)
            return found_windows[0]
        else:
            print("No suitable browser windows found via AppleScript after filtering.")
            return None

    except subprocess.CalledProcessError as e:
        print(f"Error running AppleScript to find windows: {e}")
        print(f"Stderr: {e.stderr}")
        return None
    except subprocess.TimeoutExpired:
        print("Error: AppleScript command to find windows timed out.")
        return None
    except Exception as e:
        print(f"Unexpected error during AppleScript window search: {e}")
        return None

def get_browser_window(browser_type):
    """Find the browser window using OS-specific methods."""
    if sys.platform == 'darwin': # macOS
        print("Using macOS (AppleScript) window detection.")
        return get_browser_window_macos(browser_type)
    else: # Windows or other platforms
        print(f"Using {sys.platform} (pygetwindow) window detection.")
        # Original pygetwindow logic
        possible_titles = []
        if browser_type == 'chromium':
            possible_titles.extend(["chrome", "edge", "chromium"])
        elif browser_type == 'firefox':
            possible_titles.extend(["firefox", "mozilla"])
        
        windows = gw.getAllWindows()
        matched_window = None
        all_visible_titles = [] # Store titles for debugging

        for window in windows:
            # Collect titles of potentially relevant windows for debugging
            if window.visible and window.width > 100 and window.height > 100:
                all_visible_titles.append(f"'{window.title}' ({window.width}x{window.height})")

            # Attempt to match based on title
            if any(title in window.title.lower() for title in possible_titles):
                if window.visible and window.width > 100 and window.height > 100:
                    print(f"Found likely browser window: '{window.title}' at ({window.left}, {window.top}) Size: {window.width}x{window.height}")
                    matched_window = window
                    break # Found a suitable window, stop searching
        
        if matched_window:
            return matched_window
        else:
            print("Warning: Could not find a suitable browser window based on expected titles.")
            if all_visible_titles:
                print("    Visible windows found by pygetwindow were:")
                for title in all_visible_titles:
                    print(f"      - {title}")
            else:
                print("    No visible windows meeting basic size criteria were found by pygetwindow.")
            return None

def generate_random_text(min_words=1, max_words=5, max_len=40):
    """Generates plausible-looking random text with words, numbers, and punctuation."""
    rw = RandomWords()
    num_words = random.randint(min_words, max_words)
    words = []
    # Generate words one by one
    for _ in range(num_words):
        word = rw.get_random_word()
        if word: # Ensure a word was returned before appending
            words.append(word)
    text = ' '.join(words)
    
    # Randomly insert numbers, punctuation, maybe double spaces
    insert_indices = sorted(random.sample(range(len(text)), k=min(random.randint(1, 4), len(text))))
    for i in reversed(insert_indices): # Insert from end to keep indices valid
        char_type = random.choice(['digit', 'punct', 'space'])
        if char_type == 'digit':
            text = text[:i] + random.choice(string.digits) + text[i:]
        elif char_type == 'punct':
             # Avoid inserting punctuation right next to existing punctuation/space maybe?
             if i > 0 and text[i-1] not in string.punctuation + ' ' and text[i] not in string.punctuation + ' ':
                 text = text[:i] + random.choice(',.?!') + text[i:] # Common punctuation
        else: # Extra space
             if text[i] != ' ': # Avoid triple spaces
                 text = text[:i] + ' ' + text[i:]
                 
    return text[:max_len].strip()

def generate_safe_text_for_mac(min_words=1, max_words=5, max_len=40):
    """Generates text that won't trigger macOS shortcuts and special characters."""
    if sys.platform != 'darwin':  # Only use special handling for macOS
        return generate_random_text(min_words, max_words, max_len)
        
    rw = RandomWords()
    num_words = random.randint(min_words, max_words)
    words = []
    
    # Generate words one by one
    for _ in range(num_words):
        word = rw.get_random_word()
        if word:
            # On macOS, avoid words that might be common macOS shortcuts
            if word.lower() in ['command', 'option', 'control', 'fn', 'siri', 'spotlight']:
                word = word + "x"  # Add 'x' to avoid exact matches
            words.append(word)
            
    text = ' '.join(words)
    
    # For macOS, use a more limited set of punctuation to avoid Option+key combinations
    # that might produce special characters or trigger system functions
    safe_punct = '.,?!'  # Just the basics
    
    # Add fewer random characters for macOS to reduce chance of hitting shortcuts
    insert_indices = sorted(random.sample(range(len(text)), k=min(random.randint(1, 2), len(text))))
    for i in reversed(insert_indices):
        char_type = random.choice(['digit', 'safe_punct'])
        if char_type == 'digit':
            text = text[:i] + random.choice(string.digits) + text[i:]
        else:  # safe_punct
            if i > 0 and text[i-1] not in safe_punct + ' ' and text[i] not in safe_punct + ' ':
                text = text[:i] + random.choice(safe_punct) + text[i:]
                
    return text[:max_len].strip()

def safe_type_text(text, interval_min=0.08, interval_max=0.18):  # Increased intervals
    """Types text safely, handling platform-specific issues."""
    if sys.platform == 'darwin':  # macOS
        # Use a slightly longer interval on macOS to avoid overwhelming the input system
        interval_min = 0.12  # Increased from 0.06
        interval_max = 0.25  # Increased from 0.15
        
        # On macOS, type character-by-character with careful handling
        for char in text:
            # Avoid potential keyboard shortcuts by not using modifier keys
            if char in '~@#$%^&*()_+{}|:"<>?':
                # For special characters, just use a basic substitute
                substitute = {'~': 'tilde', '@': 'at', '#': 'hash', '$': 'dollar', 
                             '%': 'percent', '^': 'caret', '&': 'and', '*': 'star',
                             '(': 'lparen', ')': 'rparen', '_': 'under', '+': 'plus',
                             '{': 'lbrace', '}': 'rbrace', '|': 'pipe', ':': 'colon',
                             '"': 'quote', '<': 'less', '>': 'greater', '?': 'question'}
                safe_char = substitute.get(char, char.lower())
                pyautogui.write(safe_char, interval=random.uniform(interval_min, interval_max))
            else:
                # Type regular characters normally
                pyautogui.write(char, interval=random.uniform(interval_min, interval_max))
                
            # Small pause sometimes after spaces or punctuation on macOS - increase pauses
            if char in ' .,:;!?':
                time.sleep(random.uniform(0.1, 0.3))  # Increased from 0.05-0.2
    else:
        # For non-macOS, use the original typing approach with slower intervals
        for char in text:
            pyautogui.write(char, interval=random.uniform(interval_min, interval_max))
            # Add occasional small pauses for non-macOS too
            if char in ' .,:;!?':
                time.sleep(random.uniform(0.05, 0.15))

def load_websites(filename):
    """Loads websites from the JSON file."""
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        urls = []
        for category in data.values():
            if isinstance(category, dict):
                urls.extend(category.values())
        print(f"Loaded {len(urls)} websites from {filename}")
        return urls
    except FileNotFoundError:
        print(f"Error: File not found - {filename}")
        sys.exit(1)
    except json.JSONDecodeError:
        print(f"Error: Could not decode JSON from {filename}")
        sys.exit(1)
    except Exception as e:
        print(f"An unexpected error occurred loading websites: {e}")
        sys.exit(1)

def activate_recording_app():
    """Attempts to find and activate the recording application before sending hotkeys."""
    print(f"Attempting to activate recording app ({RECORDING_APP_NAME})...")
    
    # Save current active window to return to it later if needed
    current_active = None
    browser_active = False
    
    try:
        if sys.platform == 'darwin':  # macOS
            # Try to find and activate the recording app using AppleScript
            script = f'''
                tell application "System Events"
                    set recording_app_running to false
                    try
                        if exists application process "{RECORDING_APP_NAME}" then
                            set recording_app_running to true
                            tell application process "{RECORDING_APP_NAME}"
                                set frontmost to true
                            end tell
                            return "Recording app activated"
                        end if
                    end try
                    
                    if not recording_app_running then
                        -- If specific app not found, try activating Desktop/Finder as neutral ground
                        tell application "Finder" to activate
                        return "Activated Finder (recording app not found)"
                    end if
                end tell
            '''
            
            try:
                result = subprocess.run(['osascript', '-e', script], 
                                       capture_output=True, text=True, check=False)
                print(f"Recording app activation result: {result.stdout.strip()}")
                time.sleep(1.0)  # Give time for app to come to foreground
                return True
            except Exception as e:
                print(f"Error activating recording app: {e}")
                # Fall back to just sending the hotkey without app focus
                time.sleep(0.5)
                return False
        else:  # Windows
            # On Windows, try to find and activate the recording app window
            windows = gw.getAllWindows()
            for window in windows:
                if RECORDING_APP_NAME.lower() in window.title.lower():
                    print(f"Found recording app window: {window.title}")
                    current_active = gw.getActiveWindow()
                    window.activate()
                    time.sleep(1.0)  # Wait for activation
                    return True
            
            # If recording app not found, just proceed with global hotkey
            print(f"Recording app window not found, will send global hotkey")
            return False
    except Exception as e:
        print(f"Error in activate_recording_app: {e}")
        return False

def trigger_hotkey(keys):
    """Triggers a keyboard hotkey combination using pyautogui."""
    try:
        # First try to activate the recording app
        activate_recording_app()
        
        print(f"Triggering hotkey via pyautogui: {'+'.join(keys)}")
        pyautogui.hotkey(*keys)
        time.sleep(1.5) # Increased delay to ensure app registers it
    except Exception as e:
        print(f"Warning: Could not trigger hotkey {'+'.join(keys)}. Error: {e}")
        print("Check pyautogui permissions/dependencies if this persists (e.g., Accessibility on macOS).")

def get_domain(url):
    """Extracts the domain (netloc) from a URL string."""
    try:
        parsed_url = urlparse(url)
        # Handle protocol-relative URLs (e.g., //example.com)
        if parsed_url.scheme == '' and parsed_url.netloc == '' and url.startswith('//'):
            # Re-parse with a dummy scheme
            parsed_url = urlparse('http:' + url) 
        return parsed_url.netloc.lower().replace('www.', '') # Normalize by lowercasing and removing www.
    except Exception:
        return None # Return None for invalid URLs

def get_macos_screen_scaling():
    """Get the macOS screen scaling factor using AppleScript."""
    if sys.platform != 'darwin':
        return 1.0
        
    try:
        # Get screen resolution and backing scale factor on macOS
        script = '''
            set screenInfo to {}
            tell application "Finder"
                set screenResolution to bounds of window of desktop
                set screenWidth to item 3 of screenResolution
                set screenHeight to item 4 of screenResolution
            end tell
            
            -- Try to get backing scale factor using system events
            set backingScaleFactor to 1.0
            try
                tell application "System Events"
                    tell process "Finder"
                        set backingScaleFactor to value of attribute "AXUIElementForFullScreenMode"'s value of attribute "AXWindowBackingScaleFactor" as string
                    end tell
                end try
            end try
            
            return screenWidth & "," & screenHeight & "," & backingScaleFactor
        '''
        
        process = subprocess.run(['osascript', '-e', script], 
                            capture_output=True, text=True, check=True, timeout=5)
        
        output = process.stdout.strip().split(',')
        if len(output) >= 3:
            try:
                # Get the reported screen width, height and scale factor
                screen_width = int(output[0])
                screen_height = int(output[1])
                # The backing scale factor might be 2.0 for Retina displays
                backing_scale = float(output[2])
                
                # Check if the scale factor seems reasonable
                if backing_scale < 0.5 or backing_scale > 3.0:
                    backing_scale = 2.0 if (screen_width > 2000 or screen_height > 1200) else 1.0
                
                print(f"Detected macOS screen: {screen_width}x{screen_height}, scaling: {backing_scale}")
                return backing_scale
            except (ValueError, IndexError) as e:
                print(f"Error parsing macOS screen info: {e}, output: {output}")
                # Guess scale based on pyautogui screen size
                pyautogui_size = pyautogui.size()
                return 2.0 if (pyautogui_size[0] > 2000 or pyautogui_size[1] > 1200) else 1.0
    except Exception as e:
        print(f"Error detecting macOS screen scaling: {e}")
        # Fallback: Use a reasonable guess based on typical macOS setups
        return 2.0  # Most modern Macs use Retina displays (2x scaling)

def calculate_screen_coordinates(window_pos, logical_pos, dpr, debug=False):
    """Calculate physical screen coordinates from logical coordinates using the correct DPR for the platform."""
    logical_x, logical_y = logical_pos
    
    if sys.platform == 'darwin':
        # On macOS, window positions from AppleScript might already include some scaling
        # Check our detected DPR and apply corrections
        macos_scaling = get_macos_screen_scaling()
        
        # Logic for different scaling scenarios (this may need adjustment for your specific setup)
        if dpr >= 1.5 and macos_scaling >= 1.5:
            # High DPR browser on Retina display - window coordinates are already scaled
            screen_x = window_pos['x'] + logical_x
            screen_y = window_pos['y'] + logical_y
            scaling_method = "macOS Retina (no additional scaling)"
        elif dpr >= 1.5:
            # High DPR browser on standard display
            screen_x = window_pos['x'] + (logical_x / dpr)
            screen_y = window_pos['y'] + (logical_y / dpr)
            scaling_method = f"macOS high DPR browser on standard display (divide by {dpr})"
        elif macos_scaling >= 1.5:
            # Standard browser on Retina display
            screen_x = window_pos['x'] + (logical_x * macos_scaling)
            screen_y = window_pos['y'] + (logical_y * macos_scaling)
            scaling_method = f"macOS standard browser on Retina display (multiply by {macos_scaling})"
        else:
            # Standard browser on standard display
            screen_x = window_pos['x'] + logical_x
            screen_y = window_pos['y'] + logical_y
            scaling_method = "macOS standard (no scaling)"
    else:
        # Non-macOS platforms use the original calculation
        screen_x = window_pos['x'] + (logical_x * dpr)
        screen_y = window_pos['y'] + (logical_y * dpr)
        scaling_method = f"Standard DPR scaling (multiply by {dpr})"
    
    # Get screen dimensions for bounds checking
    screen_width, screen_height = pyautogui.size()
    
    # For macOS, avoid the bottom 10% of the screen to prevent Dock interactions
    if sys.platform == 'darwin':
        # Calculate the safe area (avoid bottom 10% of screen)
        dock_margin = int(screen_height * 0.1)  # 10% of screen height
        
        # Ensure y coordinate doesn't go into the bottom margin
        max_y = screen_height - dock_margin - 1
        
        # Also add a small margin at the top for the menu bar (20px)
        min_y = 20
        
        # Apply the macOS-specific boundaries
        screen_x = max(0, min(screen_width - 1, int(screen_x)))
        screen_y = max(min_y, min(max_y, int(screen_y)))
        
        if debug:
            print(f"  Applied macOS safety margins: Top={min_y}px, Bottom={dock_margin}px")
            
    else:
        # Standard boundary check for non-macOS
        screen_x = max(0, min(screen_width - 1, int(screen_x)))
        screen_y = max(0, min(screen_height - 1, int(screen_y)))
    
    if debug:
        print(f"Coordinate conversion:")
        print(f"  Window pos: ({window_pos['x']}, {window_pos['y']})")
        print(f"  Logical pos: ({logical_x}, {logical_y})")
        print(f"  DPR: {dpr}, macOS scaling: {get_macos_screen_scaling() if sys.platform == 'darwin' else 'N/A'}")
        print(f"  Scaling method: {scaling_method}")
        print(f"  Screen dimensions: {screen_width}x{screen_height}")
        print(f"  Result: ({screen_x}, {screen_y})")
    
    return screen_x, screen_y

def interact_with_website(page, num_interactions=NUM_INTERACTIONS, debug_mode=False):
    """Uses Playwright to find elements, pygetwindow to find the window, and pyautogui to interact."""
    print(f"Page loaded: {page.title()}")
    time.sleep(random.uniform(2.5, 4.0))  # Increased initial wait time

    # Get initial domain
    initial_url = page.url
    initial_domain = get_domain(initial_url)
    if initial_domain:
        print(f"Operating on domain: {initial_domain}")
    else:
        print(f"Warning: Could not determine initial domain for {initial_url}")

    # Use OS-specific fullscreen shortcut
    print("Attempting to toggle fullscreen mode...")
    if sys.platform == 'darwin':  # macOS
        print("Using macOS fullscreen shortcut (Command+Control+F)...")
        pyautogui.hotkey('command', 'ctrl', 'f')
    else:  # Windows/Linux
        print("Using F11 fullscreen shortcut...")
        pyautogui.press('f11')
    time.sleep(4.5) # Increased wait time for fullscreen transition from 3.5

    screen_width, screen_height = pyautogui.size()
    print(f"Screen dimensions: {screen_width}x{screen_height}")

    # Get Device Pixel Ratio (DPR) after page load and potential fullscreen
    try:
        dpr = page.evaluate('window.devicePixelRatio')
        print(f"Detected Device Pixel Ratio (DPR): {dpr}")
        if dpr <= 0: # Basic sanity check
             print("Warning: Invalid DPR detected, defaulting to 1.")
             dpr = 1
    except Exception as e:
        print(f"Warning: Could not get devicePixelRatio, assuming 1. Error: {e}")
        dpr = 1
        
    # Additional Mac-specific display info
    if sys.platform == 'darwin':
        macos_scale = get_macos_screen_scaling()
        print(f"Detected macOS screen scaling factor: {macos_scale}")
        
        # Display macOS safety margin info
        screen_width, screen_height = pyautogui.size()
        dock_margin = int(screen_height * 0.1)
        print(f"Using macOS safety margins: Avoiding bottom {dock_margin}px of screen (Dock area)")
        print(f"Safe Y coordinate range: 20px to {screen_height - dock_margin - 1}px")
        
        # Simple coordinate test for debugging
        if debug_mode:
            print("Testing coordinate conversion:")
            test_logical_x, test_logical_y = 100, 100
            test_screen_x, test_screen_y = calculate_screen_coordinates(
                {'x': 0, 'y': 0}, 
                (test_logical_x, test_logical_y), 
                dpr, 
                debug=True
            )
            print(f"Test coords: Logical (100,100) → Screen ({test_screen_x},{test_screen_y})")

    # Initial window fetch (might be slightly delayed after F11)
    browser_window = get_browser_window(BROWSER_TYPE)
    if browser_window:
        print(f"Initial window guess: '{browser_window.title}' at ({browser_window.left}, {browser_window.top}) Size: {browser_window.width}x{browser_window.height}")

    for i in range(num_interactions):
        print(f"--- Interaction {i + 1}/{num_interactions} ---")
        if page.is_closed():
            print("Page closed, stopping interactions.")
            break

        # Re-fetch window info before each interaction, in case it moved/resized
        current_browser_window = get_browser_window(BROWSER_TYPE)
        if not current_browser_window:
            raise Exception("Browser window not found")
        else:
            try:
                if not current_browser_window.isActive:
                    # print("Activating browser window...") # Reduce noise
                    current_browser_window.activate()
                    time.sleep(0.2)
            except Exception as e:
                print(f"Warning: Could not activate browser window: {e}")
            window_pos = {'x': current_browser_window.left, 'y': current_browser_window.top}
            print(f"Using window pos: ({window_pos['x']}, {window_pos['y']}) Size: {current_browser_window.width}x{current_browser_window.height}")

        try:
            # --- Find all potentially relevant elements BEFORE the action --- 
            all_interactive_elements = page.query_selector_all(INTERACTIVE_SELECTOR)
            all_typing_elements = page.query_selector_all(TYPING_SELECTOR)
            
            visible_interactive = [el for el in all_interactive_elements if el.is_visible() and el.is_enabled()]
            visible_typing = [el for el in all_typing_elements if el.is_visible() and el.is_enabled()]
            print(f"Debug: Found {len(visible_interactive)} visible/enabled interactive elements.")
            print(f"Debug: Found {len(visible_typing)} visible/enabled typing elements.")
            # --- End element finding --- 

            # Decide action: Make click and type roughly equally likely, scroll/move less likely
            action = random.choices(['scroll', 'click', 'type', 'move'], weights=[15, 35, 35, 15], k=1)[0]
            print(f"Chosen action: '{action}'")
            
            # Add a general pause before any action
            time.sleep(random.uniform(0.5, 1.0))  # New general pause

            if action == 'scroll' and window_pos is not None:
                scroll_amount = random.randint(-800, 800)

                # --- New Scroll Logic: Target an element --- 
                print("Action: Attempting to scroll to an element...")
                viewport_size = page.viewport_size # Returns {'width', 'height'}
                scroll_target_element = None
                target_candidates = []

                # Combine candidates: interactive, typing, and images
                potential_targets = visible_interactive + visible_typing + page.query_selector_all('img:visible')
                random.shuffle(potential_targets) # Shuffle to avoid always picking the first off-screen one

                if viewport_size:
                    vp_height = viewport_size['height']
                    for el in potential_targets:
                        try:
                            bbox = el.bounding_box()
                            if bbox:
                                # Check if element is mostly outside the viewport (top or bottom)
                                if bbox['y'] < 10 or bbox['y'] + bbox['height'] > vp_height - 10:
                                    target_candidates.append(el)
                                    # Optional: Break early if we found a few candidates
                                    # if len(target_candidates) >= 5: break 
                        except PlaywrightError:
                            continue # Ignore elements that error out on bounding_box

                if target_candidates:
                    scroll_target_element = random.choice(target_candidates)
                    element_text_desc = "Image" if scroll_target_element.evaluate('el => el.tagName.toLowerCase()') == 'img' else (scroll_target_element.inner_text() or scroll_target_element.get_attribute('aria-label') or "[Scroll Target]")[:40].strip()
                    print(f"Action: Scrolling towards element: '{element_text_desc}'")
                    try:
                        scroll_target_element.scroll_into_view_if_needed(timeout=INTERACTION_TIMEOUT_MS // 2)
                        print("Debug: scroll_into_view_if_needed completed.")
                        action_performed = True
                    except PlaywrightError as scroll_err:
                        print(f"Warning: Could not scroll to target element '{element_text_desc}': {scroll_err}")
                        scroll_target_element = None # Failed to scroll
                else:
                    print("No suitable off-screen elements found to scroll towards. Performing small fallback scroll.")
                    scroll_target_element = None

                # Fallback: If no element was targeted or scroll failed, do a small random scroll
                fallback_scroll = False # Initialize fallback flag
                if not scroll_target_element:
                    scroll_amount = random.randint(-250, 250) # Smaller random scroll
                    if scroll_amount != 0:
                        print(f"Action: Performing fallback scroll ('down' if scroll_amount > 0 else 'up') by {abs(scroll_amount)} units (smoothly)")
                        # --- Simulate smoother scroll --- 
                        num_chunks = 8 # Increased from 5 for smoother scrolling
                        chunk_amount = scroll_amount // num_chunks
                        remainder = scroll_amount % num_chunks
                        scroll_delay = 0.1 # Increased from 0.04 for slower scrolling

                        for i in range(num_chunks):
                            if chunk_amount != 0:
                                pyautogui.scroll(chunk_amount)
                            if i == num_chunks - 1 and remainder != 0: # Add remainder on last chunk
                                pyautogui.scroll(remainder)
                            time.sleep(scroll_delay)
                        # --- End smoother scroll --- 
                        fallback_scroll = True
                    else:
                        print("Fallback scroll amount was 0, skipping scroll.")
                        fallback_scroll = False # Ensure it's false if we skip
                else:
                    fallback_scroll = False

                # --- Debug Screenshot for Scroll --- 
                if debug_mode:
                    save_debug_screenshot(page, 'scroll', {
                        'target_element': scroll_target_element, # Pass the element we scrolled to
                        'fallback_scroll': fallback_scroll, 
                        'scroll_amount': scroll_amount if fallback_scroll else 0 # Only relevant for fallback
                    }, dpr=dpr,
                        visible_interactive_elements=visible_interactive,
                        visible_typing_elements=visible_typing)
                # --- End Scroll Logic ---
                
                # Add extra pause after scrolling
                time.sleep(random.uniform(0.7, 1.5))  # Extra pause after scroll
            
            elif action == 'click' and window_pos is not None:
                print("Action: Finding CLICKABLE element (non-typing)...")
                # Use the predefined INTERACTIVE_SELECTOR (which excludes typing fields now)
                # We already found visible_interactive elements above
                # print(f"Debug: Found {len(interactive_elements)} potential clickable elements, {len(visible_interactive)} are visible and enabled.") # Redundant now

                if visible_interactive:
                    target_element = random.choice(visible_interactive)
                    element_text_desc = (target_element.inner_text() or target_element.get_attribute('value') or target_element.get_attribute('aria-label') or target_element.get_attribute('placeholder') or "[No Text/Desc]")[:60].strip()
                    
                    try:
                        # --- Check for Mailto and Cross-Domain Links --- 
                        tag_name = target_element.evaluate('el => el.tagName.toLowerCase()')
                        if tag_name == 'a':
                            href = target_element.get_attribute('href')
                            if href:
                                href_lower_stripped = href.lower().strip()
                                # Skip mailto links
                                if href_lower_stripped.startswith('mailto:'):
                                    print(f"Skipping click on mailto link: '{element_text_desc}' (href: {href})")
                                    continue 
                                # Skip javascript links (often don't navigate)
                                if href_lower_stripped.startswith('javascript:'):
                                    print(f"Skipping click on javascript link: '{element_text_desc}' (href: {href})")
                                    continue
                                # Check domain if it's not mailto/javascript
                                link_domain = get_domain(href)
                                # Allow click if: 
                                # 1. Link has no domain (relative path) 
                                # 2. Link domain matches initial domain (and initial domain is known)
                                if link_domain and initial_domain and link_domain != initial_domain:
                                     print(f"Skipping click on cross-domain link: '{element_text_desc}' (href: {href}, link_domain: {link_domain}, initial: {initial_domain})")
                                     continue
                        # --- End Mailto/Cross-Domain Check --- 
                        
                        # --- Ensure element is visible before getting final bbox --- 
                        print(f"Debug: Attempting to scroll element '{element_text_desc}' into view...")
                        try:
                            target_element.scroll_into_view_if_needed(timeout=INTERACTION_TIMEOUT_MS // 4) # Shorter timeout for scroll
                            print("Debug: Element scrolled into view (if needed). Re-checking visibility...")
                            if not target_element.is_visible(): # Double check visibility after scroll
                                print(f"Warning: Element '{element_text_desc}' still not visible after attempting scroll. Skipping click/type.")
                                continue # Skip to next interaction
                        except PlaywrightError as scroll_err:
                            print(f"Warning: Could not scroll element '{element_text_desc}' into view or element became stale: {scroll_err}. Skipping click/type.")
                            continue # Skip to next interaction
                        # --- End visibility check ---
                        
                        bbox = target_element.bounding_box()
                        if bbox:
                            # Element is in view and bbox obtained, proceed with click/type
                            # Playwright provides logical coordinates (CSS pixels)
                            logical_x, logical_y, logical_w, logical_h = bbox['x'], bbox['y'], bbox['width'], bbox['height']
                            logical_center_x = logical_x + logical_w / 2
                            logical_center_y = logical_y + logical_h / 2

                            # --- Debug Visualization (Moved to helper) --- 
                            if debug_mode:
                                save_debug_screenshot(page, 'click', {
                                    'target_element': target_element,
                                    'logical_center_x': logical_center_x,
                                    'logical_center_y': logical_center_y
                                }, dpr=dpr, 
                                    visible_interactive_elements=visible_interactive,
                                    visible_typing_elements=visible_typing)
                            # --- End Debug Visualization ---

                            # Calculate PHYSICAL screen coordinates for pyautogui action
                            screen_x, screen_y = calculate_screen_coordinates(
                                window_pos,
                                (logical_center_x, logical_center_y),
                                dpr,
                                debug=debug_mode
                            )

                            # Move more slowly to the click target
                            movement_duration = random.uniform(MOUSE_MOVE_DURATION_MIN, MOUSE_MOVE_DURATION_MAX)
                            print(f"Action: Moving mouse to click element '{element_text_desc}' at screen coords ({screen_x}, {screen_y}) over {movement_duration:.2f} seconds")
                            
                            # Move cursor in a slightly curved path
                            current_x, current_y = pyautogui.position()
                            
                            # Calculate a midpoint with slight randomness for curved movement
                            mid_x = (current_x + screen_x) / 2 + random.randint(-30, 30)
                            mid_y = (current_y + screen_y) / 2 + random.randint(-30, 30)
                            
                            # First half of the movement (to midpoint)
                            half_duration = movement_duration / 2
                            pyautogui.moveTo(mid_x, mid_y, duration=half_duration)
                            
                            # Brief pause at midpoint
                            time.sleep(random.uniform(0.05, 0.15))
                            
                            # Second half of the movement (to target)
                            pyautogui.moveTo(screen_x, screen_y, duration=half_duration)
                            
                            # Pause briefly before clicking
                            time.sleep(CLICK_PAUSE_BEFORE)
                            
                            # Click more naturally
                            pyautogui.click()
                            
                            # Pause after clicking
                            time.sleep(CLICK_PAUSE_AFTER)
                            
                            # Simulate typing character by character with mistakes
                            current_typed = ""
                            
                            if sys.platform == 'darwin':  # macOS-specific typing handling
                                # On macOS, use our safe typing function
                                safe_type_text(random_input_text)
                                
                                # Occasionally simulate a backspace for realism
                                if len(random_input_text) > 5 and random.random() < 0.2:  # 20% chance
                                    # Press backspace 1-2 times
                                    num_backspaces = random.randint(1, 2)
                                    print(f"    (Simulating {num_backspaces} backspace(s))")
                                    for _ in range(num_backspaces):
                                        pyautogui.press('backspace')
                                        time.sleep(random.uniform(0.1, 0.2))
                            else:
                                # For non-macOS, use the original typing approach with mistakes
                                for char in random_input_text:
                                    # Chance to make a mistake (press backspace)
                                    if random.random() < 0.05 and len(current_typed) > 0: # e.g., 5% chance if something is typed
                                        num_backspaces = random.randint(1, min(3, len(current_typed))) # Backspace 1-3 chars
                                        print(f"    (Simulating {num_backspaces} backspace(s))", end='')
                                        for _ in range(num_backspaces):
                                             pyautogui.press('backspace')
                                             time.sleep(random.uniform(0.05, 0.15))
                                        current_typed = current_typed[:-num_backspaces] # Update our tracked typed text
                                    
                                    # Type the actual character
                                    pyautogui.write(char, interval=random.uniform(0.04, 0.12))
                                    current_typed += char

                                    # Chance to press left/right arrow
                                    if random.random() < 0.03: # e.g. 3% chance per character
                                        arrow_key = random.choice(['left', 'right'])
                                        print(f"    (Simulating arrow key: {arrow_key})", end='')
                                        pyautogui.press(arrow_key)
                                        time.sleep(random.uniform(0.05, 0.1))

                                    # Small pause sometimes after spaces or punctuation? 
                                    if char in ' ' + string.punctuation:
                                         time.sleep(random.uniform(0.0, 0.15))

                            print() # Newline after typing simulation messages
                            time.sleep(0.5) # Wait after typing finished
                            
                            # IMPORTANT: On macOS, press ESC key to dismiss any accidentally triggered system UI
                            if sys.platform == 'darwin':
                                # Press ESC key just to be safe (dismisses emoji picker, dictation prompt, etc.)
                                time.sleep(0.3)
                                pyautogui.press('escape')
                                time.sleep(0.3)
                        else:
                            print(f"Could not get bounding box for the element '{element_text_desc}' even after scrolling into view.")
                    except PlaywrightError as pe:
                        print(f"Playwright error evaluating/interacting with element '{element_text_desc}': {pe}")
                    except Exception as e:
                        print(f"Error calculating/interacting with element '{element_text_desc}': {e}")
                else:
                    print("No visible interactive elements found. Performing random move instead.")
                    action = 'move' # Fallback if click chosen but no elements found

            elif action == 'type' and window_pos is not None:
                print("Action: Finding TYPING element...")
                # Use the specific TYPING_SELECTOR
                # We already found visible_typing elements above
                # print(f"Debug: Found {len(typing_elements)} potential typing elements, {len(visible_typing)} are visible and enabled.") # Redundant now

                if visible_typing:
                    target_element = random.choice(visible_typing)
                    element_text_desc = (target_element.get_attribute('placeholder') or target_element.get_attribute('aria-label') or target_element.get_attribute('name') or "[Typing Field]")[:60].strip()

                    try:
                         # --- Ensure element is visible before getting final bbox --- 
                        print(f"Debug: Attempting to scroll element '{element_text_desc}' into view...")
                        try:
                            target_element.scroll_into_view_if_needed(timeout=INTERACTION_TIMEOUT_MS // 4) # Shorter timeout for scroll
                            print("Debug: Element scrolled into view (if needed). Re-checking visibility...")
                            if not target_element.is_visible(): # Double check visibility after scroll
                                print(f"Warning: Element '{element_text_desc}' still not visible after attempting scroll. Skipping type.")
                                continue # Skip to next interaction
                        except PlaywrightError as scroll_err:
                            print(f"Warning: Could not scroll element '{element_text_desc}' into view or element became stale: {scroll_err}. Skipping type.")
                            continue # Skip to next interaction
                        # --- End visibility check ---

                        bbox = target_element.bounding_box()
                        if bbox:
                            logical_x, logical_y, logical_w, logical_h = bbox['x'], bbox['y'], bbox['width'], bbox['height']
                            logical_center_x = logical_x + logical_w / 2
                            logical_center_y = logical_y + logical_h / 2

                            screen_x, screen_y = calculate_screen_coordinates(
                                window_pos,
                                (logical_center_x, logical_center_y),
                                dpr,
                                debug=debug_mode
                            )

                            # Move more slowly to the input element
                            movement_duration = random.uniform(MOUSE_MOVE_DURATION_MIN, MOUSE_MOVE_DURATION_MAX)
                            print(f"Action: Moving mouse to typing element '{element_text_desc}' at screen coords ({screen_x}, {screen_y}) over {movement_duration:.2f} seconds")
                            
                            # Move cursor in a slightly curved path
                            current_x, current_y = pyautogui.position()
                            
                            # Calculate a midpoint with slight randomness for curved movement
                            mid_x = (current_x + screen_x) / 2 + random.randint(-30, 30)
                            mid_y = (current_y + screen_y) / 2 + random.randint(-30, 30)
                            
                            # First half of the movement (to midpoint)
                            half_duration = movement_duration / 2
                            pyautogui.moveTo(mid_x, mid_y, duration=half_duration)
                            
                            # Brief pause at midpoint
                            time.sleep(random.uniform(0.05, 0.15))
                            
                            # Second half of the movement (to target)
                            pyautogui.moveTo(screen_x, screen_y, duration=half_duration)
                            
                            # Pause briefly before clicking
                            time.sleep(CLICK_PAUSE_BEFORE)
                            
                            # Click to focus
                            pyautogui.click()
                            
                            # Longer wait for focus
                            time.sleep(random.uniform(0.5, 0.8))  # Increased from 0.2-0.4
                            
                            # Simulate typing character by character with mistakes
                            current_typed = ""
                            
                            if sys.platform == 'darwin':  # macOS-specific typing handling
                                # On macOS, use our safe typing function
                                safe_type_text(random_input_text)
                                
                                # Occasionally simulate a backspace for realism
                                if len(random_input_text) > 5 and random.random() < 0.2:  # 20% chance
                                    # Press backspace 1-2 times
                                    num_backspaces = random.randint(1, 2)
                                    print(f"    (Simulating {num_backspaces} backspace(s))")
                                    for _ in range(num_backspaces):
                                        pyautogui.press('backspace')
                                        time.sleep(random.uniform(0.1, 0.2))
                            else:
                                # For non-macOS, use the original typing approach with mistakes
                                for char in random_input_text:
                                    # Chance to make a mistake (press backspace)
                                    if random.random() < 0.05 and len(current_typed) > 0: # e.g., 5% chance if something is typed
                                        num_backspaces = random.randint(1, min(3, len(current_typed))) # Backspace 1-3 chars
                                        print(f"    (Simulating {num_backspaces} backspace(s))", end='')
                                        for _ in range(num_backspaces):
                                             pyautogui.press('backspace')
                                             time.sleep(random.uniform(0.05, 0.15))
                                        current_typed = current_typed[:-num_backspaces] # Update our tracked typed text
                                    
                                    # Type the actual character
                                    pyautogui.write(char, interval=random.uniform(0.04, 0.12))
                                    current_typed += char

                                    # Chance to press left/right arrow
                                    if random.random() < 0.03: # e.g. 3% chance per character
                                        arrow_key = random.choice(['left', 'right'])
                                        print(f"    (Simulating arrow key: {arrow_key})", end='')
                                        pyautogui.press(arrow_key)
                                        time.sleep(random.uniform(0.05, 0.1))

                                    # Small pause sometimes after spaces or punctuation? 
                                    if char in ' ' + string.punctuation:
                                         time.sleep(random.uniform(0.0, 0.15))

                            print() # Newline after typing simulation messages
                            time.sleep(0.5) # Wait after typing finished
                            
                            # IMPORTANT: On macOS, press ESC key to dismiss any accidentally triggered system UI
                            if sys.platform == 'darwin':
                                # Press ESC key just to be safe (dismisses emoji picker, dictation prompt, etc.)
                                time.sleep(0.3)
                                pyautogui.press('escape')
                                time.sleep(0.3)
                        else:
                            print(f"Could not get bounding box for the typing element '{element_text_desc}' even after scrolling into view.")
                    except PlaywrightError as pe:
                        print(f"Playwright error evaluating/interacting with typing element '{element_text_desc}': {pe}")
                    except Exception as e:
                        print(f"Error calculating/interacting with typing element '{element_text_desc}': {e}")
                else:
                    print("No visible typing elements found. Performing random move instead.")
                    action = 'move' # Fallback if type chosen but no elements found

            if action == 'move':
                # For macOS, ensure random coordinates avoid the Dock area
                if sys.platform == 'darwin':
                    screen_width, screen_height = pyautogui.size()
                    dock_margin = int(screen_height * 0.1)
                    rand_x = random.randint(0, screen_width - 1)
                    rand_y = random.randint(20, screen_height - dock_margin - 1)  # Avoid Dock area and menu bar
                    print(f"Action: Moving mouse randomly to ({rand_x}, {rand_y}) [Safe macOS area]")
                else:
                    rand_x = random.randint(0, screen_width - 1)
                    rand_y = random.randint(0, screen_height - 1)
                    print(f"Action: Moving mouse randomly to ({rand_x}, {rand_y})")
                
                # Debug screenshot
                if debug_mode:
                    save_debug_screenshot(page, 'move', {
                        'screen_x': rand_x, 
                        'screen_y': rand_y,
                        'window_pos': window_pos
                    }, dpr=dpr,
                        visible_interactive_elements=visible_interactive,
                        visible_typing_elements=visible_typing)
                
                # Move more slowly and naturally
                movement_duration = random.uniform(MOUSE_MOVE_DURATION_MIN, MOUSE_MOVE_DURATION_MAX)
                
                # Current position
                current_x, current_y = pyautogui.position()
                
                # Create a more natural path with 2-3 intermediate points
                num_points = random.randint(2, 3)
                points = [(current_x, current_y)]
                
                for p in range(num_points):
                    # Create points that make a somewhat curved path
                    progress = (p + 1) / (num_points + 1)
                    # Base position by linear interpolation
                    base_x = current_x + (rand_x - current_x) * progress
                    base_y = current_y + (rand_y - current_y) * progress
                    # Add randomness to create curve
                    curve_x = base_x + random.randint(-50, 50) * (1 - progress)
                    curve_y = base_y + random.randint(-50, 50) * (1 - progress)
                    points.append((curve_x, curve_y))
                
                # Add final destination
                points.append((rand_x, rand_y))
                
                # Move through points
                segment_duration = movement_duration / (len(points) - 1)
                for i in range(1, len(points)):
                    pyautogui.moveTo(points[i][0], points[i][1], duration=segment_duration)
                    # Small pause at each point
                    if i < len(points) - 1:
                        time.sleep(random.uniform(0.05, 0.1))

            # Increased delay between interactions
            next_delay = random.uniform(INTERACTION_DELAY_MIN, INTERACTION_DELAY_MAX)
            print(f"Waiting {next_delay:.2f} seconds before next interaction...")
            time.sleep(next_delay)

        except Exception as interact_err:
            print(f"Error during interaction {i+1}: {interact_err}")
            if page.is_closed():
                print("Page closed during interaction/error, stopping interactions.")
                break
            if 'fail-safe' in str(interact_err).lower():
                 print("Fail-safe triggered. Stopping script.")
                 sys.exit(1)
            print("Continuing to next interaction.")

def save_debug_screenshot(page, action_type, data, dpr=1, screen_size=None, visible_interactive_elements=None, visible_typing_elements=None):
    """Saves a screenshot with visual indicators for debugging purposes."""
    try:
        print(f"Debug: Taking screenshot for '{action_type}' action...")
        screenshot_bytes = page.screenshot()
        img = Image.open(io.BytesIO(screenshot_bytes))
        draw = ImageDraw.Draw(img)
        img_width, img_height = img.size # These are physical pixels
        
        # --- Draw ALL detected elements first --- 
        # Draw boxes for all visible interactive (clickable) elements
        if visible_interactive_elements:
            print(f"Debug: Drawing {len(visible_interactive_elements)} interactive element boxes (DPR={dpr})...")
            for el in visible_interactive_elements:
                try:
                    el_bbox = el.bounding_box()
                    if el_bbox:
                        draw_x = el_bbox['x'] * dpr
                        draw_y = el_bbox['y'] * dpr
                        draw_w = el_bbox['width'] * dpr
                        draw_h = el_bbox['height'] * dpr
                        draw.rectangle([draw_x, draw_y, draw_x + draw_w, draw_y + draw_h], outline="gray", width=1)
                except PlaywrightError as bbox_err:
                    print(f"Debug: Error getting bounding box for interactive element: {bbox_err}")

        # Draw boxes for all visible typing elements
        if visible_typing_elements:
            print(f"Debug: Drawing {len(visible_typing_elements)} typing element boxes (DPR={dpr})...")
            for el in visible_typing_elements:
                try:
                    el_bbox = el.bounding_box()
                    if el_bbox:
                        draw_x = el_bbox['x'] * dpr
                        draw_y = el_bbox['y'] * dpr
                        draw_w = el_bbox['width'] * dpr
                        draw_h = el_bbox['height'] * dpr
                        draw.rectangle([draw_x, draw_y, draw_x + draw_w, draw_y + draw_h], outline="lightgreen", width=1) # Light green for all typing fields
                except PlaywrightError as bbox_err:
                    print(f"Debug: Error getting bounding box for typing element: {bbox_err}")
        # --- End drawing all elements ---

        # --- Now draw specific action highlights ON TOP --- 
        if action_type == 'click':
            target_element = data.get('target_element')
            logical_center_x = data.get('logical_center_x')
            logical_center_y = data.get('logical_center_y')
            
            # Draw thicker red box for the chosen target element
            if target_element:
                try:
                    el_bbox = target_element.bounding_box()
                    if el_bbox:
                         draw_x = el_bbox['x'] * dpr
                         draw_y = el_bbox['y'] * dpr
                         draw_w = el_bbox['width'] * dpr
                         draw_h = el_bbox['height'] * dpr
                         draw.rectangle([draw_x, draw_y, draw_x + draw_w, draw_y + draw_h], outline="red", width=3) # Thicker red for target
                except PlaywrightError as bbox_err:
                     print(f"Debug: Error getting bounding box for target element: {bbox_err}")

            # Draw larger marker at logical click point (scaled) with label
            if logical_center_x is not None and logical_center_y is not None:
                marker_draw_x = logical_center_x * dpr
                marker_draw_y = logical_center_y * dpr
                marker_size = 15 # Increased size
                x0 = marker_draw_x - marker_size / 2
                y0 = marker_draw_y - marker_size / 2
                x1 = marker_draw_x + marker_size / 2
                y1 = marker_draw_y + marker_size / 2
                draw.line([(x0,y0), (x1,y1)], fill="red", width=4) # Thicker crosshair
                draw.line([(x0,y1), (x1,y0)], fill="red", width=4)
                draw.text((marker_draw_x + 5, marker_draw_y + 5), "Click Target", fill="red")

        elif action_type == 'scroll':
            scroll_amount = data.get('scroll_amount')
            target_element = data.get('target_element') # Element we scrolled to
            fallback_scroll = data.get('fallback_scroll', False)

            if target_element:
                # Highlight the element scrolled into view
                try:
                    el_bbox = target_element.bounding_box()
                    if el_bbox:
                        draw_x = el_bbox['x'] * dpr
                        draw_y = el_bbox['y'] * dpr
                        draw_w = el_bbox['width'] * dpr
                        draw_h = el_bbox['height'] * dpr
                        draw.rectangle([draw_x, draw_y, draw_x + draw_w, draw_y + draw_h], outline="orange", width=3) # Orange box for scroll target
                        draw.text((draw_x, draw_y - 15), "Scroll Target", fill="orange")
                    else:
                        print("Debug: Scroll target bounding box not available after scroll.")
                except PlaywrightError as bbox_err:
                    print(f"Debug: Error getting bounding box for scroll target element: {bbox_err}")
            elif fallback_scroll:
                # Draw indicator for small random scroll if target wasn't found
                scroll_amount = data.get('scroll_amount', 0)
                center_x = img_width / 2
                draw.line([(center_x - 30, img_height / 2), (center_x + 30, img_height / 2)], fill="orange", width=3)
                draw.text((center_x + 35, img_height / 2 - 10), f"Fallback Scroll ({scroll_amount})", fill="orange")
            else:
                 # If scroll wasn't possible (no target, no fallback)
                 draw.text((10, img_height - 20), "Scroll Attempted (No Target Found)", fill="orange")

        elif action_type == 'move':
            screen_x = data.get('screen_x') # Absolute screen coord
            screen_y = data.get('screen_y') # Absolute screen coord
            window_pos = data.get('window_pos') # Window top-left screen coord {'x', 'y'}
            
            if screen_x is not None and screen_y is not None and window_pos is not None:
                 # Calculate target position *relative* to the viewport (screenshot) top-left
                 # NOTE: This assumes the screenshot captures the viewport starting exactly at window_pos.
                 # It does NOT account for browser chrome (title bar, toolbars, etc.) above the viewport.
                 # The accuracy depends on how well window_pos represents the viewport origin.
                 viewport_target_x = screen_x - window_pos['x']
                 viewport_target_y = screen_y - window_pos['y']
                 
                 marker_size = 20 # Size of the crosshair
                 marker_color = "purple"
                 text_offset = 5
                 target_text = f"Move Target\n({screen_x},{screen_y})"
                 target_on_screen = True

                 # Clamp coordinates to draw marker at edge if target is outside screenshot bounds
                 draw_x = viewport_target_x
                 draw_y = viewport_target_y
                 if not (0 <= viewport_target_x < img_width and 0 <= viewport_target_y < img_height):
                     target_on_screen = False
                     # Clamp to nearest edge for drawing the marker
                     draw_x = max(marker_size/2, min(img_width - marker_size/2, viewport_target_x))
                     draw_y = max(marker_size/2, min(img_height - marker_size/2, viewport_target_y))
                     target_text += "\n(Outside Viewport)"
                     marker_color = "deeppink" # Different color for off-screen target

                 # Draw a large crosshair at the calculated/clamped position
                 x0 = draw_x - marker_size / 2
                 y0 = draw_y - marker_size / 2
                 x1 = draw_x + marker_size / 2
                 y1 = draw_y + marker_size / 2
                 draw.line([(x0, draw_y), (x1, draw_y)], fill=marker_color, width=4) # Horizontal line
                 draw.line([(draw_x, y0), (draw_x, y1)], fill=marker_color, width=4) # Vertical line
                 draw.text((draw_x + text_offset, draw_y + text_offset), target_text, fill=marker_color)
                 print(f"Debug: Drawing move indicator (Target: {screen_x},{screen_y}, OnScreen: {target_on_screen})")
            else:
                # Fallback if coordinates are missing
                center_x = img_width / 2
                center_y = img_height / 2
                draw.ellipse([(center_x - 10, center_y - 10), (center_x + 10, center_y + 10)], outline="purple", width=3)
                draw.text((center_x + 15, center_y), "Move (Coords N/A)", fill="purple")
                print("Debug: Drawing placeholder move indicator (coordinates unavailable)")

        elif action_type == 'type':
            target_element = data.get('target_element')
            typed_text = data.get('typed_text', '')
            
            # Draw green box around the target typing element
            if target_element:
                try:
                    el_bbox = target_element.bounding_box()
                    if el_bbox:
                         draw_x = el_bbox['x'] * dpr
                         draw_y = el_bbox['y'] * dpr
                         draw_w = el_bbox['width'] * dpr
                         draw_h = el_bbox['height'] * dpr
                         draw.rectangle([draw_x, draw_y, draw_x + draw_w, draw_y + draw_h], outline="lime", width=3) # Lime green highlight for TARGET typing field
                         # Add text label
                         label = f"Typing Target\nText: '{typed_text[:20]}{'...' if len(typed_text) > 20 else ''}'"
                         draw.text((draw_x, draw_y + draw_h + 5), label, fill="lime")
                except PlaywrightError as bbox_err:
                     print(f"Debug: Error getting bounding box for typing target element: {bbox_err}")

        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        filename = f"debug_{action_type}_{ts}.png"
        img.save(filename)
        print(f"Debug: Saved screenshot to {filename}")
    except PlaywrightError as pe_debug:
        print(f"Debug: Playwright error during screenshot/drawing for '{action_type}': {pe_debug}")
    except Exception as debug_e:
        print(f"Debug: General error saving screenshot for '{action_type}': {debug_e}")

def main():
    """Main loop for the automation process."""
    parser = argparse.ArgumentParser(description="Automate website interaction and recording.")
    parser.add_argument('--debug', action='store_true', help='Enable debug mode to save screenshots of click targets.')
    args = parser.parse_args()
    debug_mode = args.debug

    if debug_mode:
        print("!!! DEBUG MODE ENABLED: Click target screenshots will be saved. !!!")

    print("Starting automation script...")
    urls = load_websites(SEED_WEBSITES_FILE)
    if not urls:
        print("No URLs loaded, exiting.")
        return

    pyautogui.FAILSAFE = True
    print("PyAutoGUI Fail-Safe enabled: Move mouse to top-left corner to stop script.")
    print("Ensure DuckTrack is running and ready to record (uses internal hotkeys).")
    time.sleep(3)

    try: # Outer loop for KeyboardInterrupt
        while True:
            selected_url = random.choice(urls)
            print("-" * 50)
            print(f"Selected URL for this run: {selected_url}")
            
            browser = None # Initialize browser to None for this iteration
            page = None
            context = None
            
            try: # Inner try for per-URL browser management
                with sync_playwright() as p:
                    print(f"Launching new {BROWSER_TYPE} browser instance...")
                    browser = getattr(p, BROWSER_TYPE).launch(headless=False)
                    context = browser.new_context(no_viewport=True) # Use no_viewport
                    page = context.new_page()
                    print("Browser launched for this URL.")

                    try: # Innermost try for navigation/interaction errors
                        print(f"Navigating page to: {selected_url}")
                        # Use wait_until='domcontentloaded' or 'load'? 'load' is generally safer for full interaction.
                        page.goto(selected_url, timeout=INTERACTION_TIMEOUT_MS * 2, wait_until='load')
                        
                        # --- Pause before starting recording ---
                        time.sleep(2.0)  # Ensure page is fully loaded and stable
                        
                        # --- Trigger Start Recording (AFTER navigation) --- 
                        print("Starting recording...")
                        trigger_hotkey(RECORD_HOTKEY)
                        time.sleep(3.0)  # Give recording time to start before interaction
                        
                        # --- Check if browser is still the active window ---
                        if sys.platform == 'darwin':  # macOS
                            # Try to reactivate the browser window through AppleScript
                            browser_activate_script = f'''
                                tell application "System Events"
                                    tell application process "Chromium"
                                        set frontmost to true
                                    end tell
                                end tell
                                return "Browser reactivated"
                            '''
                            try:
                                subprocess.run(['osascript', '-e', browser_activate_script], 
                                              capture_output=True, text=True, check=False)
                                print("Reactivated browser window after starting recording")
                                time.sleep(1.0)
                            except Exception as e:
                                print(f"Error reactivating browser: {e}")
                        
                        # --- Now perform interactions ---
                        interact_with_website(page, debug_mode=debug_mode)

                        # --- Pause before stopping recording ---
                        time.sleep(2.0)  # Ensure interactions are complete
                        
                        # --- Trigger Stop Recording (AFTER interactions are done) --- 
                        print("Stopping recording...")
                        trigger_hotkey(STOP_HOTKEY)
                        time.sleep(2.0)  # Give recording time to complete saving

                    except PlaywrightError as pe:
                        print(f"Playwright error during navigation/interaction for {selected_url}: {pe}")
                        # Still attempt to stop recording if an error occurred
                        try:
                            trigger_hotkey(STOP_HOTKEY)
                        except Exception as stop_err:
                            print(f"Error stopping recording after error: {stop_err}")
                    except Exception as e:
                        print(f"An unexpected error occurred during interaction for {selected_url}: {e}")
                        traceback.print_exc()
                        # Still attempt to stop recording if an error occurred
                        try:
                            trigger_hotkey(STOP_HOTKEY)
                        except Exception as stop_err:
                            print(f"Error stopping recording after error: {stop_err}")
                    finally:
                        print("Interaction cycle finished for this URL.")
            
            except Exception as browser_launch_err:
                 print(f"FATAL: Failed to launch/setup browser for {selected_url}: {browser_launch_err}")
                 traceback.print_exc()
                 # Stop recording in case it's still running
                 try:
                     trigger_hotkey(STOP_HOTKEY)
                 except Exception as stop_err:
                     print(f"Error stopping recording after browser launch error: {stop_err}")
            finally:
                # --- Ensure browser instance for this URL is closed --- 
                if browser:
                    print("Closing browser instance...")
                    try:
                        browser.close()
                    except Exception as close_err:
                        print(f"Warning: Error closing browser instance: {close_err}")
                else:
                    print("No browser instance was successfully launched for this URL.")

            # --- Wait before next URL --- 
            wait_time = random.uniform(MIN_WAIT_SECONDS, MAX_WAIT_SECONDS)
            print(f"Waiting {wait_time:.2f} seconds before launching browser for next URL...")
            time.sleep(wait_time)

    except KeyboardInterrupt:
        print("Script interrupted by user. Exiting cleanly.")
        # Stop recording if interrupted
        try:
            trigger_hotkey(STOP_HOTKEY)
        except Exception as stop_err:
            print(f"Error stopping recording after user interruption: {stop_err}")
    except Exception as e:
        print(f"A critical error occurred in the main loop control: {e}")
        traceback.print_exc()
        # Stop recording if error
        try:
            trigger_hotkey(STOP_HOTKEY)
        except Exception as stop_err:
            print(f"Error stopping recording after critical error: {stop_err}")
    finally:
        # No browser instance should be dangling here due to the inner finally
        print("Automation finished.")


if __name__ == "__main__":
    main() 