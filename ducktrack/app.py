import os
import sys
from platform import system
import threading

try:
    from pynput import keyboard
except ImportError:
    print("Warning: pynput not found. Global hotkeys will be disabled.")
    print("Install it via pip install pynput (or from requirements.txt)")
    keyboard = None

from PyQt6.QtCore import QTimer, pyqtSlot, pyqtSignal, QObject
from PyQt6.QtGui import QAction, QIcon
from PyQt6.QtWidgets import (QApplication, QCheckBox, QDialog, QFileDialog,
                             QFormLayout, QLabel, QLineEdit, QMenu,
                             QMessageBox, QPushButton, QSystemTrayIcon,
                             QTextEdit, QVBoxLayout, QWidget)

from .obs_client import close_obs, is_obs_running, open_obs
from .playback import Player, get_latest_recording
from .recorder import Recorder
from .util import get_recordings_dir, open_file


# Define the hotkeys (using pynput format)
# You might want to make these configurable later
HOTKEYS = {
    # '<ctrl>+<alt>+r': 'toggle_record',
    # '<ctrl>+<alt>+s': 'toggle_record', # Use the same toggle function for stop
    # '<ctrl>+<alt>+p': 'toggle_pause'
    '<ctrl>+<alt>+<shift>+<f9>': 'toggle_record',
    '<ctrl>+<alt>+<shift>+<f10>': 'toggle_pause'
}

class HotkeyListener(threading.Thread, QObject):
    # Define signals to communicate back to the main GUI thread
    record_toggled = pyqtSignal()
    pause_toggled = pyqtSignal()

    def __init__(self):
        # Need to call constructors for both parents
        threading.Thread.__init__(self, daemon=True)
        QObject.__init__(self)
        self.listener = None
        self._callbacks = {
            'toggle_record': self.on_toggle_record,
            'toggle_pause': self.on_toggle_pause
        }
        # Add a flag to track if running
        self._is_running = threading.Event()

    def run(self):
        if keyboard is None: # Check if pynput was imported
            print("HotkeyListener: pynput module not available. Thread exiting.")
            return

        print("HotkeyListener: Starting listener thread...")
        self._is_running.set() # Signal that the thread is attempting to start the listener
        try:
            # Map hotkeys from the dict to their corresponding methods
            hotkey_map = {key: self._callbacks[action] for key, action in HOTKEYS.items()}
            print(f"HotkeyListener: Mapping keys: {hotkey_map}")

            # Create and run the hotkey listener
            with keyboard.GlobalHotKeys(hotkey_map) as self.listener:
                print("HotkeyListener: GlobalHotKeys listener started successfully.")
                self.listener.join() # Keep the thread alive while listening
        except Exception as e:
            # TODO: Maybe emit a signal to show an error in the GUI?
            print(f"HotkeyListener: Error starting/running hotkey listener: {e}")
            print("HotkeyListener: Hotkeys may not function.")
        finally:
            self._is_running.clear() # Signal that the listener loop has exited
            print("HotkeyListener: Listener thread stopped.")


    def stop(self):
        print("HotkeyListener: Attempting to stop listener...")
        if self.listener and self._is_running.is_set():
             print("HotkeyListener: Calling listener.stop()...")
             # pynput's stop might need to be called from a different thread
             # but GlobalHotKeys handles this internally when exiting the 'with' block.
             # Forcing stop might still be useful for abrupt termination.
             try:
                  keyboard.Listener.stop(self.listener) # Attempt to stop the underlying listener
                  # Note: GlobalHotKeys.stop() might also work depending on pynput version
             except Exception as e:
                  print(f"HotkeyListener: Error during explicit stop: {e}")
        elif not self._is_running.is_set():
             print("HotkeyListener: Listener was not running.")
        else:
             print("HotkeyListener: Listener object not found or not running.")


    # --- Callbacks that emit signals ---
    # These are called by pynput in the listener thread

    def on_toggle_record(self):
        # Add print statement HERE
        print(f"HotkeyListener: Detected hotkey for 'Toggle Record'. Emitting signal...")
        self.record_toggled.emit()

    def on_toggle_pause(self):
        # Add print statement HERE
        print(f"HotkeyListener: Detected hotkey for 'Toggle Pause'. Emitting signal...")
        self.pause_toggled.emit()


class TitleDescriptionDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.setWindowTitle("Recording Details")

        layout = QVBoxLayout(self)

        self.form_layout = QFormLayout()

        self.title_label = QLabel("Title:")
        self.title_input = QLineEdit(self)
        self.form_layout.addRow(self.title_label, self.title_input)

        self.description_label = QLabel("Description:")
        self.description_input = QTextEdit(self)
        self.form_layout.addRow(self.description_label, self.description_input)

        layout.addLayout(self.form_layout)

        self.submit_button = QPushButton("Save", self)
        self.submit_button.clicked.connect(self.accept)
        layout.addWidget(self.submit_button)

    def get_values(self):
        return self.title_input.text(), self.description_input.toPlainText()

class MainInterface(QWidget):
    def __init__(self, app: QApplication):
        super().__init__()
        self.tray = QSystemTrayIcon(QIcon(resource_path("assets/duck.png")))
        self.tray.show()
                
        self.app = app
        
        self.init_tray()
        self.init_window()
        self.init_hotkeys()
        
        if not is_obs_running():
            self.obs_process = open_obs()

    def init_window(self):
        self.setWindowTitle("DuckTrack")
        layout = QVBoxLayout(self)
        
        self.toggle_record_button = QPushButton("Start Recording", self)
        self.toggle_record_button.clicked.connect(self.toggle_record)
        layout.addWidget(self.toggle_record_button)
        
        self.toggle_pause_button = QPushButton("Pause Recording", self)
        self.toggle_pause_button.clicked.connect(self.toggle_pause)
        self.toggle_pause_button.setEnabled(False)
        layout.addWidget(self.toggle_pause_button)
        
        self.show_recordings_button = QPushButton("Show Recordings", self)
        self.show_recordings_button.clicked.connect(lambda: open_file(get_recordings_dir()))
        layout.addWidget(self.show_recordings_button)
        
        self.play_latest_button = QPushButton("Play Latest Recording", self)
        self.play_latest_button.clicked.connect(self.play_latest_recording)
        layout.addWidget(self.play_latest_button)
        
        self.play_custom_button = QPushButton("Play Custom Recording", self)
        self.play_custom_button.clicked.connect(self.play_custom_recording)
        layout.addWidget(self.play_custom_button)
        
        self.replay_recording_button = QPushButton("Replay Recording", self)
        self.replay_recording_button.clicked.connect(self.replay_recording)
        self.replay_recording_button.setEnabled(False)
        layout.addWidget(self.replay_recording_button)
        
        self.quit_button = QPushButton("Quit", self)
        self.quit_button.clicked.connect(self.quit)
        layout.addWidget(self.quit_button)
        
        self.natural_scrolling_checkbox = QCheckBox("Natural Scrolling", self, checked=system() == "Darwin")
        layout.addWidget(self.natural_scrolling_checkbox)

        self.natural_scrolling_checkbox.stateChanged.connect(self.toggle_natural_scrolling)
        
        self.setLayout(layout)
        
    def init_tray(self):
        self.menu = QMenu()
        self.tray.setContextMenu(self.menu)

        self.toggle_record_action = QAction("Start Recording")
        self.toggle_record_action.triggered.connect(self.toggle_record)
        self.menu.addAction(self.toggle_record_action)

        self.toggle_pause_action = QAction("Pause Recording")
        self.toggle_pause_action.triggered.connect(self.toggle_pause)
        self.toggle_pause_action.setVisible(False)
        self.menu.addAction(self.toggle_pause_action)
        
        self.show_recordings_action = QAction("Show Recordings")
        self.show_recordings_action.triggered.connect(lambda: open_file(get_recordings_dir()))
        self.menu.addAction(self.show_recordings_action)
        
        self.play_latest_action = QAction("Play Latest Recording")
        self.play_latest_action.triggered.connect(self.play_latest_recording)
        self.menu.addAction(self.play_latest_action)

        self.play_custom_action = QAction("Play Custom Recording")
        self.play_custom_action.triggered.connect(self.play_custom_recording)
        self.menu.addAction(self.play_custom_action)
        
        self.replay_recording_action = QAction("Replay Recording")
        self.replay_recording_action.triggered.connect(self.replay_recording)
        self.menu.addAction(self.replay_recording_action)
        self.replay_recording_action.setVisible(False)

        self.quit_action = QAction("Quit")
        self.quit_action.triggered.connect(self.quit)
        self.menu.addAction(self.quit_action)
        
        self.menu.addSeparator()
        
        self.natural_scrolling_option = QAction("Natural Scrolling", checkable=True, checked=system() == "Darwin")
        self.natural_scrolling_option.triggered.connect(self.toggle_natural_scrolling)
        self.menu.addAction(self.natural_scrolling_option)
        
    def init_hotkeys(self):
        """Initializes and starts the global hotkey listener."""
        if keyboard is None: # Check if pynput is available
             print("Hotkey listener disabled because pynput module is not loaded.")
             self.hotkey_listener = None
             return
        try:
            self.hotkey_listener = HotkeyListener()
            # Connect signals from the listener thread to slots in the main GUI thread
            self.hotkey_listener.record_toggled.connect(self.toggle_record)
            self.hotkey_listener.pause_toggled.connect(self.toggle_pause)
            self.hotkey_listener.start()
            print("Hotkey listener initialized and started.")
        except NameError as e:
             # Catch if pynput isn't installed (already handled by keyboard check, but good practice)
             print(f"Could not initialize hotkeys. Is pynput installed correctly? Error: {e}")
             self.hotkey_listener = None # Ensure attribute exists
        except Exception as e:
            print(f"Failed to initialize hotkey listener: {e}")
            self.hotkey_listener = None # Ensure attribute exists

    @pyqtSlot()
    def replay_recording(self):
        player = Player()
        if hasattr(self, "last_played_recording_path"):
            player.play(self.last_played_recording_path)
        else:
            self.display_error_message("No recording has been played yet!")

    @pyqtSlot()
    def play_latest_recording(self):
        player = Player()
        recording_path = get_latest_recording()
        self.last_played_recording_path = recording_path
        self.replay_recording_action.setVisible(True)
        self.replay_recording_button.setEnabled(True)
        player.play(recording_path)

    @pyqtSlot()
    def play_custom_recording(self):
        player = Player()
        directory = QFileDialog.getExistingDirectory(None, "Select Recording", get_recordings_dir())
        if directory:
            self.last_played_recording_path = directory
            self.replay_recording_button.setEnabled(True)
            self.replay_recording_action.setVisible(True)
            player.play(directory)

    @pyqtSlot()
    def quit(self):
        # Stop the hotkey listener first
        if hasattr(self, "hotkey_listener") and self.hotkey_listener:
            print("Stopping hotkey listener...")
            self.hotkey_listener.stop()
            self.hotkey_listener.join(timeout=0.5) # Wait briefly for thread to stop
            print("Hotkey listener should be stopped.")

        if hasattr(self, "recorder_thread") and self.recorder_thread.isRunning():
            print("Stopping recorder thread...")
            # Ensure recording is stopped cleanly before quitting
            if self.recorder_thread._is_recording:
                 # If thread is running but not recording (e.g. paused), just stop it.
                 self.recorder_thread.stop_recording() # Force stop signal just in case
                 # Wait for QThread to finish using wait() instead of join()
                 if not self.recorder_thread.wait(1000): # Wait 1 second (in ms)
                     print("Warning: Recorder thread did not finish cleanly after stop signal.")
            print("Recorder thread should be stopped.")


        if hasattr(self, "obs_process"):
            close_obs(self.obs_process)
        self.app.quit()

    def closeEvent(self, event):
        self.quit()

    @pyqtSlot()
    def toggle_natural_scrolling(self):
        sender = self.sender()

        if sender == self.natural_scrolling_checkbox:
            state = self.natural_scrolling_checkbox.isChecked()
            self.natural_scrolling_option.setChecked(state)
        else:
            state = self.natural_scrolling_option.isChecked()
            self.natural_scrolling_checkbox.setChecked(state)

    @pyqtSlot()
    def toggle_pause(self):
        if not hasattr(self, "recorder_thread") or not self.recorder_thread.isRunning():
             print("Warning: Tried to pause/resume when not recording.")
             self.tray.showMessage("DuckTrack", "Cannot pause/resume: Not recording", QSystemTrayIcon.MessageIcon.Warning, 1500)
             return
             
        if self.recorder_thread._is_paused:
            self.recorder_thread.resume_recording()
            self.toggle_pause_action.setText("Pause Recording")
            self.toggle_pause_button.setText("Pause Recording")
            # Show notification
            self.tray.showMessage("DuckTrack", "Recording Resumed", QSystemTrayIcon.MessageIcon.Information, 1500) # 1.5 sec duration
        else:
            self.recorder_thread.pause_recording()
            self.toggle_pause_action.setText("Resume Recording")
            self.toggle_pause_button.setText("Resume Recording")
            # Show notification
            self.tray.showMessage("DuckTrack", "Recording Paused", QSystemTrayIcon.MessageIcon.Information, 1500)

    @pyqtSlot()
    def toggle_record(self):
        if not hasattr(self, "recorder_thread") or not self.recorder_thread.isRunning():
            # Start recording
            print("Starting new recording...")
            self.recorder_thread = Recorder(natural_scrolling=self.natural_scrolling_checkbox.isChecked())
            self.recorder_thread.recording_stopped.connect(self.on_recording_stopped)
            self.recorder_thread.start()
            self.update_menu(True)
            # Show notification
            self.tray.showMessage("DuckTrack", "Recording Started", QSystemTrayIcon.MessageIcon.Information, 1500)
        else:
            # Stop recording
            print("Stopping recording...")
            self.recorder_thread.stop_recording()
            # Wait for the thread to finish writing files etc. using QThread's wait()
            if not self.recorder_thread.wait(5000): # Changed join to wait (timeout in ms)
                 print("Warning: Recorder thread did not finish cleanly after stop signal.")
                 # Terminate might be risky with file operations, but it's a fallback
                 self.recorder_thread.terminate()

            recording_dir = self.recorder_thread.recording_path
            print(f"Recording saved to: {recording_dir}")
            
            # Clean up the thread object
            del self.recorder_thread
            # Update UI state (needs to be called after thread cleanup)
            self.on_recording_stopped() 
            # Show notification - Moved after stop logic completes
            self.tray.showMessage("DuckTrack", f"Recording Stopped\nSaved to: {os.path.basename(recording_dir)}", QSystemTrayIcon.MessageIcon.Information, 2500) # Longer duration for stop message

    @pyqtSlot()
    def on_recording_stopped(self):
        print("Recording stopped signal received.")
        self.update_menu(False)

    def update_menu(self, is_recording: bool):
        self.toggle_record_button.setText("Stop Recording" if is_recording else "Start Recording")
        self.toggle_record_action.setText("Stop Recording" if is_recording else "Start Recording")
        
        self.toggle_pause_button.setEnabled(is_recording)
        self.toggle_pause_action.setVisible(is_recording)

    def display_error_message(self, message):
        QMessageBox.critical(None, "Error", message)
        
def resource_path(relative_path: str) -> str:
    if hasattr(sys, '_MEIPASS'):
        base_path = getattr(sys, "_MEIPASS")
    else:
        base_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')

    return os.path.join(base_path, relative_path)