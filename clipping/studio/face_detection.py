import html
import importlib.util
import json
import math
import os
import random
import re
import shutil
import string
import subprocess
import textwrap
import time
import urllib.parse
import urllib.request

import cv2
import mediapipe as mp
import numpy as np
import requests
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision as mp_vision
from PIL import Image, ImageDraw, ImageFont
from yt_dlp import YoutubeDL

FIREFOX_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:148.0) Gecko/20100101 Firefox/148.0"

def _load_studio_internal_module(file_name: str, module_alias: str):
    module_path = os.path.join(os.path.dirname(__file__), file_name)
    spec = importlib.util.spec_from_file_location(module_alias, module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

_helpers = _load_studio_internal_module("helpers.py", "clipping_studio_helpers")
_ffmpeg_utils = _load_studio_internal_module("ffmpeg_utils.py", "clipping_studio_ffmpeg_utils")
format_seconds = _helpers.format_seconds
escape_ffmpeg_filter_value = _helpers.escape_ffmpeg_filter_value
detect_video_encoder = _ffmpeg_utils.detect_video_encoder
get_ts_encode_args = _ffmpeg_utils.get_ts_encode_args
get_mp4_encode_args = _ffmpeg_utils.get_mp4_encode_args
open_ffmpeg_video_writer = _ffmpeg_utils.open_ffmpeg_video_writer
build_ffmpeg_progress_cmd = _ffmpeg_utils.build_ffmpeg_progress_cmd
run_ffmpeg_with_progress = _ffmpeg_utils.run_ffmpeg_with_progress


import platform

class _BoundingBox:
    def __init__(self, x, y, w, h):
        self.origin_x = x
        self.origin_y = y
        self.width = w
        self.height = h

class _Detection:
    def __init__(self, x, y, w, h, left_eye=None, right_eye=None, nose_tip=None):
        self.bounding_box = _BoundingBox(x, y, w, h)
        self.left_eye = left_eye
        self.right_eye = right_eye
        self.nose_tip = nose_tip

class _DetectionResult:
    def __init__(self, detections):
        self.detections = detections

class YuNetDetectorWrapper:
    def __init__(self, model_path="face_detection_yunet.onnx"):
        if not os.path.isabs(model_path):
            base = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
            cand = os.path.join(base, model_path)
            if os.path.exists(cand):
                model_path = cand
        self.detector = cv2.FaceDetectorYN.create(
            model=model_path,
            config="",
            input_size=(640, 480),
            score_threshold=0.5,
        )

    def detect(self, mp_image):
        if hasattr(mp_image, "numpy_view"):
            img = mp_image.numpy_view()
        elif hasattr(mp_image, "data"):
            img = mp_image.data
        else:
            img = mp_image
        h, w = img.shape[:2]
        self.detector.setInputSize((w, h))
        if len(img.shape) == 3 and img.shape[2] == 3:
            bgr = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
        else:
            bgr = img
        _, faces = self.detector.detect(bgr)
        detections = []
        if faces is not None:
            for f in faces:
                x, y, fw, fh = int(f[0]), int(f[1]), int(f[2]), int(f[3])
                # YuNet 5 landmarks: right_eye (f[4:6]), left_eye (f[6:8]), nose_tip (f[8:10])
                r_eye = (float(f[4]), float(f[5])) if len(f) > 5 else None
                l_eye = (float(f[6]), float(f[7])) if len(f) > 7 else None
                nose = (float(f[8]), float(f[9])) if len(f) > 9 else None
                detections.append(_Detection(x, y, fw, fh, left_eye=l_eye, right_eye=r_eye, nose_tip=nose))
        return _DetectionResult(detections)


_FACE_DETECTOR = None

def get_face_detector(cfg):
    """
    Create or reuse a singleton face detector instance.
    Uses native OpenCV YuNet on macOS to prevent MediaPipe Metal crashes,
    falling back to MediaPipe Tasks where supported.
    """
    global _FACE_DETECTOR

    if _FACE_DETECTOR is not None:
        return _FACE_DETECTOR

    # On macOS, MediaPipe DrishtiMetalHelper causes a fatal C++ abort on Apple Silicon.
    # Use native OpenCV YuNet for 100% stability.
    yunet_cand = getattr(cfg, "file_yunet_model", "face_detection_yunet.onnx")
    if not os.path.isabs(yunet_cand):
        yunet_cand = os.path.join(getattr(cfg, "base_dir", os.getcwd()), yunet_cand)

    if platform.system() == "Darwin" and os.path.exists(yunet_cand):
        print("   🛡️ Using OpenCV YuNet neural face detector (macOS native)...", flush=True)
        _FACE_DETECTOR = YuNetDetectorWrapper(yunet_cand)
        return _FACE_DETECTOR

    try:
        if not os.path.exists(cfg.file_mediapipe_model):
            urllib.request.urlretrieve(
                cfg.url_mediapipe_model, cfg.file_mediapipe_model
            )

        base_options = mp_python.BaseOptions(model_asset_path=cfg.file_mediapipe_model)
        _FACE_DETECTOR = mp_vision.FaceDetector.create_from_options(
            mp_vision.FaceDetectorOptions(
                base_options=base_options,
                min_detection_confidence=0.5,
            )
        )
    except Exception as e:
        print(f"   ⚠️ MediaPipe face detector failed ({e}). Falling back to YuNet.", flush=True)
        _FACE_DETECTOR = YuNetDetectorWrapper(yunet_cand)

    return _FACE_DETECTOR


def estimate_speaker_count_from_video(video_path: str, cfg) -> int:
    """
    Sample frames from the video to estimate the max number of visible faces.
    Used for automatically setting min_speakers for pyannote.

    Args:
        video_path (str): The absolute path to the video file.
        cfg: Runtime configuration that may specify 'face_detector' (e.g. 'yolo' or 'mediapipe').

    Returns:
        int: The estimated maximum number of speakers (faces) present in any sampled frame. Defaults to 2 if unsure.

    Side Effects:
        Downloads YOLO face detection model if it's set in config and doesn't exist.
        Prints scanning progress logs to stdout.

    Raises:
        Exception: General exceptions may occur during YOLO initialization, falling back to Mediapipe.
    """
    import cv2

    print("🔍 Auto-detecting speaker count via visual scanning...", flush=True)

    yolo_model = None
    detector = None

    if cfg.face_detector == "yolo":
        from ultralytics import YOLO
        import logging

        logging.getLogger("ultralytics").setLevel(logging.ERROR)
        try:
            model_name = f"yolov{cfg.yolo_size}-face.pt"
            yolo_model = YOLO(model_name)
        except Exception as e:
            print(f"⚠️ YOLO face detect failed: {e}. Fallback to Mediapipe.")
            cfg.face_detector = "mediapipe"

    if cfg.face_detector != "yolo":
        detector = get_face_detector(cfg)

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return 2

    fps = cap.get(cv2.CAP_PROP_FPS)
    total_frames = cap.get(cv2.CAP_PROP_FRAME_COUNT)
    duration = total_frames / fps if fps > 0 else 0

    if duration == 0:
        cap.release()
        return 2

    sample_count = 20
    step = duration / sample_count
    max_faces = 0

    for i in range(sample_count):
        t = i * step
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
        ret, frame = cap.read()
        if not ret:
            continue

        faces_in_frame = 0

        if cfg.face_detector == "yolo" and yolo_model:
            results = yolo_model(frame, verbose=False)
            if results and len(results[0].boxes) > 0:
                faces_in_frame = len(results[0].boxes)
        else:
            mp_image = mp.Image(
                image_format=mp.ImageFormat.SRGB,
                data=cv2.cvtColor(frame, cv2.COLOR_BGR2RGB),
            )
            results = detector.detect(mp_image)
            if results.detections:
                faces_in_frame = len(results.detections)

        if faces_in_frame > max_faces:
            max_faces = faces_in_frame

    cap.release()
    print(f"   ✅ Found maximum {max_faces} faces in a single frame.", flush=True)
    return max(1, max_faces)


