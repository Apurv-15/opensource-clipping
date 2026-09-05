"""
clipping.studio.crop_stabilizer

Fixes the "static, off-center crop" bug:
Anchors the crop on EYE/NOSE landmarks rather than the full face bbox
(which includes hair mass that drags the centroid backward and pushes the face
toward the frame edge).
Enforces a hard edge-margin constraint every frame: no anchor landmark may sit
closer than margin_ratio of crop width to any crop edge.
Temporal smoothing via EMA with hard reset support.
"""

from dataclasses import dataclass
from typing import Optional, Tuple, List, Set
import cv2


@dataclass
class DiarizationSegment:
    speaker: str
    start: float
    end: float


def detect_visual_cuts(
    video_path: str,
    start_sec: float = 0.0,
    end_sec: Optional[float] = None,
    hist_corr_threshold: float = 0.55,
    min_gap_frames: int = 6,
) -> Tuple[Set[float], float]:
    """
    Returns (cut_timestamps_set, fps).
    HSV histogram correlation detects hard scene and camera cuts reliably.
    """
    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0

    if start_sec > 0:
        cap.set(cv2.CAP_PROP_POS_MSEC, start_sec * 1000)

    cuts = set()
    prev_hist = None
    frame_idx = 0
    last_cut_frame = -min_gap_frames

    max_frames = None
    if end_sec is not None and end_sec > start_sec:
        max_frames = int((end_sec - start_sec) * fps)

    while True:
        ret, frame = cap.read()
        if not ret:
            break
        if max_frames is not None and frame_idx >= max_frames:
            break

        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        hist = cv2.calcHist([hsv], [0, 1], None, [50, 60], [0, 180, 0, 256])
        cv2.normalize(hist, hist, 0, 1, cv2.NORM_MINMAX)

        if prev_hist is not None:
            corr = cv2.compareHist(prev_hist, hist, cv2.HISTCMP_CORREL)
            if corr < hist_corr_threshold and (frame_idx - last_cut_frame) >= min_gap_frames:
                cut_time = start_sec + (frame_idx / fps)
                cuts.add(round(cut_time, 3))
                last_cut_frame = frame_idx

        prev_hist = hist
        frame_idx += 1

    cap.release()
    return cuts, fps


def get_cut_timestamps(
    video_path: str,
    start_sec: float = 0.0,
    end_sec: Optional[float] = None,
    diarization_data: Optional[List[dict]] = None,
    hist_corr_threshold: float = 0.55,
    merge_window_sec: float = 0.25,
) -> Set[float]:
    """
    Unified cut set: visual cuts UNION diarization speaker cuts.
    """
    visual_cuts, fps = detect_visual_cuts(
        video_path=video_path,
        start_sec=start_sec,
        end_sec=end_sec,
        hist_corr_threshold=hist_corr_threshold,
    )
    all_cuts = list(visual_cuts)

    if diarization_data:
        prev_speaker = None
        for seg in diarization_data:
            spk = seg.get("speaker")
            s_start = seg.get("start", 0.0)
            if start_sec <= s_start <= (end_sec if end_sec else float("inf")):
                if prev_speaker is not None and spk != prev_speaker:
                    if not any(abs(s_start - vc) <= merge_window_sec for vc in visual_cuts):
                        all_cuts.append(round(s_start, 3))
                prev_speaker = spk

    return set(all_cuts)


@dataclass
class Landmarks:
    left_eye: Tuple[float, float]
    right_eye: Tuple[float, float]
    nose_tip: Tuple[float, float]


@dataclass
class CropRect:
    x: int
    y: int
    w: int
    h: int


class CropStabilizer:
    def __init__(
        self,
        frame_w: int,
        frame_h: int,
        target_aspect: float = 9 / 16,
        max_zoom: float = 1.35,
        margin_ratio: float = 0.18,     # Min distance from any landmark to crop edge (fraction of crop width)
        smoothing_alpha: float = 0.15,  # Lower = smoother/slower, higher = snappier
        headroom_ratio: float = 0.38,   # Eye-line sits ~38% down from top of crop (rule of thirds)
    ):
        self.frame_w = frame_w
        self.frame_h = frame_h
        self.target_aspect = target_aspect
        self.max_zoom = max_zoom
        self.margin_ratio = margin_ratio
        self.alpha = smoothing_alpha
        self.headroom_ratio = headroom_ratio

        # Base (zoom=1.0) crop is the largest target-aspect window that fits the source frame.
        base_h = frame_h
        base_w = int(base_h * target_aspect)
        if base_w > frame_w:
            base_w = frame_w
            base_h = int(base_w / target_aspect)
        self.base_w = base_w
        self.base_h = base_h

        self._smoothed_cx: Optional[float] = None
        self._smoothed_cy: Optional[float] = None
        self._smoothed_zoom: Optional[float] = None

    def reset(self):
        """Call on detected scene/speaker cut so smoothing doesn't drag across an edit."""
        self._smoothed_cx = None
        self._smoothed_cy = None
        self._smoothed_zoom = None

    def compute(self, lm: Landmarks, is_cut: bool = False) -> CropRect:
        if is_cut:
            self.reset()

        eye_cx = (lm.left_eye[0] + lm.right_eye[0]) / 2.0
        eye_cy = (lm.left_eye[1] + lm.right_eye[1]) / 2.0
        interocular = abs(lm.right_eye[0] - lm.left_eye[0]) or 1.0

        # Anchor point weighted toward eyes (stable) with a nudge toward the nose
        # to account for head yaw (keeps 3/4 or profile turns centered).
        anchor_x = 0.7 * eye_cx + 0.3 * lm.nose_tip[0]
        anchor_y = 0.7 * eye_cy + 0.3 * lm.nose_tip[1]

        # Zoom derived from interocular distance, capped
        reference_interocular = 0.055 * self.base_w
        raw_zoom = reference_interocular / interocular
        zoom = max(1.0, min(self.max_zoom, raw_zoom))

        # Smoothing (EMA), reset-safe
        if self._smoothed_cx is None:
            self._smoothed_cx, self._smoothed_cy, self._smoothed_zoom = anchor_x, anchor_y, zoom
        else:
            a = self.alpha
            self._smoothed_cx = a * anchor_x + (1 - a) * self._smoothed_cx
            self._smoothed_cy = a * anchor_y + (1 - a) * self._smoothed_cy
            self._smoothed_zoom = a * zoom + (1 - a) * self._smoothed_zoom

        cx, cy = self._smoothed_cx, self._smoothed_cy
        current_zoom = self._smoothed_zoom or 1.0
        crop_w = int(self.base_w / current_zoom)
        crop_h = int(self.base_h / current_zoom)

        crop_x = cx - crop_w / 2
        crop_y = cy - crop_h * self.headroom_ratio  # Keep eye-line in upper-middle

        # Hard edge-margin constraint: never let the anchor sit within margin_ratio*crop_w of edges
        margin = self.margin_ratio * crop_w
        min_crop_x = anchor_x - crop_w + margin
        max_crop_x = anchor_x - margin
        crop_x = max(min_crop_x, min(max_crop_x, crop_x))

        # Clamp to source frame bounds
        crop_x = max(0, min(self.frame_w - crop_w, crop_x))
        crop_y = max(0, min(self.frame_h - crop_h, crop_y))

        return CropRect(x=int(crop_x), y=int(crop_y), w=int(crop_w), h=int(crop_h))


def estimate_landmarks_from_bbox(bbox_x: float, bbox_y: float, bbox_w: float, bbox_h: float) -> Landmarks:
    """Fallback if landmarks are unavailable."""
    eye_y = bbox_y + bbox_h * 0.38
    nose_y = bbox_y + bbox_h * 0.55
    return Landmarks(
        left_eye=(bbox_x + bbox_w * 0.32, eye_y),
        right_eye=(bbox_x + bbox_w * 0.68, eye_y),
        nose_tip=(bbox_x + bbox_w * 0.5, nose_y),
    )
