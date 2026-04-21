import cv2
import numpy as np
import base64
import mediapipe as mp
from mediapipe.tasks import python as mp_tasks
from mediapipe.tasks.python import vision
from enum import IntEnum
import math
from ultralytics import YOLO

import os
import time
import json
import threading
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional
from .redis_service import RedisService


class PoseLandmark(IntEnum):
    # Local enum avoids relying on mediapipe.solutions, which is absent in some builds.
    NOSE = 0
    LEFT_EYE = 2
    RIGHT_EYE = 5
    LEFT_SHOULDER = 11
    RIGHT_SHOULDER = 12
    LEFT_ELBOW = 13
    RIGHT_ELBOW = 14
    LEFT_WRIST = 15
    RIGHT_WRIST = 16
    LEFT_HIP = 23
    RIGHT_HIP = 24
    LEFT_KNEE = 25
    RIGHT_KNEE = 26

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("detection_service")

# Model paths
_MODELS_DIR = os.path.join(os.path.dirname(__file__), "models")
_POSE_MODEL_PATH = os.path.join(_MODELS_DIR, "pose_landmarker_lite.task")
_FACE_MODEL_PATH = os.path.join(_MODELS_DIR, "face_landmarker.task")

# Initialize MediaPipe Pose Landmarker (Tasks API)
_pose_base_options = mp_tasks.BaseOptions(model_asset_path=_POSE_MODEL_PATH)
_pose_options = vision.PoseLandmarkerOptions(
    base_options=_pose_base_options,
    running_mode=vision.RunningMode.IMAGE,
    min_pose_detection_confidence=0.5,
    min_pose_presence_confidence=0.5,
    min_tracking_confidence=0.5,
)
pose_landmarker = vision.PoseLandmarker.create_from_options(_pose_options)

# Initialize MediaPipe Face Landmarker (Tasks API)
_face_base_options = mp_tasks.BaseOptions(model_asset_path=_FACE_MODEL_PATH)
_face_options = vision.FaceLandmarkerOptions(
    base_options=_face_base_options,
    running_mode=vision.RunningMode.IMAGE,
    num_faces=1,
    min_face_detection_confidence=0.5,
    min_face_presence_confidence=0.5,
    min_tracking_confidence=0.5,
    output_face_blendshapes=False,
    output_facial_transformation_matrixes=False,
)
face_landmarker = vision.FaceLandmarker.create_from_options(_face_options)

# Initialize FER for emotion detection
try:
    from fer.fer import FER
    emotion_detector = FER(mtcnn=True)
    logger.info("FER initialized successfully")
except Exception as e:
    logger.error(f"Error initializing FER: {str(e)}")
    emotion_detector = None

# YOLOv8 model for cheating detection
try:
    yolo_model = YOLO("yolov8l.pt")
    logger.info("YOLO model initialized successfully")
except Exception as e:
    logger.error(f"Error initializing YOLO model: {str(e)}")
    yolo_model = None

# Eye landmark indices (FaceMesh / FaceLandmarker compatible)
LEFT_EYE = [362, 382, 381, 380, 374, 373, 390, 249, 263, 466, 388, 387, 386, 385, 384, 398]
RIGHT_EYE = [33, 7, 163, 144, 145, 153, 154, 155, 133, 173, 157, 158, 159, 160, 161, 246]
LEFT_IRIS = [474, 475, 476, 477]
RIGHT_IRIS = [469, 470, 471, 472]


def _detect_with_pose(frame_rgb: np.ndarray):
    """Run pose landmarker and return result."""
    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=frame_rgb)
    return pose_landmarker.detect(mp_image)


def _detect_with_face(frame_rgb: np.ndarray):
    """Run face landmarker and return result."""
    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=frame_rgb)
    return face_landmarker.detect(mp_image)


class DetectionService:
    def __init__(self):
        self.redis_service = RedisService()
        self.lock = threading.Lock()
        self.yolo_model_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
            "yolov8l.pt",
        )
        logger.info("Detection service initialized")

    def start_detection_session(self, interview_id: str) -> Dict[str, Any]:
        """Start a new detection session"""
        with self.lock:
            existing_session = self.redis_service.get_session(interview_id)
            if existing_session:
                logger.info(f"Retrieved existing session: {interview_id}")
                return existing_session

            logger.info(f"Starting new detection session: {interview_id}")
            session = {
                "id": interview_id,
                "active": True,
                "start_time": time.time(),
                "last_updated": time.time(),
                "frames_processed": 0,
                "current_state": {
                    "pose": "Unknown",
                    "pose_confidence": 0.5,
                    "emotion": "neutral",
                    "emotion_confidence": 0.5,
                    "eye_direction": "Unknown",
                    "eye_confidence": 0.5,
                    "people_count": 1,
                    "direction_looking": "at-system",
                    "communication_device_present": False,
                },
                "history": [],
            }

            try:
                self.redis_service.set_session(interview_id, session)
                logger.info(f"Created new detection session for interview {interview_id}")
            except Exception as e:
                logger.error(f"Error creating detection session: {str(e)}")
                raise

            return session

    def stop_detection_session(self, interview_id: str) -> Dict[str, Any]:
        """Stop an active detection session"""
        with self.lock:
            session = self.redis_service.get_session(interview_id)
            if not session:
                logger.warning(f"Attempted to stop non-existent session: {interview_id}")
                return {"success": False, "error": "Session not found"}

            logger.info(f"Stopping detection session: {interview_id}")
            session["active"] = False
            session["end_time"] = time.time()

            try:
                self.redis_service.delete_session(interview_id)
                logger.info(f"Stopped detection session for interview {interview_id}")
                return {"success": True, "session": session}
            except Exception as e:
                logger.error(f"Error stopping detection session: {str(e)}")
                raise

    def get_detection_session(self, interview_id: str) -> Optional[Dict[str, Any]]:
        """Get a detection session by ID"""
        with self.lock:
            if interview_id not in self.redis_service.get_all_sessions():
                return None
            return self.redis_service.get_session(interview_id)

    def process_frame(self, interview_id: str, frame_base64: str) -> Dict[str, Any]:
        """Process a video frame for detection"""
        logger.info(f"Processing frame for session: {interview_id}")

        session = self.get_detection_session(interview_id)
        if not session:
            logger.info(f"Creating new session for {interview_id}")
            session = self.start_detection_session(interview_id)

        try:
            if not frame_base64:
                logger.error("Received empty frame data")
                raise ValueError("Empty frame data received")

            try:
                if "," in frame_base64:
                    frame_base64 = frame_base64.split(",")[1]

                img_data = base64.b64decode(frame_base64)
                nparr = np.frombuffer(img_data, np.uint8)
                frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

                if frame is None or frame.size == 0:
                    logger.error("Decoded frame is empty or invalid")
                    raise ValueError("Invalid frame data")

                logger.info(f"Frame decoded successfully, shape: {frame.shape}")

                frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

                # Pose detection
                logger.info("Processing with MediaPipe Pose Landmarker...")
                pose_result = _detect_with_pose(frame_rgb)

                if pose_result.pose_landmarks:
                    logger.info("Pose landmarks detected")
                    pose_type, pose_confidence = self._detect_pose(pose_result.pose_landmarks[0])
                else:
                    logger.warning("No pose landmarks detected")
                    return {
                        "success": True,
                        "detection_results": {
                            "pose": "No Person Detected",
                            "pose_confidence": 0.0,
                            "emotion": "Unknown",
                            "emotion_confidence": 0.0,
                            "eye_direction": "Unknown",
                            "eye_confidence": 0.0,
                            "people_count": 0,
                            "direction_looking": "unknown",
                            "communication_device_present": False,
                        },
                        "frames_processed": session["frames_processed"],
                    }

                # Eye tracking
                logger.info("Processing with MediaPipe Face Landmarker...")
                face_result = _detect_with_face(frame_rgb)

                if face_result.face_landmarks:
                    logger.info("Face landmarks detected")
                    eye_direction, eye_confidence = self._detect_eye_direction(
                        face_result.face_landmarks[0]
                    )
                else:
                    logger.warning("No face landmarks detected")
                    eye_direction = "Unknown"
                    eye_confidence = 0.0

                # Emotion detection
                emotion = "Unknown"
                emotion_confidence = 0.0
                emotion_breakdown = {
                    "neutral": 0.6,
                    "happy": 0.2,
                    "sad": 0.1,
                    "angry": 0.05,
                    "surprise": 0.05,
                }

                if emotion_detector:
                    try:
                        logger.info("Processing emotions with FER...")
                        emotions = emotion_detector.detect_emotions(frame)
                        if emotions and len(emotions) > 0:
                            emotion_breakdown = emotions[0]["emotions"]
                            dominant_emotion = max(emotion_breakdown.items(), key=lambda x: x[1])
                            emotion = dominant_emotion[0]
                            emotion_confidence = float(dominant_emotion[1])
                            logger.info(f"Emotion detected: {emotion} with confidence {emotion_confidence}")
                    except Exception as e:
                        logger.error(f"Error in emotion detection: {str(e)}")

                # Cheating detection
                logger.info("Processing cheating detection with YOLO...")
                cheating_results = self._detect_cheating(frame)

                detection_results = {
                    "pose": pose_type,
                    "pose_confidence": float(pose_confidence),
                    "emotion": emotion,
                    "emotion_confidence": emotion_confidence,
                    "eye_direction": eye_direction,
                    "eye_confidence": float(eye_confidence),
                    "people_count": cheating_results["people_count"],
                    "direction_looking": "at-system" if eye_direction == "Center (Neutral)" else "away",
                    "communication_device_present": cheating_results["communication_device_present"],
                    "emotion_breakdown": emotion_breakdown,
                }

                logger.info(f"Detection results: {detection_results}")

                with self.lock:
                    session["current_state"] = detection_results
                    session["frames_processed"] += 1
                    session["last_updated"] = time.time()

                    self.redis_service.append_to_history(
                        interview_id,
                        {"frame_number": session["frames_processed"], "state": detection_results},
                    )
                    if len(self.redis_service.get_history(interview_id)) > 10:
                        self.redis_service.trim_history(interview_id, 10)

                self.redis_service.set_session(interview_id, session)

                # Record proctoring violations to the interview JSON
                self._record_proctoring_violations(interview_id, detection_results)

                return {
                    "success": True,
                    "detection_results": detection_results,
                    "frames_processed": session["frames_processed"],
                }

            except Exception as e:
                logger.error(f"Error processing frame: {str(e)}")
                raise

        except Exception as e:
            logger.error(f"Unexpected error in process_frame: {str(e)}")
            logger.exception("Full exception trace:")
            return {
                "success": False,
                "error": str(e),
                "frames_processed": session.get("frames_processed", 0),
            }

    def _record_proctoring_violations(self, interview_id: str, detection_results: Dict[str, Any]):
        """Record proctoring violations (multiple people, device, looking away) to the interview JSON."""
        violations = []
        now = datetime.now(timezone.utc).isoformat()

        # Read interview data to get current question index
        interview_path = f"interview_data/{interview_id}.json"
        if not os.path.exists(interview_path):
            return

        try:
            with open(interview_path, 'r') as f:
                interview_data = json.load(f)
        except Exception as e:
            logger.error(f"Failed to read interview data for proctoring: {e}")
            return

        question_index = interview_data.get("current_question_index", 0)

        if detection_results.get("people_count", 1) > 1:
            violations.append({
                "type": "multiple_people",
                "timestamp": now,
                "question_index": question_index,
                "severity": "critical",
                "details": f"{detection_results['people_count']} people detected in frame",
            })

        if detection_results.get("communication_device_present", False):
            violations.append({
                "type": "communication_device",
                "timestamp": now,
                "question_index": question_index,
                "severity": "critical",
                "details": "Communication device detected in frame",
            })

        eye_direction = detection_results.get("eye_direction", "Unknown")
        if eye_direction not in ("Center (Neutral)", "Unknown") and detection_results.get("direction_looking") != "at-system":
            violations.append({
                "type": "looking_away",
                "timestamp": now,
                "question_index": question_index,
                "severity": "warning",
                "details": f"Candidate looking away: {eye_direction}",
            })

        if not violations:
            return

        try:
            if "proctoring_violations" not in interview_data:
                interview_data["proctoring_violations"] = []

            interview_data["proctoring_violations"].extend(violations)

            with open(interview_path, 'w') as f:
                json.dump(interview_data, f, indent=2)

            logger.info(f"Recorded {len(violations)} proctoring violation(s) for interview {interview_id}")
        except Exception as e:
            logger.error(f"Failed to save proctoring violations: {e}")

    def _process_all_detections(self, frame: np.ndarray) -> Dict[str, Any]:
        """Process a frame with all detection systems"""
        results = {
            "pose": "Unknown Pose",
            "pose_confidence": 0.0,
            "emotion": "Unknown",
            "emotion_confidence": 0.0,
            "eye_direction": "Unknown",
            "eye_confidence": 0.0,
            "people_count": 0,
            "direction_looking": "unknown",
            "communication_device_present": False,
        }

        try:
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

            try:
                pose_result = _detect_with_pose(rgb_frame)
                if pose_result.pose_landmarks:
                    pose_type, pose_confidence = self._detect_pose(pose_result.pose_landmarks[0])
                    results["pose"] = pose_type
                    results["pose_confidence"] = float(pose_confidence)
                    logger.info(f"Pose detected: {pose_type} with confidence {pose_confidence}")
                else:
                    logger.info("No pose landmarks detected")
            except Exception as e:
                logger.error(f"Error in pose detection: {str(e)}")
                results["pose"] = "Error in detection"

            try:
                face_result = _detect_with_face(rgb_frame)
                if face_result.face_landmarks:
                    eye_direction, eye_confidence = self._detect_eye_direction(
                        face_result.face_landmarks[0]
                    )
                    results["eye_direction"] = eye_direction
                    results["eye_confidence"] = float(eye_confidence)
                    logger.info(f"Eye direction detected: {eye_direction} with confidence {eye_confidence}")
                else:
                    logger.info("No face landmarks detected")
            except Exception as e:
                logger.error(f"Error in eye tracking: {str(e)}")
                results["eye_direction"] = "Error in detection"

            try:
                if emotion_detector:
                    emotions = emotion_detector.detect_emotions(frame)
                    if emotions and len(emotions) > 0:
                        dominant_emotion = max(emotions[0]["emotions"].items(), key=lambda x: x[1])
                        results["emotion"] = dominant_emotion[0]
                        results["emotion_confidence"] = float(dominant_emotion[1])
                    else:
                        logger.info("No emotions detected")
                else:
                    logger.warning("Emotion detector not available")
            except Exception as e:
                logger.error(f"Error in emotion detection: {str(e)}")
                results["emotion"] = "Error in detection"

            try:
                cheating_results = self._detect_cheating(frame)
                results.update(cheating_results)
            except Exception as e:
                logger.error(f"Error in cheating detection: {str(e)}")
                results["people_count"] = 1

            # Adjust people count if face was detected
            if results["people_count"] == 0 and face_result.face_landmarks:
                results["people_count"] = 1
                logger.info("Adjusted people count to 1 based on face detection")

        except Exception as e:
            logger.error(f"Error in _process_all_detections: {str(e)}")
            results["pose"] = "Error in detection"
            results["emotion"] = "Error in detection"
            results["eye_direction"] = "Error in detection"
            results["people_count"] = 1

        return results

    def _detect_pose(self, landmarks):
        """Detect pose from a list of NormalizedLandmark objects."""
        confidence_score = np.mean([lm.visibility for lm in landmarks])

        left_wrist    = landmarks[PoseLandmark.LEFT_WRIST]
        right_wrist   = landmarks[PoseLandmark.RIGHT_WRIST]
        left_elbow    = landmarks[PoseLandmark.LEFT_ELBOW]
        right_elbow   = landmarks[PoseLandmark.RIGHT_ELBOW]
        left_shoulder = landmarks[PoseLandmark.LEFT_SHOULDER]
        right_shoulder= landmarks[PoseLandmark.RIGHT_SHOULDER]
        left_hip      = landmarks[PoseLandmark.LEFT_HIP]
        right_hip     = landmarks[PoseLandmark.RIGHT_HIP]
        left_knee     = landmarks[PoseLandmark.LEFT_KNEE]
        right_knee    = landmarks[PoseLandmark.RIGHT_KNEE]

        avg_shoulder_y = (left_shoulder.y + right_shoulder.y) / 2
        avg_hip_y      = (left_hip.y + right_hip.y) / 2
        avg_knee_y     = (left_knee.y + right_knee.y) / 2

        if (abs(left_wrist.y - left_elbow.y) < 0.1 and abs(right_wrist.y - right_elbow.y) < 0.1
                and abs(left_wrist.y - left_shoulder.y) < 0.1 and abs(right_wrist.y - right_shoulder.y) < 0.1):
            return "T-Pose", confidence_score

        if (abs(left_wrist.x - right_wrist.x) < 0.3 and left_wrist.y < left_elbow.y
                and right_wrist.y < right_elbow.y and left_wrist.y < left_shoulder.y
                and right_wrist.y < right_shoulder.y
                and not abs(left_wrist.x - left_elbow.x) < 0.1
                and not abs(right_wrist.x - right_elbow.x) < 0.1):
            return "Heart", confidence_score

        if (left_wrist.y < left_elbow.y and right_wrist.y < right_elbow.y
                and left_wrist.y < left_shoulder.y and right_wrist.y < right_shoulder.y):
            return "Hands Up", confidence_score

        if ((left_wrist.y < left_elbow.y or right_wrist.y < right_elbow.y)
                and (left_wrist.y < left_shoulder.y or right_wrist.y < right_shoulder.y)):
            return "Waving", confidence_score

        if (abs(left_wrist.x - right_wrist.x) < 0.05 and left_wrist.y < left_elbow.y
                and right_wrist.y < right_elbow.y and left_wrist.y > left_shoulder.y):
            return "Folded Hands", confidence_score

        if (left_wrist.x > right_shoulder.x and right_wrist.x < left_shoulder.x
                and left_elbow.y > left_wrist.y and right_elbow.y > right_wrist.y):
            return "Arms Crossed", confidence_score

        if abs(avg_shoulder_y - avg_hip_y) <= 0.2 and avg_hip_y < avg_knee_y:
            return "Bending Down", confidence_score

        if avg_hip_y > avg_knee_y and abs(left_hip.y - right_hip.y) < 0.5:
            return "Sitting", confidence_score

        if (abs(left_wrist.y - left_hip.y) < 0.1 and abs(right_wrist.y - right_hip.y) < 0.1
                and left_elbow.x < left_wrist.x and right_elbow.x > right_wrist.x):
            return "Standing", confidence_score

        if abs(avg_shoulder_y - avg_hip_y) > 0.2 and avg_hip_y < avg_knee_y:
            return "Hands on Hips", confidence_score

        return "Normal Pose", confidence_score

    def _detect_eye_direction(self, landmarks):
        """Detect eye movement direction from a list of NormalizedLandmark objects."""
        if landmarks is None:
            return "Unknown", 0.0

        left_eye_x,  left_eye_y  = self._calculate_eye_center(landmarks, LEFT_EYE)
        right_eye_x, right_eye_y = self._calculate_eye_center(landmarks, RIGHT_EYE)
        left_iris_x, left_iris_y = self._calculate_iris_center(landmarks, LEFT_IRIS)
        right_iris_x, right_iris_y = self._calculate_iris_center(landmarks, RIGHT_IRIS)

        left_rel_x  = left_iris_x  - left_eye_x
        right_rel_x = right_iris_x - right_eye_x
        left_rel_y  = left_iris_y  - left_eye_y
        right_rel_y = right_iris_y - right_eye_y

        avg_rel_x = (left_rel_x + right_rel_x) / 2
        avg_rel_y = (left_rel_y + right_rel_y) / 2

        threshold_x = 0.01
        threshold_y = 0.01
        confidence = max(abs(avg_rel_x), abs(avg_rel_y)) * 5

        if abs(avg_rel_x) < threshold_x and abs(avg_rel_y) < threshold_y:
            return "Center (Neutral)", confidence
        elif avg_rel_x < -threshold_x and abs(avg_rel_y) < threshold_y:
            return "Looking Left (Truth/Memory)", confidence
        elif avg_rel_x > threshold_x and abs(avg_rel_y) < threshold_y:
            return "Looking Right (Imagination/Lie)", confidence
        elif abs(avg_rel_x) < threshold_x and avg_rel_y < -threshold_y:
            return "Looking Up (Visual Memory)", confidence
        elif abs(avg_rel_x) < threshold_x and avg_rel_y > threshold_y:
            return "Looking Down (Auditory Internal)", confidence
        elif avg_rel_x < -threshold_x and avg_rel_y < -threshold_y:
            return "Looking Up Left (Visual Memory)", confidence
        elif avg_rel_x > threshold_x and avg_rel_y < -threshold_y:
            return "Looking Up Right (Visual Construct)", confidence

        return "Unknown", confidence

    def _detect_cheating(self, frame):
        """Detect cheating indicators such as multiple people or devices."""
        global yolo_model

        if yolo_model is None:
            try:
                if os.path.exists(self.yolo_model_path):
                    logger.info(f"Loading YOLO model from {self.yolo_model_path}")
                    yolo_model = YOLO(self.yolo_model_path)
                else:
                    logger.error(f"YOLO model file not found at {self.yolo_model_path}")
                    return {
                        "people_count": 1,
                        "direction_looking": "at-system",
                        "communication_device_present": False,
                    }
            except Exception as e:
                logger.error(f"Error loading YOLO model: {e}")
                return {
                    "people_count": 1,
                    "direction_looking": "at-system",
                    "communication_device_present": False,
                }

        try:
            results = yolo_model(frame, conf=0.25)
            people_count = 0
            communication_device_present = False
            direction_looking = "at-system"

            for box in results[0].boxes:
                cls = int(box.cls[0])
                detected_class = yolo_model.names[cls]
                conf = float(box.conf[0])

                color = (0, 255, 0) if detected_class == "person" else (0, 0, 255)
                cv2.rectangle(
                    frame,
                    (int(box.xyxy[0][0]), int(box.xyxy[0][1])),
                    (int(box.xyxy[0][2]), int(box.xyxy[0][3])),
                    color, 2,
                )
                label = f"{detected_class} {conf:.2f}"
                cv2.putText(frame, label, (int(box.xyxy[0][0]), int(box.xyxy[0][1]) - 10),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)

                if detected_class == "person":
                    people_count += 1
                    if people_count > 1:
                        try:
                            os.system("afplay /System/Library/Sounds/Ping.aiff")
                        except Exception as beep_error:
                            logger.error(f"Error generating beep sound: {beep_error}")
                elif detected_class in ["laptop", "remote", "cell phone", "tvmonitor"]:
                    communication_device_present = True
                    try:
                        os.system("afplay /System/Library/Sounds/Ping.aiff")
                    except Exception as beep_error:
                        logger.error(f"Error generating beep sound for device: {beep_error}")

            # Use pose to determine gaze direction when only one person is detected
            if people_count == 1:
                image_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                pose_result = _detect_with_pose(image_rgb)
                if pose_result.pose_landmarks:
                    h, w, _ = frame.shape
                    lms = pose_result.pose_landmarks[0]
                    nose      = lms[PoseLandmark.NOSE]
                    left_eye  = lms[PoseLandmark.LEFT_EYE]
                    right_eye = lms[PoseLandmark.RIGHT_EYE]

                    nose_coords      = (int(nose.x * w),      int(nose.y * h))
                    left_eye_coords  = (int(left_eye.x * w),  int(left_eye.y * h))
                    right_eye_coords = (int(right_eye.x * w), int(right_eye.y * h))

                    mid_eye_x = (left_eye_coords[0] + right_eye_coords[0]) / 2
                    mid_eye_y = (left_eye_coords[1] + right_eye_coords[1]) / 2
                    dist_nose_mid_eye_x = abs(nose_coords[0] - mid_eye_x)
                    dist_nose_mid_eye_y = abs(nose_coords[1] - mid_eye_y)
                    dist_between_eyes = math.sqrt(
                        (right_eye_coords[0] - left_eye_coords[0]) ** 2
                        + (right_eye_coords[1] - left_eye_coords[1]) ** 2
                    )

                    screen_threshold_x = dist_between_eyes * 0.2
                    screen_threshold_y = dist_between_eyes * 0.2

                    if dist_nose_mid_eye_x < screen_threshold_x and dist_nose_mid_eye_y < screen_threshold_y:
                        direction_looking = "at-system"
                    else:
                        if nose_coords[1] < mid_eye_y and nose_coords[0] < mid_eye_x:
                            direction_looking = "up-left"
                        elif nose_coords[1] < mid_eye_y and nose_coords[0] > mid_eye_x:
                            direction_looking = "up-right"
                        elif nose_coords[1] > mid_eye_y and nose_coords[0] < mid_eye_x:
                            direction_looking = "down-left"
                        elif nose_coords[1] > mid_eye_y and nose_coords[0] > mid_eye_x:
                            direction_looking = "down-right"

            return {
                "people_count": people_count,
                "direction_looking": direction_looking,
                "communication_device_present": communication_device_present,
            }

        except Exception as e:
            logger.error(f"Error in cheating detection: {e}")
            return {
                "people_count": 1,
                "direction_looking": "unknown",
                "communication_device_present": False,
            }

    def _detect_basic_pose(self, frame: np.ndarray) -> Dict[str, Any]:
        """A reliable basic pose detector that won't fail"""
        results = {
            "pose": "Normal Pose",
            "pose_confidence": 0.8,
            "emotion": "Neutral",
            "emotion_confidence": 0.7,
            "eye_direction": "Center (Neutral)",
            "eye_confidence": 0.9,
            "people_count": 1,
            "direction_looking": "at-system",
            "communication_device_present": False,
        }

        try:
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            logger.info("Processing frame with MediaPipe Pose Landmarker...")

            pose_result = _detect_with_pose(rgb_frame)
            if pose_result.pose_landmarks:
                logger.info("MediaPipe pose landmarks detected")
                pose_type, pose_confidence = self._detect_pose(pose_result.pose_landmarks[0])
                results["pose"] = pose_type
                results["pose_confidence"] = float(pose_confidence)
                results["people_count"] = 1
                logger.info(f"Pose detected: {pose_type} with confidence {pose_confidence}")

                try:
                    face_result = _detect_with_face(rgb_frame)
                    if face_result.face_landmarks:
                        eye_direction, eye_confidence = self._detect_eye_direction(
                            face_result.face_landmarks[0]
                        )
                        results["eye_direction"] = eye_direction
                        results["eye_confidence"] = float(eye_confidence)
                    else:
                        logger.warning("Face landmarker did not detect any faces")
                except Exception as e:
                    logger.error(f"Eye tracking failed: {e}")

                try:
                    lms = pose_result.pose_landmarks[0]
                    h, w, _ = frame.shape
                    nose      = lms[PoseLandmark.NOSE]
                    left_eye  = lms[PoseLandmark.LEFT_EYE]
                    right_eye = lms[PoseLandmark.RIGHT_EYE]

                    nose_coords      = (int(nose.x * w),      int(nose.y * h))
                    left_eye_coords  = (int(left_eye.x * w),  int(left_eye.y * h))
                    right_eye_coords = (int(right_eye.x * w), int(right_eye.y * h))

                    mid_eye_x = (left_eye_coords[0] + right_eye_coords[0]) / 2
                    mid_eye_y = (left_eye_coords[1] + right_eye_coords[1]) / 2
                    dist_nose_mid_eye_x = abs(nose_coords[0] - mid_eye_x)
                    dist_nose_mid_eye_y = abs(nose_coords[1] - mid_eye_y)
                    dist_between_eyes = math.sqrt(
                        (right_eye_coords[0] - left_eye_coords[0]) ** 2
                        + (right_eye_coords[1] - left_eye_coords[1]) ** 2
                    )
                    screen_threshold_x = dist_between_eyes * 0.2
                    screen_threshold_y = dist_between_eyes * 0.2

                    if dist_nose_mid_eye_x < screen_threshold_x and dist_nose_mid_eye_y < screen_threshold_y:
                        results["direction_looking"] = "at-system"
                    else:
                        if nose_coords[1] < mid_eye_y and nose_coords[0] < mid_eye_x:
                            results["direction_looking"] = "up-left"
                        elif nose_coords[1] < mid_eye_y and nose_coords[0] > mid_eye_x:
                            results["direction_looking"] = "up-right"
                        elif nose_coords[1] > mid_eye_y and nose_coords[0] < mid_eye_x:
                            results["direction_looking"] = "down-left"
                        elif nose_coords[1] > mid_eye_y and nose_coords[0] > mid_eye_x:
                            results["direction_looking"] = "down-right"
                except Exception as e:
                    logger.error(f"Direction detection failed: {e}")

                try:
                    face_result = _detect_with_face(rgb_frame)
                    if face_result.face_landmarks:
                        face_lms = face_result.face_landmarks[0]
                        mouth_top    = face_lms[61]
                        mouth_bottom = face_lms[291]
                        mouth_height = abs(mouth_bottom.y - mouth_top.y)
                        results["emotion"] = "Speaking" if mouth_height > 0.03 else "Neutral"
                        results["emotion_confidence"] = 0.7
                except Exception as e:
                    logger.error(f"Emotion detection failed: {e}")
            else:
                logger.warning("No pose landmarks detected")
                results["pose"] = "No Person Detected"
                results["pose_confidence"] = 0.3
                results["people_count"] = 0

        except Exception as e:
            logger.error(f"Error in basic pose detection: {str(e)}")
            logger.exception("Full exception details:")

        return results

    def _calculate_eye_center(self, landmarks, eye_indices):
        """Calculate the center of the eye"""
        x_sum = sum(landmarks[i].x for i in eye_indices)
        y_sum = sum(landmarks[i].y for i in eye_indices)
        return x_sum / len(eye_indices), y_sum / len(eye_indices)

    def _calculate_iris_center(self, landmarks, iris_indices):
        """Calculate the center of the iris"""
        x_sum = sum(landmarks[i].x for i in iris_indices)
        y_sum = sum(landmarks[i].y for i in iris_indices)
        return x_sum / len(iris_indices), y_sum / len(iris_indices)
