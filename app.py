"""
Atenza Live Dashboard - Real-time Focus Monitoring with Camera Integration
"""
import streamlit as st
import cv2
import numpy as np
import mediapipe as mp
from ultralytics import YOLO
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from collections import deque
from datetime import datetime
import os
import time

# Page config
st.set_page_config(
    page_title="Atenza - Live Focus Monitor",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ================== SESSION STATE ==================
if "focus_history" not in st.session_state:
    st.session_state.focus_history = deque(maxlen=100)
    st.session_state.phone_detections = deque(maxlen=50)
    st.session_state.blink_counts = deque(maxlen=30)
    st.session_state.gaze_directions = deque(maxlen=50)
    st.session_state.mode = "Study"
    st.session_state.session_start = datetime.now()
    st.session_state.total_distractions = 0
    st.session_state.frames_processed = 0
    st.session_state.camera_active = False
    st.session_state.cap = None
    st.session_state.current_metrics = None
    st.session_state.current_direction = "Forward"
    st.session_state.ui_placeholders = None

# ================== LOAD MODELS ==================
@st.cache_resource
def load_models():
    mp_face_mesh = mp.solutions.face_mesh
    face_mesh = mp_face_mesh.FaceMesh(
        max_num_faces=1,
        refine_landmarks=True,
        min_detection_confidence=0.5,
        min_tracking_confidence=0.5
    )
    
    yolo_path = os.path.join(os.path.dirname(__file__), "yolov8s.pt")
    yolo_model = YOLO(yolo_path)
    
    return face_mesh, yolo_model

# ================== DETECTION FUNCTIONS ==================
def eye_aspect_ratio(eye):
    A = np.linalg.norm(eye[1] - eye[5])
    B = np.linalg.norm(eye[2] - eye[4])
    C = np.linalg.norm(eye[0] - eye[3])
    return (A + B) / (2.0 * C) if C != 0 else 0

def iris_ratio(iris, eye_corners):
    iris_center = np.mean(iris, axis=0)
    eye_width = np.linalg.norm(eye_corners[1] - eye_corners[0])
    if eye_width < 1:
        return 0.5
    return np.linalg.norm(iris_center - eye_corners[0]) / eye_width

def process_frame(frame, face_mesh, yolo_model, mode_config):
    h, w, _ = frame.shape
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    
    results = face_mesh.process(rgb)
    
    metrics = {
        'focus_score': 50,
        'blink_score': 75,
        'gaze_stability': 75,
        'phone_detected': False,
        'face_detected': False,
        'objects': {},
        'gaze_x': 0.5,
        'blink_detected': False
    }
    
    if results.multi_face_landmarks:
        metrics['face_detected'] = True
        face = results.multi_face_landmarks[0]
        
        LEFT_EYE = [33, 160, 158, 133, 153, 144]
        RIGHT_EYE = [362, 385, 387, 263, 373, 380]
        LEFT_IRIS = [468, 469, 470, 471]
        RIGHT_IRIS = [473, 474, 475, 476]
        LEFT_EYE_CORNERS = [33, 133]
        RIGHT_EYE_CORNERS = [362, 263]
        
        # Blink detection
        left_eye = np.array([[int(face.landmark[i].x * w), int(face.landmark[i].y * h)] for i in LEFT_EYE])
        right_eye = np.array([[int(face.landmark[i].x * w), int(face.landmark[i].y * h)] for i in RIGHT_EYE])
        
        ear = (eye_aspect_ratio(left_eye) + eye_aspect_ratio(right_eye)) / 2
        metrics['blink_score'] = max(0, 100 - int(abs(ear - 0.23) * 200))
        
        # Detect actual blink event (eyes closed)
        if ear < 0.15:
            metrics['blink_detected'] = True
        
        # Gaze detection
        left_iris = np.array([[int(face.landmark[i].x * w), int(face.landmark[i].y * h)] for i in LEFT_IRIS])
        right_iris = np.array([[int(face.landmark[i].x * w), int(face.landmark[i].y * h)] for i in RIGHT_IRIS])
        
        left_eye_corners = np.array([
            [int(face.landmark[LEFT_EYE_CORNERS[0]].x * w), int(face.landmark[LEFT_EYE_CORNERS[0]].y * h)],
            [int(face.landmark[LEFT_EYE_CORNERS[1]].x * w), int(face.landmark[LEFT_EYE_CORNERS[1]].y * h)]
        ])
        right_eye_corners = np.array([
            [int(face.landmark[RIGHT_EYE_CORNERS[0]].x * w), int(face.landmark[RIGHT_EYE_CORNERS[0]].y * h)],
            [int(face.landmark[RIGHT_EYE_CORNERS[1]].x * w), int(face.landmark[RIGHT_EYE_CORNERS[1]].y * h)]
        ])
        
        left_gaze = iris_ratio(left_iris, left_eye_corners)
        right_gaze = iris_ratio(right_iris, right_eye_corners)
        gaze = (left_gaze + right_gaze) / 2
        
        metrics['gaze_x'] = gaze
        metrics['gaze_stability'] = max(0, 100 - int(abs(gaze - 0.5) * 100))
        
        # Downward gaze penalty
        eye_center_y = (left_iris[:, 1].mean() + right_iris[:, 1].mean()) / 2
        face_center_y = h / 2
        downward_penalty = mode_config.get("downward_penalty", 10) if eye_center_y > face_center_y + 20 else 0
        
        focus_score = int(
            mode_config.get("gaze_weight", 0.6) * metrics['gaze_stability'] +
            mode_config.get("blink_weight", 0.4) * metrics['blink_score'] -
            downward_penalty
        )
        metrics['focus_score'] = max(0, min(100, focus_score))
    
    # Object detection with YOLO
    try:
        results_yolo = yolo_model(frame, conf=0.28, iou=0.4, verbose=False)
        for r in results_yolo:
            for box in r.boxes:
                label = yolo_model.names[int(box.cls[0])].lower()
                
                # Check for phone
                if "phone" in label or "cell phone" in label or "mobile" in label:
                    metrics['phone_detected'] = True
                
                # Count all objects
                metrics['objects'][label] = metrics['objects'].get(label, 0) + 1
    except:
        pass
    
    # Phone penalty
    phone_penalty = mode_config.get("phone_penalty", 25) if metrics['phone_detected'] else 0
    metrics['focus_score'] = max(0, min(100, metrics['focus_score'] - phone_penalty))
    
    return metrics

# ================== SIDEBAR ==================
st.sidebar.title("🎯 Atenza Control Panel")

modes = ["Study", "Exam", "Interview", "Relax"]
st.session_state.mode = st.sidebar.selectbox("📊 Mode", modes, index=modes.index(st.session_state.mode))

st.sidebar.markdown("---")

# Camera settings
col_cam1, col_cam2 = st.sidebar.columns(2)
with col_cam1:
    start_camera = st.button("▶️ Start", key="start_cam")
with col_cam2:
    stop_camera = st.button("⏹️ Stop", key="stop_cam")

st.sidebar.markdown("---")

# Statistics
st.sidebar.subheader("📈 Session Stats")
duration = int((datetime.now() - st.session_state.session_start).total_seconds() / 60)
st.sidebar.metric("Duration", f"{duration} min")
st.sidebar.metric("Distractions", st.session_state.total_distractions)
if st.session_state.focus_history:
    st.sidebar.metric("Avg Focus", f"{int(np.mean(list(st.session_state.focus_history)))}%")

# ================== MAIN UI ==================
st.title("🎯 Atenza - Live Focus Monitor")

mode_config = {
    "Study": {"gaze_weight": 0.6, "blink_weight": 0.4, "downward_penalty": 10, "phone_penalty": 25},
    "Exam": {"gaze_weight": 0.7, "blink_weight": 0.3, "downward_penalty": 15, "phone_penalty": 30},
    "Interview": {"gaze_weight": 0.8, "blink_weight": 0.2, "downward_penalty": 20, "phone_penalty": 35},
    "Relax": {"gaze_weight": 0.4, "blink_weight": 0.6, "downward_penalty": 5, "phone_penalty": 10}
}

# Camera and detection
face_mesh, yolo_model = load_models()

# Handle camera start/stop
if start_camera and not st.session_state.camera_active:
    st.session_state.cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
    if st.session_state.cap.isOpened():
        st.session_state.camera_active = True
    else:
        st.session_state.cap = None
        st.error("❌ Failed to open camera. Please check camera permissions and connections.")

if stop_camera and st.session_state.camera_active:
    if st.session_state.cap:
        st.session_state.cap.release()
    st.session_state.camera_active = False
    st.session_state.cap = None
    st.rerun()

# Create UI placeholders only once
if st.session_state.ui_placeholders is None and st.session_state.camera_active:
    st.info("📷 Camera Active - Real-time Detection Running")
    
    col_video, col_stats = st.columns([2, 1])
    
    with col_video:
        camera_placeholder = st.empty()
    
    with col_stats:
        focus_metric = st.empty()
        blink_metric = st.empty()
        gaze_metric = st.empty()
        phone_alert = st.empty()
    
    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "📊 Focus Score", "📱 Phone", "👁️ Gaze", "👀 Blinks", "🔍 Objects"
    ])
    
    st.session_state.ui_placeholders = {
        'camera': camera_placeholder,
        'focus': focus_metric,
        'blink': blink_metric,
        'gaze': gaze_metric,
        'phone': phone_alert,
        'tab1': tab1,
        'tab2': tab2,
        'tab3': tab3,
        'tab4': tab4,
        'tab5': tab5,
    }

# Update UI if camera is active
if st.session_state.camera_active:
    cap = st.session_state.cap
    
    if cap and cap.isOpened():
        ret, frame = cap.read()
        if ret:
            frame = cv2.flip(frame, 1)
            h, w = frame.shape[:2]
            
            # Process frame
            metrics = process_frame(frame, face_mesh, yolo_model, mode_config[st.session_state.mode])
            
        # Update history
            st.session_state.focus_history.append(metrics['focus_score'])
            st.session_state.frames_processed += 1
            
            if metrics['phone_detected']:
                st.session_state.total_distractions += 1
            
            # Track blinks - increment when blink is detected
            if metrics['blink_detected']:
                st.session_state.blink_counts.append(1)
            
            # Gaze tracking
            if metrics['gaze_x'] < 0.33:
                direction = "Left"
                st.session_state.gaze_directions.append('Left')
            elif metrics['gaze_x'] > 0.67:
                direction = "Right"
                st.session_state.gaze_directions.append('Right')
            else:
                direction = "Forward"
                st.session_state.gaze_directions.append('Forward')
            
            st.session_state.current_direction = direction
            st.session_state.current_metrics = metrics
            
            # Update camera display
            if st.session_state.ui_placeholders:
                try:
                    _, buffer = cv2.imencode('.jpg', frame)
                    st.session_state.ui_placeholders['camera'].image(buffer.tobytes(), channels="BGR", width='stretch')
                except:
                    pass
                
                # Update metrics
                st.session_state.ui_placeholders['focus'].metric("Focus Score", f"{metrics['focus_score']}%")
                st.session_state.ui_placeholders['blink'].metric("Blink Score", f"{metrics['blink_score']}%")
                st.session_state.ui_placeholders['gaze'].metric("Gaze", f"{metrics['gaze_stability']}% {direction}")
                
                if metrics['phone_detected']:
                    st.session_state.ui_placeholders['phone'].error("🚨 PHONE DETECTED")
                else:
                    st.session_state.ui_placeholders['phone'].success("✅ Phone Clear")
                
                # Update tabs
                with st.session_state.ui_placeholders['tab1']:
                    st.write(f"**Current Focus: {metrics['focus_score']}%**")
                    if st.session_state.focus_history:
                        fig = go.Figure(go.Scatter(y=list(st.session_state.focus_history), mode='lines', name='Focus Score'))
                        fig.update_layout(height=300, margin=dict(l=0, r=0, t=20, b=0), xaxis_title="Frames", yaxis_title="Focus %")
                        st.plotly_chart(fig, width='stretch', key=f"focus_chart_{time.time()}")
                
                with st.session_state.ui_placeholders['tab2']:
                    st.write(f"**Phone Detected:** {'Yes ⚠️' if metrics['phone_detected'] else 'No ✓'}")
                    st.write(f"**Total Distractions:** {st.session_state.total_distractions}")
                    st.write(f"**Frames Processed:** {st.session_state.frames_processed}")
                
                with st.session_state.ui_placeholders['tab3']:
                    st.write(f"**Gaze Stability:** {metrics['gaze_stability']}%")
                    st.write(f"**Direction:** {direction}")
                    if st.session_state.gaze_directions and len(st.session_state.gaze_directions) > 0:
                        gaze_counts = pd.Series(list(st.session_state.gaze_directions)).value_counts()
                        fig = px.pie(values=gaze_counts.values, names=gaze_counts.index, title="Gaze Distribution")
                        fig.update_layout(height=300)
                        st.plotly_chart(fig, width='stretch', key=f"gaze_chart_{time.time()}")
                
                with st.session_state.ui_placeholders['tab4']:
                    st.write(f"**Total Blinks Detected:** {len(st.session_state.blink_counts)}")
                    st.write(f"**Eye Strain:** {'Low 😊' if metrics['blink_score'] > 70 else 'High 😵'}")
                    st.write(f"**Current Blink Score:** {metrics['blink_score']}%")
                
                with st.session_state.ui_placeholders['tab5']:
                    if metrics['objects']:
                        df = pd.DataFrame({'Object': list(metrics['objects'].keys()), 'Count': list(metrics['objects'].values())})
                        fig = px.bar(df, x='Object', y='Count', title="Detected Objects")
                        fig.update_layout(height=300)
                        st.plotly_chart(fig, width='stretch', key=f"objects_chart_{time.time()}")
                    else:
                        st.info("No additional objects detected")
            
            # Smooth rerun
            time.sleep(0.05)
            st.rerun()
        else:
            st.error("❌ Cannot read frame from camera")
            st.session_state.camera_active = False
            st.session_state.ui_placeholders = None
    else:
        st.error("❌ Cannot access camera")
        st.session_state.camera_active = False
        st.session_state.ui_placeholders = None
else:
    st.session_state.ui_placeholders = None
    if stop_camera:
        st.info("Camera stopped")
    else:
        st.info("Click 'Start' button to begin monitoring")

st.markdown("---")
st.markdown("<p style='text-align: center; color: #7f8c8d;'>🎯 Atenza Focus Monitor | Status: Ready</p>", unsafe_allow_html=True)
