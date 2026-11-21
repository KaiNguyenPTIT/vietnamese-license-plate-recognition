"""Pipeline nhận dạng hoàn chỉnh và lưu ảnh trung gian.

Luồng:
    đọc ảnh -> tiền xử lý -> phát hiện ứng viên -> cắt/hiệu chỉnh phối cảnh
    -> phân đoạn ký tự -> chuẩn hóa + template matching -> hậu xử lý
    -> quyết định trạng thái -> xuất kết quả/ảnh debug.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np

from .character_recognition import (
    CharacterPrediction,
    TemplateError,
    TemplateLibrary,
    load_templates,
    recognize_characters,
)
from .character_segmentation import SegmentationResult, segment_characters
from .config import Config
from .io_utils import expand_bbox, safe_filename, write_image
from .plate_detection import (
    DetectionResult,
    PlateCandidate,
    detect_plates,
    select_top_candidates,
)
from .plate_rectification import (
    RectificationResult,
    map_rectified_bbox_to_work,
    rectify_plate,
)
from .postprocessing import (
    PlateTextResult,
    build_text_result,
    resolve_position_constraints,
)
from .preprocessing import (
    InvalidImageError,
    PreprocessResult,
    preprocess,
)


STATUS_PRIORITY = {
    "SUCCESS": 5,
    "FORMAT_WARNING": 4,
    "LOW_CONFIDENCE": 3,
    "PLATE_NOT_FOUND": 2,
    "INVALID_IMAGE": 1,
    "CONFIG_ERROR": 0,
}

STATUS_LABELS_VI = {
    "SUCCESS": "THÀNH CÔNG",
    "INVALID_IMAGE": "ẢNH KHÔNG HỢP LỆ",
    "PLATE_NOT_FOUND": "KHÔNG TÌM THẤY BIỂN SỐ",
    "LOW_CONFIDENCE": "KHÔNG ĐỦ TIN CẬY",
    "FORMAT_WARNING": "CẢNH BÁO ĐỊNH DẠNG",
    "CONFIG_ERROR": "LỖI CẤU HÌNH",
}


@dataclass
class CandidateAttempt:
    index: int
    candidate: PlateCandidate
    rectification: Optional[RectificationResult] = None
    segmentation: Optional[SegmentationResult] = None
    predictions: List[CharacterPrediction] = field(default_factory=list)
    text: Optional[PlateTextResult] = None
    status: str = "LOW_CONFIDENCE"
    error: Optional[str] = None
    char_boxes_original: List[Dict[str, Any]] = field(default_factory=list)
    timings_ms: Dict[str, float] = field(default_factory=dict)

    def ranking_key(self) -> Tuple[float, ...]:
        text_score = self.text.mean_score if self.text else 0.0
        seg_score = self.segmentation.score if self.segmentation else 0.0
        char_count = len(self.predictions)
        return (
            float(STATUS_PRIORITY.get(self.status, 0)),
            float(text_score),
            float(seg_score),
            float(self.candidate.score),
            float(char_count),
        )

    def as_dict(self) -> Dict[str, Any]:
        return {
            "index": self.index,
            "status": self.status,
            "error": self.error,
            "candidate": self.candidate.as_dict(),
            "rectification_method": self.rectification.method
            if self.rectification
            else None,
            "rectification_size": list(self.rectification.output_size)
            if self.rectification
            else None,
            "segmentation_status": self.segmentation.status
            if self.segmentation
            else None,
            "segmentation_count": self.segmentation.count
            if self.segmentation
            else 0,
            "segmentation_score": round(self.segmentation.score, 4)
            if self.segmentation
            else 0.0,
            "characters": [p.as_dict() for p in self.predictions],
            "text": self.text.as_dict() if self.text else None,
            "timings_ms": {k: round(v, 3) for k, v in self.timings_ms.items()},
        }


@dataclass
class RecognitionResult:
    status: str
    image_path: str = ""
    image: Optional[np.ndarray] = None
    bbox: Optional[Tuple[float, float, float, float]] = None
    bbox_original: Optional[Tuple[float, float, float, float]] = None
    preprocess: Optional[PreprocessResult] = None
    detection: Optional[DetectionResult] = None
    attempts: List[CandidateAttempt] = field(default_factory=list)
    selected_attempt: Optional[CandidateAttempt] = None
    text: Optional[PlateTextResult] = None
    message: str = ""
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    timings_ms: Dict[str, float] = field(default_factory=dict)
    total_time_ms: float = 0.0
    template_stats: Dict[str, Any] = field(default_factory=dict)
    config_snapshot: Dict[str, Any] = field(default_factory=dict)
    debug_dir: Optional[str] = None

    # ----------------------------- Thuộc tính tiện dụng -----------------
    @property
    def plate_image(self) -> Optional[np.ndarray]:
        if self.selected_attempt and self.selected_attempt.rectification:
            return self.selected_attempt.rectification.plate_image
        return None

    @property
    def plate_crop(self) -> Optional[np.ndarray]:
        if self.selected_attempt and self.selected_attempt.rectification:
            return self.selected_attempt.rectification.crop_image
        return None

    @property
    def rectification_method(self) -> str:
        if self.selected_attempt and self.selected_attempt.rectification:
            return self.selected_attempt.rectification.method
        return "none"

    @property
    def segmentation(self) -> Optional[SegmentationResult]:
        if self.selected_attempt:
            return self.selected_attempt.segmentation
        return None

    @property
    def predictions(self) -> List[CharacterPrediction]:
        if self.selected_attempt:
            return self.selected_attempt.predictions
        return []

    @property
    def characters(self):
        seg = self.segmentation
        return seg.characters if seg else []

    @property
    def char_boxes_original(self) -> List[Dict[str, Any]]:
        if self.selected_attempt:
            return self.selected_attempt.char_boxes_original
        return []

    @property
    def detected_text(self) -> str:
        return self.text.formatted_text if self.text else ""

    @property
    def raw_text(self) -> str:
        return self.text.raw_text if self.text else ""

    @property
    def normalized_text(self) -> str:
        return self.text.normalized_text if self.text else ""

    @property
    def display_status(self) -> str:
        return STATUS_LABELS_VI.get(self.status, self.status)

    # ----------------------------- Debug --------------------------------
    def debug_images(self) -> Dict[str, np.ndarray]:
        images: Dict[str, np.ndarray] = {}
        if self.image is not None:
            images["01_original"] = self.image.copy()
            if self.detection and self.detection.candidates:
                images["08_candidates"] = draw_candidates(
                    self.image,
                    self.detection.candidates,
                    self.preprocess.scale if self.preprocess else 1.0,
                    selected_index=self.selected_attempt.index
                    if self.selected_attempt
                    else None,
                )
            if self.bbox_original:
                x1, y1, x2, y2 = [int(round(v)) for v in self.bbox_original]
                overlay = self.image.copy()
                cv2.rectangle(overlay, (x1, y1), (x2, y2), (0, 255, 0), 3)
                images["09_selected_bbox"] = overlay
        if self.preprocess:
            p = self.preprocess
            images.update(
                {
                    "02_work": p.work_image.copy(),
                    "03_gray": p.gray.copy(),
                    "04_blurred": p.blurred.copy(),
                    "05_enhanced": p.enhanced.copy(),
                    "06_edges": p.edges.copy(),
                    "07_binary_otsu": p.binary_otsu.copy(),
                    "07b_binary_adaptive": p.binary_adaptive.copy(),
                }
            )
        if self.detection and self.detection.closed is not None:
            images["10_morphology_closed"] = self.detection.closed.copy()
        attempt = self.selected_attempt
        if attempt and attempt.rectification:
            images["11_plate_crop"] = attempt.rectification.crop_image.copy()
            images["12_plate_rectified"] = attempt.rectification.plate_image.copy()
        if attempt and attempt.segmentation:
            seg = attempt.segmentation
            if seg.binary is not None:
                images["13_plate_binary"] = seg.binary.copy()
        return images

    def as_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "display_status": self.display_status,
            "image_path": self.image_path,
            "bbox": list(self.bbox) if self.bbox else None,
            "bbox_original": list(self.bbox_original)
            if self.bbox_original
            else None,
            "detected_text": self.detected_text,
            "raw_text": self.raw_text,
            "normalized_text": self.normalized_text,
            "message": self.message,
            "warnings": list(self.warnings),
            "errors": list(self.errors),
            "rectification_method": self.rectification_method,
            "template_stats": self.template_stats,
            "timings_ms": {k: round(v, 3) for k, v in self.timings_ms.items()},
            "total_time_ms": round(self.total_time_ms, 3),
            "candidates": [c.as_dict() for c in self.detection.candidates]
            if self.detection
            else [],
            "attempts": [a.as_dict() for a in self.attempts],
            "selected_attempt_index": self.selected_attempt.index
            if self.selected_attempt
            else None,
            "text": self.text.as_dict() if self.text else None,
            "char_boxes_original": self.char_boxes_original,
            "debug_dir": self.debug_dir,
        }

    def as_csv_row(self) -> Dict[str, Any]:
        text = self.text
        return {
            "status": self.status,
            "image_path": self.image_path,
            "detected_text": self.detected_text,
            "raw_text": self.raw_text,
            "normalized_text": self.normalized_text,
            "format_valid": text.validation.is_valid if text else False,
            "mean_score": round(text.mean_score, 4) if text else 0.0,
            "min_score": round(text.min_score, 4) if text else 0.0,
            "char_count": text.char_count if text else 0,
            "unknown_count": text.unknown_count if text else 0,
            "rectification_method": self.rectification_method,
            "plate_score": round(
                self.selected_attempt.candidate.score
                if self.selected_attempt
                else 0.0,
                4,
            ),
            "total_time_ms": round(self.total_time_ms, 3),
            "preprocess_ms": round(self.timings_ms.get("preprocess", 0.0), 3),
            "detection_ms": round(self.timings_ms.get("detection", 0.0), 3),
            "rectification_ms": round(
                self.timings_ms.get("rectification", 0.0), 3
            ),
            "segmentation_ms": round(
                self.timings_ms.get("segmentation", 0.0), 3
            ),
            "recognition_ms": round(self.timings_ms.get("recognition", 0.0), 3),
            "postprocessing_ms": round(
                self.timings_ms.get("postprocessing", 0.0), 3
            ),
            "message": self.message,
        }


# ----------------------------------------------------------------------
# Vẽ overlay
# ----------------------------------------------------------------------
def draw_candidates(
    image: np.ndarray,
    candidates: Sequence[PlateCandidate],
    scale: float = 1.0,
    selected_index: Optional[int] = None,
) -> np.ndarray:
    canvas = image.copy()
    for idx, cand in enumerate(candidates):
        if scale <= 0:
            scale = 1.0
        x1, y1, x2, y2 = [int(round(v / scale)) for v in cand.bbox]
        is_selected = selected_index is not None and idx == selected_index
        color = (0, 255, 0) if is_selected else (0, 200, 255)
        thickness = 3 if is_selected else 2
        cv2.rectangle(canvas, (x1, y1), (x2, y2), color, thickness)
        label = f"#{idx + 1} {cand.score:.2f}"
        ty = max(18, y1 - 6)
        cv2.putText(
            canvas,
            label,
            (max(2, x1), ty),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            color,
            2,
            cv2.LINE_AA,
        )
    return canvas


def make_character_strip(
    predictions: Sequence[CharacterPrediction],
    characters: Sequence[Any],
    cell: int = 56,
    pad: int = 8,
) -> np.ndarray:
    """Tạo dải ảnh ký tự kèm dự đoán để hiển thị/lưu debug."""
    n = max(1, len(characters))
    width = n * (cell + pad) + pad
    height = cell + 46
    canvas = np.full((height, width, 3), 245, dtype=np.uint8)
    for i, (pred, ch) in enumerate(zip(predictions, characters)):
        img = pred.normalized_image
        if img is None and ch is not None:
            img = ch.image
        if img is None:
            continue
        img = cv2.resize(img, (cell, cell), interpolation=cv2.INTER_NEAREST)
        if img.ndim == 2:
            img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
        x = pad + i * (cell + pad)
        canvas[8 : 8 + cell, x : x + cell] = img
        label = pred.label if pred.status == "OK" else "?"
        color = (0, 120, 0) if pred.status == "OK" else (0, 0, 200)
        cv2.putText(
            canvas,
            label,
            (x + 18, cell + 34),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.65,
            color,
            2,
            cv2.LINE_AA,
        )
        cv2.putText(
            canvas,
            f"{pred.score:.2f}",
            (x + 4, cell + 46),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.38,
            (80, 80, 80),
            1,
            cv2.LINE_AA,
        )
    return canvas


# ----------------------------------------------------------------------
# Bộ nhận dạng
# ----------------------------------------------------------------------
class LicensePlateRecognizer:
    def __init__(
        self,
        config: Config,
        templates_dir: Optional[str | Path] = None,
        library: Optional[TemplateLibrary] = None,
    ):
        self.config = config
        self.template_error: Optional[str] = None
        if library is not None:
            self.library = library
        else:
            try:
                self.library = load_templates(templates_dir, config)
            except TemplateError as exc:
                self.library = TemplateLibrary()
                self.template_error = str(exc)

    def _base_result(self, status: str, message: str) -> RecognitionResult:
        return RecognitionResult(
            status=status,
            message=message,
            template_stats=self.library.stats(),
            config_snapshot=self.config.to_dict(),
        )

    def _map_char_boxes(
        self,
        attempt: CandidateAttempt,
        pre: PreprocessResult,
    ) -> List[Dict[str, Any]]:
        if not attempt.segmentation or not attempt.rectification:
            return []
        rect = attempt.rectification
        seg = attempt.segmentation
        output: List[Dict[str, Any]] = []
        for idx, (char, pred) in enumerate(
            zip(seg.characters, attempt.predictions)
        ):
            x1, y1, x2, y2 = char.bbox_plate
            pts = np.array(
                [[x1, y1], [x2, y1], [x2, y2], [x1, y2]], dtype=np.float32
            )
            mapped = rect.map_points_to_work(pts)
            if pre.scale > 0:
                mapped = mapped / pre.scale
            bx1, by1 = mapped[:, 0].min(), mapped[:, 1].min()
            bx2, by2 = mapped[:, 0].max(), mapped[:, 1].max()
            output.append(
                {
                    "order": idx,
                    "row_index": char.row_index,
                    "label": pred.label,
                    "status": pred.status,
                    "score": round(pred.score, 4),
                    "margin": round(pred.margin, 4),
                    "second_label": pred.second_label,
                    "second_score": round(pred.second_score, 4),
                    "bbox_original": [
                        round(float(bx1), 2),
                        round(float(by1), 2),
                        round(float(bx2), 2),
                        round(float(by2), 2),
                    ],
                }
            )
        return output

    def recognize(
        self,
        image_path: str | Path,
        save_debug: Optional[bool] = None,
        debug_dir: Optional[str | Path] = None,
    ) -> RecognitionResult:
        t_start = time.perf_counter()
        path = Path(image_path)
        if self.template_error and self.config.pipeline.fail_on_missing_templates:
            return self._base_result(
                "CONFIG_ERROR",
                f"Không thể nạp bộ template: {self.template_error}",
            )

        # 1. Tiền xử lý -------------------------------------------------
        try:
            pre = preprocess(path, self.config)
        except InvalidImageError as exc:
            result = self._base_result("INVALID_IMAGE", str(exc))
            result.image_path = str(path)
            result.errors.append(str(exc))
            return result
        except Exception as exc:  # pragma: no cover - phòng vệ bổ sung
            result = self._base_result(
                "INVALID_IMAGE", f"Lỗi không xác định khi đọc ảnh: {exc}"
            )
            result.image_path = str(path)
            result.errors.append(str(exc))
            return result

        result = self._base_result("PLATE_NOT_FOUND", "")
        result.image_path = str(path)
        result.image = pre.original
        result.preprocess = pre
        result.warnings.extend(pre.warnings)
        result.timings_ms["preprocess"] = pre.timings_ms.get(
            "preprocess_total_ms", 0.0
        )

        # 2. Phát hiện biển số ------------------------------------------
        try:
            t_detect = time.perf_counter()
            detection = detect_plates(pre, self.config)
            result.detection = detection
            result.timings_ms["detection"] = (
                time.perf_counter() - t_detect
            ) * 1000.0
            result.warnings.extend(detection.warnings)
        except Exception as exc:  # pragma: no cover
            result.status = "PLATE_NOT_FOUND"
            result.message = f"Lỗi trong công đoạn phát hiện biển số: {exc}"
            result.errors.append(str(exc))
            result.total_time_ms = (time.perf_counter() - t_start) * 1000.0
            return result

        if not detection.candidates:
            result.status = "PLATE_NOT_FOUND"
            result.message = (
                "Không tìm thấy ứng viên biển số đủ điều kiện hình học. "
                "Không có kết quả nhận dạng được tạo."
            )
            result.total_time_ms = (time.perf_counter() - t_start) * 1000.0
            self._maybe_save_debug(result, save_debug, debug_dir)
            return result

        # 3. Thử lần lượt các ứng viên ----------------------------------
        max_try = max(
            1, min(self.config.pipeline.max_candidates_to_try, len(detection.candidates))
        )
        best_attempt: Optional[CandidateAttempt] = None
        segmentation_time_total = 0.0
        recognition_time_total = 0.0
        rect_time_total = 0.0
        post_time_total = 0.0

        for idx in range(max_try):
            candidate = detection.candidates[idx]
            attempt = CandidateAttempt(index=idx, candidate=candidate)
            attempts_t0 = time.perf_counter()
            try:
                t_rect = time.perf_counter()
                rect = rectify_plate(pre.work_image, candidate, self.config)
                rect_ms = (time.perf_counter() - t_rect) * 1000.0
                attempt.rectification = rect
                attempt.timings_ms["rectification"] = rect_ms
                rect_time_total += rect_ms
                if rect.method == "invalid" or rect.plate_image.size == 0:
                    attempt.error = "Vùng biển số cắt ra không hợp lệ."
                    attempt.status = "LOW_CONFIDENCE"
                    result.attempts.append(attempt)
                    continue
                result.warnings.extend(rect.warnings)

                t_seg = time.perf_counter()
                seg = segment_characters(rect.plate_image, self.config)
                seg_ms = (time.perf_counter() - t_seg) * 1000.0
                attempt.segmentation = seg
                attempt.timings_ms["segmentation"] = seg_ms
                segmentation_time_total += seg_ms
                result.warnings.extend(seg.warnings)
                if seg.count == 0:
                    attempt.error = "Không phân đoạn được ký tự nào."
                    attempt.status = "LOW_CONFIDENCE"
                    result.attempts.append(attempt)
                    continue

                t_rec = time.perf_counter()
                predictions, rec_timings = recognize_characters(
                    [c.image for c in seg.characters], self.library, self.config
                )
                predictions = resolve_position_constraints(
                    predictions, self.config
                )
                rec_ms = (time.perf_counter() - t_rec) * 1000.0
                attempt.predictions = predictions
                attempt.timings_ms["recognition"] = rec_ms
                recognition_time_total += rec_ms

                t_post = time.perf_counter()
                text = build_text_result(predictions, seg.status, self.config)
                post_ms = (time.perf_counter() - t_post) * 1000.0
                attempt.text = text
                attempt.timings_ms["postprocessing"] = post_ms
                post_time_total += post_ms
                attempt.status = text.status
                attempt.char_boxes_original = self._map_char_boxes(attempt, pre)
                attempt.timings_ms["attempt_total"] = (
                    time.perf_counter() - attempts_t0
                ) * 1000.0
                result.attempts.append(attempt)

                if best_attempt is None or (
                    attempt.ranking_key() > best_attempt.ranking_key()
                ):
                    best_attempt = attempt
                if attempt.status == "SUCCESS":
                    best_attempt = attempt
                    break
            except Exception as exc:  # pragma: no cover
                attempt.error = f"Lỗi xử lý ứng viên: {exc}"
                attempt.status = "LOW_CONFIDENCE"
                attempt.timings_ms["attempt_total"] = (
                    time.perf_counter() - attempts_t0
                ) * 1000.0
                result.attempts.append(attempt)
                result.errors.append(str(exc))

        if best_attempt is None:
            result.status = "LOW_CONFIDENCE"
            result.message = (
                "Đã phát hiện ứng viên nhưng không thể cắt/hiệu chỉnh hoặc "
                "phân đoạn ký tự. Không tạo kết quả nhận dạng giả."
            )
            result.total_time_ms = (time.perf_counter() - t_start) * 1000.0
            self._maybe_save_debug(result, save_debug, debug_dir)
            return result

        result.selected_attempt = best_attempt
        result.text = best_attempt.text
        result.status = best_attempt.status
        result.message = (
            best_attempt.text.message
            if best_attempt.text
            else "Không có kết quả văn bản."
        )
        result.warnings.extend(
            [w for w in best_attempt.text.warnings if w not in result.warnings]
            if best_attempt.text
            else []
        )
        if best_attempt.rectification:
            result.bbox = best_attempt.rectification.roi_bbox
            result.bbox_original = tuple(
                v / pre.scale if pre.scale > 0 else v
                for v in best_attempt.candidate.bbox
            )
            # Ứng viên cụm chữ có thể được gắn hộp hình học bao trọn. Hộp
            # này phản ánh vị trí biển chính xác hơn nhưng không ảnh hưởng
            # vùng cắt đã dùng để nhận dạng.
            hint = best_attempt.candidate.bbox_hint
            hint_original = best_attempt.candidate.bbox_hint_original
            if hint is not None and hint_original is not None:
                result.bbox = hint
                result.bbox_original = hint_original
        result.timings_ms["rectification"] = rect_time_total
        result.timings_ms["segmentation"] = segmentation_time_total
        result.timings_ms["recognition"] = recognition_time_total
        result.timings_ms["postprocessing"] = post_time_total
        result.total_time_ms = (time.perf_counter() - t_start) * 1000.0
        result.timings_ms["pipeline_total"] = result.total_time_ms
        self._maybe_save_debug(result, save_debug, debug_dir)
        return result

    # ------------------------------------------------------------------
    def _maybe_save_debug(
        self,
        result: RecognitionResult,
        save_debug: Optional[bool],
        debug_dir: Optional[str | Path],
    ) -> None:
        should_save = (
            self.config.pipeline.save_debug if save_debug is None else save_debug
        )
        if not should_save:
            return
        if debug_dir is not None:
            out = Path(debug_dir)
        else:
            stem = safe_filename(Path(result.image_path).stem)
            out = self.config.resolve(self.config.pipeline.debug_dir) / stem
        try:
            result.debug_dir = str(save_debug_artifacts(result, out))
        except Exception as exc:  # pragma: no cover
            result.warnings.append(f"Không lưu được ảnh debug: {exc}")

    def recognize_batch(
        self,
        image_paths: Sequence[str | Path],
        progress: Optional[Callable[[int, int, str], None]] = None,
        stop_flag: Optional[Callable[[], bool]] = None,
    ) -> List[RecognitionResult]:
        results: List[RecognitionResult] = []
        total = len(image_paths)
        for idx, path in enumerate(image_paths, start=1):
            if stop_flag and stop_flag():
                break
            results.append(self.recognize(path))
            if progress:
                progress(idx, total, str(path))
        return results


# ----------------------------------------------------------------------
# Lưu debug
# ----------------------------------------------------------------------
def save_debug_artifacts(
    result: RecognitionResult, out_dir: str | Path
) -> Path:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for name, image in result.debug_images().items():
        write_image(out / f"{name}.png", image)
    if result.selected_attempt and result.selected_attempt.segmentation:
        seg = result.selected_attempt.segmentation
        char_dir = out / "characters"
        char_dir.mkdir(exist_ok=True)
        for idx, (char, pred) in enumerate(
            zip(seg.characters, result.selected_attempt.predictions)
        ):
            label = pred.label if pred.status == "OK" else "UNK"
            write_image(
                char_dir / f"char_{idx:02d}_{label}_{pred.score:.2f}.png",
                char.image,
            )
            if pred.normalized_image is not None:
                write_image(
                    char_dir / f"char_{idx:02d}_{label}_normalized.png",
                    pred.normalized_image,
                )
        strip = make_character_strip(
            result.selected_attempt.predictions, seg.characters
        )
        write_image(out / "14_character_strip.png", strip)
    # JSON kết quả (không chứa mảng ảnh)
    with (out / "result.json").open("w", encoding="utf-8") as fh:
        json.dump(result.as_dict(), fh, ensure_ascii=False, indent=2)
    return out


def read_debug_images(result: RecognitionResult) -> Dict[str, np.ndarray]:
    return result.debug_images()
