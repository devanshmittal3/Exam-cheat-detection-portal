import cv2
import time
import imutils
import threading

# Load Haar Cascade for face detection (basic)
# Ensure you have the XML file in your OpenCV data path, or use Dlib/Mediapipe for better results later
face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')

# Global variable to control the frame skip rate for detection
DETECTION_FRAME_SKIP = 3  # Perform full detection every 3rd frame
frame_count = 0 

class Camera(object):
    """
    A Singleton Camera class that runs in a separate thread to continuously 
    capture and process frames, making them available to all consumers (Admin/Student).
    """
    thread = None  # Background thread for capturing
    frame = None   # Current frame (as JPEG bytes)
    last_access = 0 # Timestamp of last access
    
    # Static members to hold logging info (shared across instances)
    log_callback = None
    student_id = None
    last_log_time = time.time()
    last_face_status = 'detected'

    def initialize(self, student_id, log_callback):
        """Initializes the static variables and starts the thread if not running."""
        Camera.student_id = student_id
        Camera.log_callback = log_callback
        if Camera.thread is None:
            Camera.thread = threading.Thread(target=self._thread, daemon=True)
            Camera.thread.start()
            
    def get_frame(self):
        """Returns the latest frame (JPEG bytes) produced by the background thread."""
        Camera.last_access = time.time()
        # Wait until the first frame is available
        while Camera.frame is None:
            time.sleep(0.05)
        return Camera.frame

    @staticmethod
    def log_event(level, message):
        """Sends an event back to the Flask application for central logging."""
        if Camera.log_callback and Camera.student_id:
            Camera.log_callback(Camera.student_id, 'video', level, message)

    @staticmethod
    def _thread():
        """The main camera processing loop running in a background thread."""
        global frame_count
        camera = cv2.VideoCapture(0)
        
        # --- ROBUST CAMERA INITIALIZATION ---
        time.sleep(1) # Give the camera a moment to initialize

        # Try to use a different camera index if the default (0) is unavailable
        if not camera.isOpened():
             camera = cv2.VideoCapture(1) 

        if not camera.isOpened():
            print("CRITICAL ERROR: Could not open camera (tried 0 and 1). Is the device plugged in and not in use by another app?")
            # Set a generic error frame so the stream doesn't crash (requires a 'no_camera.png' file or similar)
            # For simplicity, we'll just set a placeholder
            Camera.frame = b'' 
            return
        # --- END OF ROBUST CHECK ---

        # Optimize camera settings
        camera.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        
        # Pre-allocate variables
        faces = [] 
        
        while True:
            t_start = time.time()
            success, frame = camera.read()
            if not success:
                time.sleep(0.5)
                continue
                
            frame = imutils.resize(frame, width=500)
            
            # --- Detection & Logging (Run on a skipped frame rate for performance) ---
            if frame_count % DETECTION_FRAME_SKIP == 0:
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                # Use a smaller image for detection to speed it up
                tiny_gray = cv2.resize(gray, (0, 0), fx=0.5, fy=0.5) 
                
                faces = face_cascade.detectMultiScale(tiny_gray, scaleFactor=1.1, minNeighbors=5, minSize=(15, 15))
                
                # Logging logic
                current_status = 'detected'
                log_message = "Face detected and centered."
                log_level = "INFO"

                if len(faces) == 0:
                    current_status = 'not_detected'
                    log_level = "CRITICAL"
                    log_message = "User Face NOT DETECTED (out of frame/covered)."
                elif len(faces) > 1:
                    current_status = 'multiple'
                    log_level = "CRITICAL"
                    log_message = f"MULTIPLE FACES detected: {len(faces)} people in view."

                # Log only if status changed or every 5s (INFO)
                if current_status != Camera.last_face_status or (current_status == 'detected' and time.time() - Camera.last_log_time > 5):
                    Camera.log_event(log_level, log_message)
                    Camera.last_log_time = time.time()
                    Camera.last_face_status = current_status
            
            frame_count += 1
            # --- End of Detection & Logging ---

            # Encode the processed frame to JPEG for web streaming
            ret, jpeg = cv2.imencode('.jpg', frame)
            Camera.frame = jpeg.tobytes()
            
            # **FPS CONTROL:** Target 30 FPS (0.033 seconds per frame)
            t_end = time.time()
            frame_time = t_end - t_start
            target_delay = 1.0 / 30.0 
            sleep_time = target_delay - frame_time
            if sleep_time > 0:
                time.sleep(sleep_time)

            # Cleanup: Stop thread if no clients access the camera for 10 seconds
            if time.time() - Camera.last_access > 10:
                print("Stopping camera thread due to inactivity.")
                break
        
        camera.release()
        Camera.thread = None 

# --- CRITICAL COMPATIBILITY FIX ---
# This line allows app.py to import 'VideoCamera' without changing app.py's code
VideoCamera = Camera