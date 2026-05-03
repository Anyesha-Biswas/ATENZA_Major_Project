"""
Atenza Live Dashboard - Flask-based Real-time Focus Monitoring
Optimized for smooth video streaming without Streamlit overhead
"""

from flask import Flask, render_template, Response, jsonify, request
import cv2
import numpy as np
import mediapipe as mp
# from ultralytics import YOLO
from camera.webcam import WebcamManager
from collections import deque
from datetime import datetime
import threading
import json
import os
import time

# ================== FLASK APP SETUP ==================
app = Flask(__name__, template_folder='templates', static_folder='static')
app.config['JSON_SORT_KEYS'] = False

# ================== GLOBAL STATE ==================
class ApplicationState:
    def __init__(self):
        self.camera = None
        self.face_mesh = None
        self.yolo_model = None
        self.is_running = False
        
        # Metrics tracking
        self.focus_history = deque(maxlen=100)
        self.phone_detections = deque(maxlen=50)
        self.blink_counts = deque(maxlen=30)
        self.gaze_directions = deque(maxlen=50)
        self.gaze_stability_history = deque(maxlen=100)
        
        # Current state
        self.current_metrics = {
            'focus_score': 50,
            'blink_score': 75,
            'gaze_stability': 75,
            'phone_detected': False,
            'face_detected': False,
            'fps': 0,
            'timestamp': datetime.now().isoformat()
        }
        self.session_start = datetime.now()
        self.total_distractions = 0
        self.mode = "Study"
        self.frame_count = 0
        self.distraction_frames = 0
        
        # Thread locks
        self.metrics_lock = threading.RLock()
        self.current_frame = None
        self.frame_lock = threading.RLock()

state = ApplicationState()

# ================== INITIALIZE MODELS ==================
def initialize_models():
    """Load ML models on startup"""
    print("Loading ML models...")
    
    # MediaPipe Face Mesh
    mp_face_mesh = mp.solutions.face_mesh
    state.face_mesh = mp_face_mesh.FaceMesh(
        max_num_faces=1,
        refine_landmarks=True,
        min_detection_confidence=0.5,
        min_tracking_confidence=0.5
    )
    
    # YOLO Model
    # yolo_path = os.path.join(os.path.dirname(__file__), "yolov8s.pt")
    # state.yolo_model = YOLO(yolo_path)
    
    print("✓ Models loaded successfully")

def initialize_camera():
    """Initialize optimized camera"""
    print("Initializing camera...")
    
    state.camera = WebcamManager(
        fps=30,
        resolution=(640, 480),
        enable_frame_skipping=True,
        skip_frames=2,
        lightweight_mode=False
    )
    
    if state.camera.initialize():
        state.camera.start_capture_thread()
        print("✓ Camera initialized successfully")
        return True
    else:
        print("✗ Failed to initialize camera")
        return False

# ================== DETECTION FUNCTIONS ==================
def eye_aspect_ratio(eye):
    """Calculate eye aspect ratio for blink detection"""
    A = np.linalg.norm(eye[1] - eye[5])
    B = np.linalg.norm(eye[2] - eye[4])
    C = np.linalg.norm(eye[0] - eye[3])
    return (A + B) / (2.0 * C) if C != 0 else 0

def iris_ratio(iris, eye_corners):
    """Calculate iris position ratio for gaze detection"""
    iris_center = np.mean(iris, axis=0)
    eye_width = np.linalg.norm(eye_corners[1] - eye_corners[0])
    if eye_width < 1:
        return 0.5
    return np.linalg.norm(iris_center - eye_corners[0]) / eye_width

def enhance_frame_for_detection(frame):
    """Enhance frame for better detection"""
    lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    
    clahe = cv2.createCLAHE(clipLimit=4.0, tileGridSize=(12, 12))
    l = clahe.apply(l)
    
    enhanced = cv2.merge([l, a, b])
    enhanced = cv2.cvtColor(enhanced, cv2.COLOR_LAB2BGR)
    
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    enhanced = cv2.morphologyEx(enhanced, cv2.MORPH_CLOSE, kernel)
    
    return enhanced

def process_frame(frame):
    """Process frame for focus detection"""
    h, w, _ = frame.shape
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    
    metrics = {
        'focus_score': 50,
        'blink_score': 75,
        'gaze_stability': 75,
        'phone_detected': False,
        'face_detected': False,
        'gaze_x': 0.5,
        'blink_detected': False
    }
    
    # ================== FACE DETECTION ==================
    # try:
    #     results = state.face_mesh.process(rgb)
    #     
    #     if results.multi_face_landmarks:
    #         metrics['face_detected'] = True
    #         face = results.multi_face_landmarks[0]
    #         
    #         LEFT_EYE = [33, 160, 158, 133, 153, 144]
    #         RIGHT_EYE = [362, 385, 387, 263, 373, 380]
    #         LEFT_IRIS = [468, 469, 470, 471]
    #         RIGHT_IRIS = [473, 474, 475, 476]
    #         LEFT_EYE_CORNERS = [33, 133]
    #         RIGHT_EYE_CORNERS = [362, 263]
    #         
    #         # Blink detection
    #         left_eye = np.array([[int(face.landmark[i].x * w), int(face.landmark[i].y * h)] for i in LEFT_EYE])
    #         right_eye = np.array([[int(face.landmark[i].x * w), int(face.landmark[i].y * h)] for i in RIGHT_EYE])
    #         
    #         ear = (eye_aspect_ratio(left_eye) + eye_aspect_ratio(right_eye)) / 2
    #         metrics['blink_score'] = max(0, 100 - int(abs(ear - 0.23) * 200))
    #         
    #         if ear < 0.15:
    #             metrics['blink_detected'] = True
    #         
    #         # Gaze detection
    #         left_iris = np.array([[int(face.landmark[i].x * w), int(face.landmark[i].y * h)] for i in LEFT_IRIS])
    #         right_iris = np.array([[int(face.landmark[i].x * w), int(face.landmark[i].y * h)] for i in RIGHT_IRIS])
    #         
    #         left_eye_corners = np.array([
    #             [int(face.landmark[LEFT_EYE_CORNERS[0]].x * w), int(face.landmark[LEFT_EYE_CORNERS[0]].y * h)],
    #             [int(face.landmark[LEFT_EYE_CORNERS[1]].x * w), int(face.landmark[LEFT_EYE_CORNERS[1]].y * h)]
    #         ])
    #         right_eye_corners = np.array([
    #             [int(face.landmark[RIGHT_EYE_CORNERS[0]].x * w), int(face.landmark[RIGHT_EYE_CORNERS[0]].y * h)],
    #             [int(face.landmark[RIGHT_EYE_CORNERS[1]].x * w), int(face.landmark[RIGHT_EYE_CORNERS[1]].y * h)]
    #         ])
    #         
    #         left_gaze = iris_ratio(left_iris, left_eye_corners)
    #         right_gaze = iris_ratio(right_iris, right_eye_corners)
    #         gaze = (left_gaze + right_gaze) / 2
    #         
    #         metrics['gaze_x'] = gaze
    #         metrics['gaze_stability'] = max(0, 100 - int(abs(gaze - 0.5) * 100))
    #         
    #         # Focus score calculation
    #         focus_score = int(0.6 * metrics['gaze_stability'] + 0.4 * metrics['blink_score'])
    #         metrics['focus_score'] = max(0, min(100, focus_score))
    # except Exception as e:
    #     print(f"Face detection error: {e}")
    
    # ================== OBJECT DETECTION ==================
    # try:
    #     enhanced_frame = enhance_frame_for_detection(frame)
    #     results_yolo = state.yolo_model(enhanced_frame, conf=0.25, iou=0.35, imgsz=640, verbose=False)
    #     
    #     for r in results_yolo:
    #         for box in r.boxes:
    #             cls_id = int(box.cls[0])
    #             label = state.yolo_model.names[cls_id].lower()
    #             
    #             if 'phone' in label or 'cell phone' in label:
    #                 metrics['phone_detected'] = True
    #                 break
    # except Exception as e:
    #     print(f"Object detection error: {e}")
    
    return metrics

def generate_frames():
    """Generate MJPEG frames with real-time processing"""
    frame_times = deque(maxlen=30)
    
    while state.is_running:
        try:
            # Get frame from camera
            frame = state.camera.get_frame_from_queue()
            
            if frame is None:
                time.sleep(0.01)
                continue
            
            frame_start = time.time()
            state.frame_count += 1
            
            # Process frame for metrics
            metrics = process_frame(frame)
            
            # Update state metrics
            with state.metrics_lock:
                state.current_metrics = metrics
                state.current_metrics['fps'] = state.camera.current_fps
                state.current_metrics['timestamp'] = datetime.now().isoformat()
                state.focus_history.append(metrics['focus_score'])
                state.gaze_stability_history.append(metrics['gaze_stability'])
            
            # Add FPS display
            frame = state.camera.add_fps_display(frame)
            
            # Add metrics overlay
            font = cv2.FONT_HERSHEY_SIMPLEX
            font_scale = 0.6
            thickness = 1
            color = (0, 255, 0)
            
            # Focus score
            cv2.putText(frame, f"Focus: {metrics['focus_score']}/100", (10, 60), 
                       font, font_scale, color, thickness)
            # Phone detected
            if metrics['phone_detected']:
                cv2.putText(frame, "PHONE DETECTED", (10, 90), 
                           font, font_scale, (0, 0, 255), thickness)
            # Face detected
            cv2.putText(frame, "Face: YES" if metrics['face_detected'] else "Face: NO", 
                       (10, 120), font, font_scale, color, thickness)
            
            # Store current frame
            with state.frame_lock:
                state.current_frame = frame.copy()
            
            # Encode frame to JPEG
            ret, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
            frame_bytes = buffer.tobytes()
            
            # MJPEG boundary format
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n'
                   b'Content-Length: ' + str(len(frame_bytes)).encode() + b'\r\n\r\n'
                   + frame_bytes + b'\r\n')
            
            # Calculate FPS
            frame_time = time.time() - frame_start
            frame_times.append(frame_time)
            
        except Exception as e:
            print(f"Frame generation error: {e}")
            time.sleep(0.01)

# ================== FLASK ROUTES ==================

@app.route('/')
def index():
    """Main dashboard page"""
    return render_template('index.html')

@app.route('/video_feed')
def video_feed():
    """MJPEG video stream endpoint"""
    return Response(
        generate_frames(),
        mimetype='multipart/x-mixed-replace; boundary=frame',
        headers={'X-Frame-Options': 'SAMEORIGIN'}
    )

@app.route('/api/metrics')
def get_metrics():
    """Get current metrics as JSON"""
    with state.metrics_lock:
        metrics = state.current_metrics.copy()
        metrics['focus_history'] = list(state.focus_history)
        metrics['gaze_stability_history'] = list(state.gaze_stability_history)
        metrics['frame_count'] = state.frame_count
        metrics['session_duration'] = (datetime.now() - state.session_start).total_seconds()
    
    return jsonify(metrics)

@app.route('/api/health')
def get_health():
    """Get camera and system health"""
    if state.camera:
        camera_info = state.camera.get_camera_info()
        health = state.camera.get_performance_health()
        
        return jsonify({
            'camera': camera_info,
            'health': health,
            'running': state.is_running
        })
    
    return jsonify({'running': False})

@app.route('/api/start', methods=['POST'])
def start_session():
    """Start monitoring session"""
    if state.is_running:
        return jsonify({'status': 'already running'})
    
    state.is_running = True
    state.session_start = datetime.now()
    state.frame_count = 0
    state.focus_history.clear()
    state.gaze_stability_history.clear()
    
    return jsonify({'status': 'started'})

@app.route('/api/stop', methods=['POST'])
def stop_session():
    """Stop monitoring session"""
    state.is_running = False
    return jsonify({'status': 'stopped'})

@app.route('/api/set-mode', methods=['POST'])
def set_mode():
    """Set monitoring mode"""
    data = request.json
    mode = data.get('mode', 'Study')
    state.mode = mode
    return jsonify({'mode': state.mode})

# ================== ERROR HANDLERS ==================
@app.errorhandler(404)
def not_found(error):
    return jsonify({'error': 'Not found'}), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({'error': 'Internal server error'}), 500

# ================== STARTUP ==================
def startup():
    """Initialize on startup"""
    print("\n" + "="*60)
    print("ATENZA - Flask-based Real-time Focus Monitor")
    print("="*60)
    
    # initialize_models()
    
    if initialize_camera():
        state.is_running = True
        print("\n✓ Application ready!")
        print("✓ Open http://localhost:5000 in your browser")
        print("✓ Optimized camera: 640x480 @ 30 FPS")
        print("✓ Frame skipping: Enabled (67% overhead reduction)")
        print("✓ Streaming: MJPEG (low latency, no page reloads)")
        print("="*60 + "\n")
    else:
        print("\n✗ Failed to initialize camera")
        print("="*60 + "\n")

if __name__ == '__main__':
    startup()
    
    try:
        print("Starting Flask server...")
        app.run(
            host='0.0.0.0',
            port=5000,
            debug=False,
            threaded=True,
            use_reloader=False
        )
    except KeyboardInterrupt:
        print("\nShutting down...")
        state.is_running = False
        if state.camera:
            state.camera.release()
        print("✓ Cleanup complete")
    except Exception as e:
        print(f"Error: {e}")
        state.is_running = False
        if state.camera:
            state.camera.release()
