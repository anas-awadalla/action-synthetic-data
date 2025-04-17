import json
import random
import time
import sys
import traceback
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
INTERACTION_DELAY_MIN = 0.5
INTERACTION_DELAY_MAX = 1.0
NUM_INTERACTIONS = 50
BROWSER_TYPE = 'chromium'

# Define hotkeys for pyautogui to trigger (matching those in ducktrack app)
RECORD_HOTKEY = ['ctrl', 'alt', 'shift', 'f9'] 
STOP_HOTKEY = ['ctrl', 'alt', 'shift', 'f9'] # Using the same key for toggle
# Define a separate hotkey for pause if needed by the automation script (optional)
# PAUSE_HOTKEY = ['ctrl', 'alt', 'shift', 'f10']

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

def trigger_hotkey(keys):
    """Triggers a keyboard hotkey combination using pyautogui."""
    try:
        print(f"Triggering hotkey via pyautogui: {'+'.join(keys)}")
        pyautogui.hotkey(*keys)
        time.sleep(1.5) # Increased delay to ensure app registers it
    except Exception as e:
        print(f"Warning: Could not trigger hotkey {'+'.join(keys)}. Error: {e}")
        print("Check pyautogui permissions/dependencies if this persists (e.g., Accessibility on macOS).")

def get_browser_window(browser_type):
    """Attempt to find the browser window using pygetwindow."""
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

def interact_with_website(page, num_interactions=NUM_INTERACTIONS, debug_mode=False):
    """Uses Playwright to find elements, pygetwindow to find the window, and pyautogui to interact."""
    print(f"Page loaded: {page.title()}")
    time.sleep(random.uniform(1.5, 3.0))

    # Get initial domain
    initial_url = page.url
    initial_domain = get_domain(initial_url)
    if initial_domain:
        print(f"Operating on domain: {initial_domain}")
    else:
        print(f"Warning: Could not determine initial domain for {initial_url}")

    print("Attempting to toggle fullscreen (F11)...")
    pyautogui.press('f11')
    time.sleep(3.5) # Increased wait time for fullscreen transition

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
            action = random.choices(['scroll', 'click', 'type', 'move'], weights=[15, 35, 35, 15], k=1)[0] # Example: Scroll 15%, Click 35%, Type 35%, Move 15%
            print(f"Chosen action: '{action}'")

            if action == 'scroll' and window_pos is not None: # Keep the window_pos check
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
                        num_chunks = 5 # Number of steps for the scroll
                        chunk_amount = scroll_amount // num_chunks
                        remainder = scroll_amount % num_chunks
                        scroll_delay = 0.04 # Small delay between chunks

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
                            screen_x = window_pos['x'] + (logical_center_x * dpr)
                            screen_y = window_pos['y'] + (logical_center_y * dpr)
                            screen_x = max(0, min(screen_width - 1, int(screen_x)))
                            screen_y = max(0, min(screen_height - 1, int(screen_y)))

                            # Perform Typing
                            random_input_text = generate_random_text()
                            print(f"Action: Typing simulated text ('{random_input_text}') into element '{element_text_desc}' at screen coords ({screen_x}, {screen_y})")
                            pyautogui.moveTo(screen_x, screen_y, duration=random.uniform(0.2, 0.5))
                            pyautogui.click() # Click to focus
                            # --- Debug Visualization for Typing --- 
                            if debug_mode:
                                save_debug_screenshot(page, 'type', {
                                    'target_element': target_element,
                                    'typed_text': random_input_text
                                }, dpr=dpr,
                                    visible_interactive_elements=visible_interactive,
                                    visible_typing_elements=visible_typing)
                            # --- End Debug Visualization ---
                            time.sleep(random.uniform(0.2, 0.4)) # Wait briefly for focus
                            
                            # Simulate typing character by character with mistakes
                            current_typed = ""
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

                            screen_x = window_pos['x'] + (logical_center_x * dpr)
                            screen_y = window_pos['y'] + (logical_center_y * dpr)
                            screen_x = max(0, min(screen_width - 1, int(screen_x)))
                            screen_y = max(0, min(screen_height - 1, int(screen_y)))

                            # Perform Typing
                            random_input_text = generate_random_text()
                            print(f"Action: Typing simulated text ('{random_input_text}') into element '{element_text_desc}' at screen coords ({screen_x}, {screen_y})")
                            pyautogui.moveTo(screen_x, screen_y, duration=random.uniform(0.2, 0.5))
                            pyautogui.click() # Click to focus
                            # --- Debug Visualization for Typing --- 
                            if debug_mode:
                                save_debug_screenshot(page, 'type', {
                                    'target_element': target_element,
                                    'typed_text': random_input_text
                                }, dpr=dpr,
                                    visible_interactive_elements=visible_interactive,
                                    visible_typing_elements=visible_typing)
                            # --- End Debug Visualization ---
                            time.sleep(random.uniform(0.2, 0.4)) # Wait briefly for focus
                            
                            # Simulate typing character by character with mistakes
                            current_typed = ""
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
                rand_x = random.randint(0, screen_width - 1)
                rand_y = random.randint(0, screen_height - 1)
                print(f"Action: Moving mouse randomly to ({rand_x}, {rand_y})")
                if debug_mode:
                    # Pass ALL found visible elements to the debug function
                    save_debug_screenshot(page, 'move', {
                        'screen_x': rand_x, 
                        'screen_y': rand_y,
                        'window_pos': window_pos
                    }, dpr=dpr,
                        visible_interactive_elements=visible_interactive,
                        visible_typing_elements=visible_typing)
                pyautogui.moveTo(rand_x, rand_y, duration=random.uniform(0.3, 0.8))

            time.sleep(random.uniform(INTERACTION_DELAY_MIN, INTERACTION_DELAY_MAX))

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
                        
                        # --- Trigger Start Recording (AFTER navigation) --- 
                        trigger_hotkey(RECORD_HOTKEY)
                        
                        interact_with_website(page, debug_mode=debug_mode)

                    except PlaywrightError as pe:
                        print(f"Playwright error during navigation/interaction for {selected_url}: {pe}")
                        # No need to create a new page here, as the browser will be closed
                    except Exception as e:
                        print(f"An unexpected error occurred during interaction for {selected_url}: {e}")
                        traceback.print_exc()
                    finally:
                        # --- Trigger Stop Recording (always attempt) --- 
                        trigger_hotkey(STOP_HOTKEY)
                        print("Interaction cycle finished for this URL.")
            
            except Exception as browser_launch_err:
                 print(f"FATAL: Failed to launch/setup browser for {selected_url}: {browser_launch_err}")
                 traceback.print_exc()
                 # Optionally wait or break loop if browser launch fails repeatedly
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
    except Exception as e:
        print(f"A critical error occurred in the main loop control: {e}")
        traceback.print_exc()
    finally:
        # No browser instance should be dangling here due to the inner finally
        print("Automation finished.")


if __name__ == "__main__":
    main() 