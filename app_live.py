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
import time
import os
import json

# Page config
st.set_page_config(
    page_title="Atenza - Live Focus Monitor",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ================== SESSION HISTORY ==================
history_file = os.path.join(os.path.dirname(__file__), "session_history.json")

def load_session_history():
    try:
        if os.path.exists(history_file):
            with open(history_file, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        return []
    return []


def save_session_history(history):
    try:
        with open(history_file, "w", encoding="utf-8") as f:
            json.dump(history, f, indent=2)
    except Exception:
        pass


def record_session_history():
    if not st.session_state.focus_history:
        return
    end_time = datetime.now()
    summary = {
        "start": st.session_state.session_start.isoformat(),
        "end": end_time.isoformat(),
        "duration_minutes": int((end_time - st.session_state.session_start).total_seconds() / 60),
        "mode": st.session_state.mode,
        "avg_focus": int(np.mean(list(st.session_state.focus_history))) if st.session_state.focus_history else 0,
        "max_focus": int(max(st.session_state.focus_history)) if st.session_state.focus_history else 0,
        "min_focus": int(min(st.session_state.focus_history)) if st.session_state.focus_history else 0,
        "distractions": st.session_state.total_distractions,
        "frames_processed": st.session_state.frames_processed,
    }
    history = st.session_state.session_history
    if history and history[-1].get("start") == summary["start"]:
        return
    history.append(summary)
    save_session_history(history)


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
    st.session_state.session_history = load_session_history()
    st.session_state.last_alert_type = None

if "session_history" not in st.session_state:
    st.session_state.session_history = load_session_history()

if "last_alert_type" not in st.session_state:
    st.session_state.last_alert_type = None

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
        'gaze_x': 0.5
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
    
    # Phone detection
    try:
        results_yolo = yolo_model(frame, conf=0.28, iou=0.4, verbose=False)
        for r in results_yolo:
            for box in r.boxes:
                label = yolo_model.names[int(box.cls[0])].lower()
                if "phone" in label:
                    metrics['phone_detected'] = True
                    break
                
                # Object categorization
                if 'phone' in label:
                    metrics['objects']['phone'] = metrics['objects'].get('phone', 0) + 1
                elif 'laptop' in label:
                    metrics['objects']['laptop'] = metrics['objects'].get('laptop', 0) + 1
                elif 'person' in label:
                    metrics['objects']['person'] = metrics['objects'].get('person', 0) + 1
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
sidebar_duration = st.sidebar.empty()
sidebar_distractions = st.sidebar.empty()
sidebar_avg_focus = st.sidebar.empty()

# History
with st.sidebar.expander("📜 Session History", expanded=False):
    if st.session_state.session_history:
        history_items = st.session_state.session_history[::-1]
        history_labels = [
            f"{item['start'][:19]} | {item['mode']} | {item['duration_minutes']}m | {item['distractions']} distractions"
            for item in history_items
        ]
        selected_idx = st.selectbox("Select session", list(range(len(history_labels))), format_func=lambda i: history_labels[i], key="history_selected")
        selected = history_items[selected_idx]
        st.markdown(f"**Mode:** {selected['mode']}  ")
        st.markdown(f"**Start:** {selected['start'][:19]}  ")
        st.markdown(f"**End:** {selected['end'][:19]}  ")
        st.markdown(f"**Duration:** {selected['duration_minutes']} minutes  ")
        st.markdown(f"**Avg Focus:** {selected['avg_focus']}%  ")
        st.markdown(f"**Min Focus:** {selected['min_focus']}%  ")
        st.markdown(f"**Max Focus:** {selected['max_focus']}%  ")
        st.markdown(f"**Distractions:** {selected['distractions']}  ")
    else:
        st.write("No previous sessions recorded yet.")

def update_sidebar_stats():
    duration = int((datetime.now() - st.session_state.session_start).total_seconds() / 60)
    sidebar_duration.metric("Duration", f"{duration} min")
    sidebar_distractions.metric("Distractions", st.session_state.total_distractions)
    if st.session_state.focus_history:
        sidebar_avg_focus.metric("Avg Focus", f"{int(np.mean(list(st.session_state.focus_history)))}%")
    else:
        sidebar_avg_focus.metric("Avg Focus", "N/A")

update_sidebar_stats()

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
    record_session_history()
    if st.session_state.cap:
        st.session_state.cap.release()
    st.session_state.camera_active = False
    st.session_state.cap = None

if st.session_state.camera_active:
    cap = st.session_state.cap
    
    if cap and cap.isOpened():
        st.info("📷 Camera Active - Real-time Detection Running")
        
        col_video, col_stats = st.columns([2, 1])
        
        with col_video:
            alert_placeholder = st.empty()
            camera_placeholder = st.empty()
            suggestion_placeholder = st.empty()
        
        with col_stats:
            focus_metric = st.empty()
            blink_metric = st.empty()
            gaze_metric = st.empty()
            phone_alert = st.empty()
        
        # Tabs for detailed views
        tab1, tab2, tab3, tab4, tab5 = st.tabs([
            "📊 Focus Score", "📱 Phone", "👁️ Gaze", "👀 Blinks", "🔍 Objects"
        ])
        
        frame_count = 0
        last_blink = 0
        
        # Continuous frame processing loop
        while st.session_state.camera_active and cap.isOpened():
            ret, frame = cap.read()
            if not ret or frame is None:
                st.error("❌ Cannot read frame from camera")
                break

            frame = cv2.flip(frame, 1)
            h, w = frame.shape[:2]
            
            # Process frame
            metrics = process_frame(frame, face_mesh, yolo_model, mode_config[st.session_state.mode])
            
            # Update history
            st.session_state.focus_history.append(metrics['focus_score'])
            st.session_state.frames_processed += 1
            
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
            
            # Blink tracking
            if metrics['blink_score'] < 50:
                last_blink += 1
            else:
                if last_blink > 2:
                    st.session_state.blink_counts.append(1)
                last_blink = 0
            
            frame_count += 1
            
            # Update statistics immediately
            update_sidebar_stats()

            # Distraction alert system
            alert_text = None
            alert_type = None
            suggestion_text = None

            if metrics['phone_detected']:
                alert_type = "phone"
                alert_text = "🚨 PHONE DETECTED: Please remove any phone from view."
            elif metrics['focus_score'] < 60:
                alert_type = "focus_low"
                alert_text = "🚨 FOCUS ALERT: Your focus score is below 60%."
            elif direction != "Forward":
                alert_type = "gaze"
                alert_text = f"🚨 DISTRACTION: Your gaze is {direction.lower()}."

            if metrics['focus_score'] < 80:
                if metrics['focus_score'] < 60:
                    suggestion_text = (
                        "Try these focus tips:<br>"
                        "• Take a deep breath and reset your posture.<br>"
                        "• Remove nearby distractions and put your phone away.<br>"
                        "• Focus on one task for the next 5 minutes.<br>"
                        "• Close unused apps and silence notifications."
                    )
                else:
                    suggestion_text = (
                        "Focus improvement suggestions:<br>"
                        "• Blink regularly and keep your eyes relaxed.<br>"
                        "• Re-center on your current task goal.<br>"
                        "• Minimize open tabs or phone notifications.<br>"
                        "• Try a short 5-minute Pomodoro stretch."
                    )

            if alert_type and alert_type != st.session_state.last_alert_type:
                st.session_state.total_distractions += 1
            if alert_type is None:
                st.session_state.last_alert_type = None
            else:
                st.session_state.last_alert_type = alert_type

            if st.session_state.total_distractions > 25:
                record_session_history()
                if st.session_state.cap:
                    st.session_state.cap.release()
                st.session_state.camera_active = False
                alert_placeholder.markdown(
                    "<div style='background:#b71c1c;color:white;padding:20px;border-radius:10px;'>"
                    "<h2>🚨 MAX DISTRACTIONS REACHED</h2>"
                    "<p>The session has been closed automatically after too many distractions.</p>"
                    "</div>",
                    unsafe_allow_html=True
                )
                suggestion_placeholder.empty()
                camera_placeholder.empty()
                st.stop()

            if alert_text:
                alert_placeholder.markdown(
                    f"<div style='background:#c62828;color:white;padding:16px;border-radius:10px;'>"
                    f"<strong>{alert_text}</strong>"
                    f"</div>",
                    unsafe_allow_html=True
                )
            else:
                alert_placeholder.markdown(
                    "<div style='background:#2e7d32;color:white;padding:16px;border-radius:10px;'>"
                    "<strong>✅ No distraction detected — stay focused.</strong>"
                    "</div>",
                    unsafe_allow_html=True
                )

            if suggestion_text:
                suggestion_placeholder.markdown(
                    f"<div style='background:#f9fbe7;color:#333;padding:14px;border-radius:10px;'>"
                    f"<strong>Suggestions:</strong><br>{suggestion_text}"
                    f"</div>",
                    unsafe_allow_html=True
                )
            else:
                suggestion_placeholder.empty()

            # Update camera display
            camera_placeholder.image(frame, channels="BGR", width='stretch')
            
            # Update metrics
            with col_stats:
                with focus_metric.container():
                    color = "green" if metrics['focus_score'] >= 70 else "orange" if metrics['focus_score'] >= 50 else "red"
                    st.metric("Focus Score", f"{metrics['focus_score']}%", delta="+5%")
                
                with blink_metric.container():
                    st.metric("Blink Score", f"{metrics['blink_score']}%")
                
                with gaze_metric.container():
                    st.metric("Gaze", f"{metrics['gaze_stability']}% {direction}")
                
                with phone_alert.container():
                    if metrics['phone_detected']:
                        st.error("🚨 PHONE DETECTED")
                    else:
                        st.success("✅ Phone Clear")
            
            with tab1:
                st.write(f"**Current Focus: {metrics['focus_score']}%**")
                if st.session_state.focus_history:
                    fig = go.Figure(go.Scatter(y=list(st.session_state.focus_history), mode='lines'))
                    fig.update_layout(height=300, margin=dict(l=0, r=0, t=0, b=0))
                    st.plotly_chart(fig, width='stretch', key=f"focus_chart_{time.time()}")
            
            with tab2:
                st.write(f"**Phone Detected:** {'Yes' if metrics['phone_detected'] else 'No'}")
                st.write(f"**Total Distractions:** {st.session_state.total_distractions}")
            
            with tab3:
                st.write(f"**Gaze Stability:** {metrics['gaze_stability']}%")
                st.write(f"**Direction:** {direction}")
                if st.session_state.gaze_directions:
                    gaze_counts = pd.Series(list(st.session_state.gaze_directions)).value_counts()
                    fig = px.pie(values=gaze_counts.values, names=gaze_counts.index)
                    fig.update_layout(height=300)
                    st.plotly_chart(fig, width='stretch', key=f"gaze_chart_{time.time()}")
            
            with tab4:
                st.write(f"**Total Blinks:** {len(st.session_state.blink_counts)}")
                st.write(f"**Eye Strain:** {'Low' if metrics['blink_score'] > 70 else 'High'}")
            
            with tab5:
                if metrics['objects']:
                    df = pd.DataFrame({'Object': list(metrics['objects'].keys()), 'Count': list(metrics['objects'].values())})
                    fig = px.bar(df, x='Object', y='Count')
                    fig.update_layout(height=300)
                    st.plotly_chart(fig, width='stretch', key=f"objects_chart_{time.time()}")
                else:
                    st.write("No objects detected")
            
            # Add a small delay to prevent excessive CPU usage
            time.sleep(0.1)
    else:
        st.error("❌ Cannot access camera")
else:
    if stop_camera:
        st.info("Camera stopped")
    else:
        st.info("Click 'Start' button to begin monitoring")

st.markdown("---")
st.markdown("<p style='text-align: center; color: #7f8c8d;'>🎯 Atenza Focus Monitor | Status: Ready</p>", unsafe_allow_html=True)
