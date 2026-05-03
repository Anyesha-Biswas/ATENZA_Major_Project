# Atenza - Streamlit to Alternative Implementation TODO

## Task
Replace Streamlit-based real-time webcam app with an alternative approach for smooth video streaming without lag, delayed frames, or slow response times.

## Plan

### Step 1: Create Flask templates
- [ ] Create `atenza/templates/` directory
- [ ] Create `atenza/templates/index.html` - main dashboard with video feed, metrics, and controls

### Step 2: Enhance Flask app with complete detection features
- [ ] Add mode configuration (Study, Exam, Interview, Relax)
- [ ] Add distraction tracking and alert system
- [ ] Add session statistics
- [ ] Add shutdown logic (25 distraction threshold)
- [ ] Integrate all detection features from `app.py`

### Step 3: Create standalone OpenCV option
- [ ] Create `atenza/app_opencv.py` - standalone OpenCV app with cv2.imshow
- [ ] Use optimized WebcamManager
- [ ] Add on-screen display for metrics
- [ ] Add keyboard controls

### Step 4: Test and verify
- [ ] Test Flask app for latency and frame smoothness
- [ ] Test OpenCV standalone app
- [ ] Verify all detection features work correctly

## Implementation Notes

### Flask Architecture
- Video streaming: MJPEG via `/video_feed` endpoint
- Metrics: JSON via `/api/metrics` endpoint
- Controls: REST API for start/stop/mode

### OpenCV Standalone Architecture
- Direct camera capture using WebcamManager
- cv2.imshow for video display
- On-screen metrics overlay
- Keyboard controls (ESC to quit)

### Required Files to Create/Edit
1. `atenza/templates/index.html` (NEW)
2. `atenza/app_flask.py` (ENHANCE) 
3. `atenza/app_opencv.py` (NEW)
