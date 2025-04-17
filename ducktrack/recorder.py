import json
import os
import time
from datetime import datetime
from platform import system
from queue import Queue

from pynput import keyboard, mouse
from pynput.keyboard import KeyCode
from PyQt6.QtCore import QThread, pyqtSignal

from .metadata import MetadataManager
from .obs_client import OBSClient
from .util import fix_windows_dpi_scaling, get_recordings_dir


class Recorder(QThread):
    """
    Makes recordings.
    """
    
    recording_stopped = pyqtSignal()

    def __init__(self, natural_scrolling: bool):
        super().__init__()
        print("[Recorder] Initializing...")
        
        if system() == "Windows":
            fix_windows_dpi_scaling()
            
        self.recording_path = self._get_recording_path()
        
        self._is_recording = False
        self._is_paused = False
        
        self.event_queue = Queue()
        self.events_file = open(os.path.join(self.recording_path, "events.jsonl"), "a")
        
        self.metadata_manager = MetadataManager(
            recording_path=self.recording_path, 
            natural_scrolling=natural_scrolling
        )
        self.obs_client = OBSClient(recording_path=self.recording_path, 
                                    metadata=self.metadata_manager.metadata)

        self.mouse_listener = mouse.Listener(
            on_move=self.on_move,
            on_click=self.on_click,
            on_scroll=self.on_scroll)
        
        self.keyboard_listener = keyboard.Listener(
            on_press=self.on_press, 
            on_release=self.on_release)
        
        print("[Recorder] Initialization complete.")
        
    def on_move(self, x, y):
        print(f"[Recorder] on_move called: ({x}, {y})")
        if not self._is_paused:
            self.event_queue.put({"time_stamp": time.perf_counter(), 
                                  "action": "move", 
                                  "x": x, 
                                  "y": y}, block=False)
        
    def on_click(self, x, y, button, pressed):
        print(f"[Recorder] on_click called: ({x}, {y}), button={button}, pressed={pressed}")
        if not self._is_paused:
            self.event_queue.put({"time_stamp": time.perf_counter(), 
                                  "action": "click", 
                                  "x": x, 
                                  "y": y, 
                                  "button": button.name, 
                                  "pressed": pressed}, block=False)
    
    def on_scroll(self, x, y, dx, dy):
        print(f"[Recorder] on_scroll called: ({x}, {y}), delta=({dx}, {dy})")
        if not self._is_paused:
            self.event_queue.put({"time_stamp": time.perf_counter(), 
                                  "action": "scroll", 
                                  "x": x, 
                                  "y": y, 
                                  "dx": dx, 
                                  "dy": dy}, block=False)
    
    def on_press(self, key):
        if not self._is_paused:
            self.event_queue.put({"time_stamp": time.perf_counter(), 
                                  "action": "press", 
                                  "name": key.char if type(key) == KeyCode else key.name}, block=False)

    def on_release(self, key):
        if not self._is_paused:
            self.event_queue.put({"time_stamp": time.perf_counter(), 
                                  "action": "release", 
                                  "name": key.char if type(key) == KeyCode else key.name}, block=False)

    def run(self):
        print("[Recorder] Thread starting (run method)...")
        self._is_recording = True
        
        self.metadata_manager.collect()
        self.obs_client.start_recording()
        
        print("[Recorder] Starting mouse listener...")
        self.mouse_listener.start()
        print("[Recorder] Starting keyboard listener...")
        self.keyboard_listener.start()
                
        print("[Recorder] Entering main event loop...")
        while self._is_recording:
            event = self.event_queue.get()
            # print(f"[Recorder] Got event from queue: {event['action']}") # Optional: uncomment for very verbose logging
            self.events_file.write(json.dumps(event) + "\n")
        print("[Recorder] Exited main event loop.")

    def stop_recording(self):
        if self._is_recording:
            self._is_recording = False

            self.metadata_manager.end_collect()
                        
            self.mouse_listener.stop()
            self.keyboard_listener.stop()
            
            self.obs_client.stop_recording()
            self.metadata_manager.add_obs_record_state_timings(self.obs_client.record_state_events)
            self.events_file.close()
            self.metadata_manager.save_metadata()
            
            self.recording_stopped.emit()
    
    def pause_recording(self):
        if not self._is_paused and self._is_recording:
            self._is_paused = True
            self.obs_client.pause_recording()
            self.event_queue.put({"time_stamp": time.perf_counter(),
                                  "action": "pause"}, block=False)

    def resume_recording(self):
        if self._is_paused and self._is_recording:
            self._is_paused = False
            self.obs_client.resume_recording()
            self.event_queue.put({"time_stamp": time.perf_counter(),
                                  "action": "resume"}, block=False)

    def _get_recording_path(self) -> str:
        recordings_dir = get_recordings_dir()

        if not os.path.exists(recordings_dir):
            os.mkdir(recordings_dir)

        current_time = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        
        recording_path = os.path.join(recordings_dir, f"recording-{current_time}")
        os.mkdir(recording_path)

        return recording_path