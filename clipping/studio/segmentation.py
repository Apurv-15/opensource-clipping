"""
clipping.studio.segmentation — Fast AI Foreground Segmentation (Text-Behind-Person Effect)

Uses Google MediaPipe Selfie Segmenter to generate real-time alpha mattes
for compositing kinetic typography and 3D text behind the speaker without
slowing down rendering.
"""

import os
import cv2
import numpy as np
import mediapipe as mp
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision as mp_vision

_SEGMENTER_INSTANCE = None
_MODEL_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "assets", "selfie_segmenter.tflite"))


def get_segmenter(model_path: str = None) -> mp_vision.ImageSegmenter:
    """
    Get or initialize a cached MediaPipe ImageSegmenter instance.
    """
    global _SEGMENTER_INSTANCE
    target_path = model_path or _MODEL_PATH
    if _SEGMENTER_INSTANCE is None:
        if not os.path.exists(target_path):
            import urllib.request
            os.makedirs(os.path.dirname(target_path), exist_ok=True)
            url = "https://storage.googleapis.com/mediapipe-models/image_segmenter/selfie_segmenter/float16/latest/selfie_segmenter.tflite"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req) as r, open(target_path, "wb") as f:
                f.write(r.read())

        base_options = mp_python.BaseOptions(model_asset_path=target_path)
        options = mp_vision.ImageSegmenterOptions(base_options=base_options, output_category_mask=True)
        _SEGMENTER_INSTANCE = mp_vision.ImageSegmenter.create_from_options(options)

    return _SEGMENTER_INSTANCE


def generate_segmentation_mask_video(
    input_video_path: str,
    output_mask_path: str,
    target_w: int,
    target_h: int,
    fps: float = 30.0,
    blur_ksize: int = 7,
) -> bool:
    """
    Extract per-frame foreground human silhouette mask into an efficient video track.
    Used by FFmpeg `alphamerge` to layer the speaker seamlessly over text.

    Args:
        input_video_path: Path to the visual source video.
        output_mask_path: Path to write the grayscale mask video (0=bg, 255=person).
        target_w: Width of output canvas.
        target_h: Height of output canvas.
        fps: Video framerate.
        blur_ksize: Gaussian blur kernel size for cinematic edge feathering.

    Returns:
        bool: True on success, False otherwise.
    """
    segmenter = get_segmenter()
    cap = cv2.VideoCapture(input_video_path)
    if not cap.isOpened():
        return False

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    out = cv2.VideoWriter(output_mask_path, fourcc, fps, (target_w, target_h), isColor=False)

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                break

            # Fast downscale for inference (MediaPipe segmenter excels at 256x256 to 512x512)
            small = cv2.resize(frame, (512, 512), interpolation=cv2.INTER_LINEAR)
            rgb = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)
            mp_img = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)

            res = segmenter.segment(mp_img)
            mask = res.category_mask.numpy_view().squeeze()

            # Upscale mask to full render resolution and soften edges
            mask_full = cv2.resize(
                (mask > 0).astype(np.uint8) * 255,
                (target_w, target_h),
                interpolation=cv2.INTER_LINEAR,
            )
            if blur_ksize > 1:
                mask_full = cv2.GaussianBlur(mask_full, (blur_ksize, blur_ksize), 0)

            out.write(mask_full)

        return True
    finally:
        cap.release()
        out.release()
