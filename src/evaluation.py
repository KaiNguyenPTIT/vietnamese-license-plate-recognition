"""Đánh giá hệ thống trên bộ dữ liệu có nhãn và xuất CSV.

Các chỉ số:
    - Plate Detection Rate (PDR) theo IoU với bounding box nhãn (nếu có).
    - Detection Precision / Recall / F1 (ảnh không biển số được tính là âm).
    - Character Segmentation Accuracy (CSA): nếu nhãn có ``char_boxes`` thì
      ghép IoU từng ký tự; nếu không, dùng proxy cấu trúc (đúng số lượng/không
      âm thầm bỏ sót) và ghi rõ trong báo cáo.
    - Character Accuracy (CA) bằng căn chỉnh Levenshtein.
    - Exact Plate Accuracy (EPA).
    - Average Processing Time theo từng công đoạn.
    - Failure/Rejection Rate.

Không có số liệu nào được tạo thủ công: mọi con số đều tính từ kết quả chạy
thực tế của pipeline trên ảnh và nhãn đầu vào.
"""

from __future__ import annotations

import csv
import json
import statistics
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

from .config import Config
from .io_utils import bbox_iou
from .pipeline import LicensePlateRecognizer, RecognitionResult
from .postprocessing import normalize_ground_truth


@dataclass
class LabelRow:
    image_name: str
    ground_truth: str
    plate_type: str = ""
    split: str = ""
    condition: str = ""
    notes: str = ""
    bbox: Optional[Tuple[float, float, float, float]] = None
    char_boxes: List[Tuple[float, float, float, float]] = field(
        default_factory=list
    )


@dataclass
class ImageEvaluation:
    image_name: str
    ground_truth: str
    condition: str
    status: str
    detected_text: str
    has_gt_plate: bool
    predicted_plate: bool
    detection_correct: Optional[bool]
    detection_iou: Optional[float]
    exact_match: Optional[bool]
    char_correct: int = 0
    char_substitutions: int = 0
    char_insertions: int = 0
    char_deletions: int = 0
    char_accuracy: Optional[float] = None
    seg_gt_count: int = 0
    seg_pred_count: int = 0
    seg_matched: int = 0
    segmentation_accuracy: Optional[float] = None
    segmentation_method: str = ""
    format_valid: bool = False
    mean_score: float = 0.0
    total_time_ms: float = 0.0
    timings: Dict[str, float] = field(default_factory=dict)
    message: str = ""

    def as_csv_row(self) -> Dict[str, Any]:
        return {
            "image_name": self.image_name,
            "ground_truth": self.ground_truth,
            "condition": self.condition,
            "status": self.status,
            "detected_text": self.detected_text,
            "has_gt_plate": int(self.has_gt_plate),
            "predicted_plate": int(self.predicted_plate),
            "detection_correct": ""
            if self.detection_correct is None
            else int(self.detection_correct),
            "detection_iou": ""
            if self.detection_iou is None
            else round(self.detection_iou, 4),
            "exact_match": "" if self.exact_match is None else int(self.exact_match),
            "char_correct": self.char_correct,
            "char_substitutions": self.char_substitutions,
            "char_insertions": self.char_insertions,
            "char_deletions": self.char_deletions,
            "char_accuracy": ""
            if self.char_accuracy is None
            else round(self.char_accuracy, 4),
            "seg_gt_count": self.seg_gt_count,
            "seg_pred_count": self.seg_pred_count,
            "seg_matched": self.seg_matched,
            "segmentation_accuracy": ""
            if self.segmentation_accuracy is None
            else round(self.segmentation_accuracy, 4),
            "segmentation_method": self.segmentation_method,
            "format_valid": int(self.format_valid),
            "mean_score": round(self.mean_score, 4),
            "total_time_ms": round(self.total_time_ms, 3),
            "preprocess_ms": round(self.timings.get("preprocess", 0.0), 3),
            "detection_ms": round(self.timings.get("detection", 0.0), 3),
            "rectification_ms": round(self.timings.get("rectification", 0.0), 3),
            "segmentation_ms": round(self.timings.get("segmentation", 0.0), 3),
            "recognition_ms": round(self.timings.get("recognition", 0.0), 3),
            "postprocessing_ms": round(self.timings.get("postprocessing", 0.0), 3),
            "message": self.message,
        }


# ----------------------------------------------------------------------
# Đọc nhãn
# ----------------------------------------------------------------------
def _parse_bbox(row: Dict[str, str]) -> Optional[Tuple[float, float, float, float]]:
    keys_sets = [
        ("x1", "y1", "x2", "y2"),
        ("plate_x1", "plate_y1", "plate_x2", "plate_y2"),
        ("bbox_x1", "bbox_y1", "bbox_x2", "bbox_y2"),
    ]
    for keys in keys_sets:
        if all(k in row and str(row[k]).strip() != "" for k in keys):
            try:
                vals = tuple(float(row[k]) for k in keys)
                if vals[2] > vals[0] and vals[3] > vals[1]:
                    return vals  # type: ignore[return-value]
            except ValueError:
                return None
    return None


def _parse_char_boxes(value: str) -> List[Tuple[float, float, float, float]]:
    if not value:
        return []
    try:
        data = json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return []
    boxes: List[Tuple[float, float, float, float]] = []
    if isinstance(data, list):
        for item in data:
            if isinstance(item, (list, tuple)) and len(item) == 4:
                try:
                    box = tuple(float(v) for v in item)
                    if box[2] > box[0] and box[3] > box[1]:
                        boxes.append(box)  # type: ignore[arg-type]
                except (TypeError, ValueError):
                    continue
    return boxes


def load_labels(path: str | Path) -> List[LabelRow]:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Không tìm thấy file nhãn: {p}")
    rows: List[LabelRow] = []
    with p.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames is None:
            raise ValueError("File nhãn rỗng hoặc thiếu header.")
        required = {"image_name", "ground_truth"}
        missing = required - set(reader.fieldnames)
        if missing:
            raise ValueError(f"File nhãn thiếu cột: {sorted(missing)}")
        for raw in reader:
            name = (raw.get("image_name") or "").strip()
            if not name:
                continue
            rows.append(
                LabelRow(
                    image_name=name,
                    ground_truth=(raw.get("ground_truth") or "").strip(),
                    plate_type=(raw.get("plate_type") or "").strip(),
                    split=(raw.get("split") or "").strip(),
                    condition=(raw.get("condition") or "").strip(),
                    notes=(raw.get("notes") or "").strip(),
                    bbox=_parse_bbox(raw),
                    char_boxes=_parse_char_boxes(
                        (raw.get("char_boxes") or "").strip()
                    ),
                )
            )
    return rows


# ----------------------------------------------------------------------
# Căn chỉnh chuỗi
# ----------------------------------------------------------------------
def align_strings(prediction: str, ground_truth: str) -> Dict[str, int]:
    """Căn chỉnh Levenshtein, trả về số match/substitution/insertion/deletion."""
    pred = prediction or ""
    gt = ground_truth or ""
    m, n = len(pred), len(gt)
    dp = np.zeros((m + 1, n + 1), dtype=np.int32)
    for i in range(m + 1):
        dp[i][0] = i
    for j in range(n + 1):
        dp[0][j] = j
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            cost = 0 if pred[i - 1] == gt[j - 1] else 1
            dp[i, j] = min(
                dp[i - 1, j - 1] + cost,
                dp[i - 1, j] + 1,
                dp[i, j - 1] + 1,
            )
    i, j = m, n
    matches = subs = ins = dels = 0
    while i > 0 or j > 0:
        if i > 0 and j > 0:
            cost = 0 if pred[i - 1] == gt[j - 1] else 1
            if dp[i, j] == dp[i - 1, j - 1] + cost:
                if cost == 0:
                    matches += 1
                else:
                    subs += 1
                i -= 1
                j -= 1
                continue
        if i > 0 and dp[i, j] == dp[i - 1, j] + 1:
            ins += 1
            i -= 1
            continue
        dels += 1
        j -= 1
    return {
        "matches": matches,
        "substitutions": subs,
        "insertions": ins,
        "deletions": dels,
    }


def _match_boxes_iou(
    pred_boxes: Sequence[Sequence[float]],
    gt_boxes: Sequence[Sequence[float]],
    threshold: float = 0.5,
) -> int:
    """Ghép tham lam các box dự đoán với box nhãn theo IoU."""
    if not pred_boxes or not gt_boxes:
        return 0
    pairs: List[Tuple[float, int, int]] = []
    for pi, pb in enumerate(pred_boxes):
        for gi, gb in enumerate(gt_boxes):
            iou = bbox_iou(pb, gb)
            if iou >= threshold:
                pairs.append((iou, pi, gi))
    pairs.sort(reverse=True)
    used_p, used_g = set(), set()
    matched = 0
    for _, pi, gi in pairs:
        if pi in used_p or gi in used_g:
            continue
        used_p.add(pi)
        used_g.add(gi)
        matched += 1
    return matched


# ----------------------------------------------------------------------
# Chạy đánh giá
# ----------------------------------------------------------------------
def evaluate_row(
    result: RecognitionResult,
    label: LabelRow,
    config: Config,
) -> ImageEvaluation:
    gt = normalize_ground_truth(label.ground_truth)
    has_gt_plate = bool(gt)
    pred_text = result.normalized_text if result.normalized_text else ""
    predicted_plate = result.bbox_original is not None

    detection_correct: Optional[bool] = None
    detection_iou: Optional[float] = None
    if has_gt_plate:
        if label.bbox is not None:
            if result.bbox_original is not None:
                detection_iou = bbox_iou(result.bbox_original, label.bbox)
                detection_correct = detection_iou >= config.evaluation.iou_threshold
            else:
                detection_iou = 0.0
                detection_correct = False
        else:
            detection_correct = (
                predicted_plate
                and result.status
                not in {"PLATE_NOT_FOUND", "INVALID_IMAGE", "CONFIG_ERROR"}
            )
    else:
        detection_correct = None

    exact_match: Optional[bool] = None
    char_stats = {
        "matches": 0,
        "substitutions": 0,
        "insertions": 0,
        "deletions": 0,
    }
    char_accuracy: Optional[float] = None
    if has_gt_plate:
        exact_match = pred_text == gt
        char_stats = align_strings(pred_text, gt)
        denominator = (
            char_stats["matches"]
            + char_stats["substitutions"]
            + char_stats["insertions"]
            + char_stats["deletions"]
        )
        char_accuracy = (
            char_stats["matches"] / denominator if denominator > 0 else 0.0
        )

    # Segmentation accuracy
    seg_gt_count = len(gt) if has_gt_plate else 0
    seg_pred_count = len(result.char_boxes_original)
    seg_accuracy: Optional[float] = None
    seg_method = ""
    seg_matched = 0
    if has_gt_plate and label.char_boxes:
        pred_boxes = [c["bbox_original"] for c in result.char_boxes_original]
        seg_matched = _match_boxes_iou(
            pred_boxes, label.char_boxes, config.evaluation.iou_threshold
        )
        seg_accuracy = seg_matched / max(1, len(label.char_boxes))
        seg_method = "char_box_iou"
    elif has_gt_plate:
        denom = max(seg_gt_count, seg_pred_count)
        if denom > 0:
            seg_accuracy = 1.0 - abs(seg_gt_count - seg_pred_count) / denom
            seg_method = "count_proxy"
    text = result.text
    return ImageEvaluation(
        image_name=label.image_name,
        ground_truth=gt,
        condition=label.condition,
        status=result.status,
        detected_text=result.detected_text,
        has_gt_plate=has_gt_plate,
        predicted_plate=predicted_plate,
        detection_correct=detection_correct,
        detection_iou=detection_iou,
        exact_match=exact_match,
        char_correct=char_stats["matches"],
        char_substitutions=char_stats["substitutions"],
        char_insertions=char_stats["insertions"],
        char_deletions=char_stats["deletions"],
        char_accuracy=char_accuracy,
        seg_gt_count=seg_gt_count,
        seg_pred_count=seg_pred_count,
        seg_matched=seg_matched,
        segmentation_accuracy=seg_accuracy,
        segmentation_method=seg_method,
        format_valid=text.validation.is_valid if text else False,
        mean_score=text.mean_score if text else 0.0,
        total_time_ms=result.total_time_ms,
        timings=dict(result.timings_ms),
        message=result.message,
    )


def _mean(values: Iterable[float]) -> Optional[float]:
    vals = [v for v in values if v is not None and np.isfinite(v)]
    return float(statistics.fmean(vals)) if vals else None


def compute_summary(rows: Sequence[ImageEvaluation]) -> Dict[str, Any]:
    total = len(rows)
    with_plate = [r for r in rows if r.has_gt_plate]
    without_plate = [r for r in rows if not r.has_gt_plate]
    processed = [r for r in rows if r.status != "INVALID_IMAGE"]

    pdr = (
        sum(1 for r in with_plate if r.detection_correct)
        / len(with_plate)
        if with_plate
        else None
    )
    tp = sum(
        1
        for r in with_plate
        if r.detection_correct and r.predicted_plate
    )
    fn = len(with_plate) - tp
    fp = sum(1 for r in without_plate if r.predicted_plate)
    tn = len(without_plate) - fp
    precision = tp / (tp + fp) if (tp + fp) > 0 else None
    recall = tp / (tp + fn) if (tp + fn) > 0 else None
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision is not None and recall is not None and (precision + recall) > 0
        else None
    )

    char_correct = sum(r.char_correct for r in with_plate)
    char_sub = sum(r.char_substitutions for r in with_plate)
    char_ins = sum(r.char_insertions for r in with_plate)
    char_del = sum(r.char_deletions for r in with_plate)
    alignment_len = char_correct + char_sub + char_ins + char_del
    gt_char_total = sum(len(r.ground_truth) for r in with_plate)
    ca = char_correct / alignment_len if alignment_len > 0 else None
    ca_gt = char_correct / gt_char_total if gt_char_total > 0 else None

    exact_matches = sum(1 for r in with_plate if r.exact_match is True)
    epa = exact_matches / len(with_plate) if with_plate else None

    csa_values = [r.segmentation_accuracy for r in with_plate if r.segmentation_accuracy is not None]
    csa = _mean(csa_values)
    csa_methods = sorted({r.segmentation_method for r in with_plate if r.segmentation_method})

    rejected_statuses = {
        "LOW_CONFIDENCE",
        "PLATE_NOT_FOUND",
        "INVALID_IMAGE",
        "CONFIG_ERROR",
    }
    failed = sum(1 for r in rows if r.status in rejected_statuses)
    failure_rate = failed / total if total else None
    success_count = sum(1 for r in rows if r.status == "SUCCESS")
    success_rate = success_count / total if total else None

    stage_names = [
        "preprocess",
        "detection",
        "rectification",
        "segmentation",
        "recognition",
        "postprocessing",
    ]
    stage_means: Dict[str, Optional[float]] = {}
    for stage in stage_names:
        stage_means[stage] = _mean(
            r.timings.get(stage) for r in processed if r.timings.get(stage) is not None
        )
    avg_time = _mean(r.total_time_ms for r in processed)
    status_counts: Dict[str, int] = {}
    for r in rows:
        status_counts[r.status] = status_counts.get(r.status, 0) + 1

    return {
        "num_images": total,
        "num_with_plate": len(with_plate),
        "num_without_plate": len(without_plate),
        "num_invalid": sum(1 for r in rows if r.status == "INVALID_IMAGE"),
        "plate_detection_rate": pdr,
        "detection_precision": precision,
        "detection_recall": recall,
        "detection_f1": f1,
        "detection_true_positive": tp,
        "detection_false_positive": fp,
        "detection_false_negative": fn,
        "detection_true_negative": tn,
        "character_segmentation_accuracy": csa,
        "character_segmentation_method": csa_methods,
        "character_accuracy": ca,
        "character_accuracy_over_gt": ca_gt,
        "character_correct": char_correct,
        "character_substitutions": char_sub,
        "character_insertions": char_ins,
        "character_deletions": char_del,
        "ground_truth_characters": gt_char_total,
        "exact_plate_accuracy": epa,
        "exact_plate_matches": exact_matches,
        "average_processing_time_ms": avg_time,
        "stage_average_time_ms": stage_means,
        "failure_rate": failure_rate,
        "success_rate": success_rate,
        "status_counts": status_counts,
        "conditions": sorted({r.condition for r in rows if r.condition}),
    }


def format_summary_text(summary: Dict[str, Any]) -> str:
    def pct(value: Optional[float]) -> str:
        return "N/A" if value is None else f"{value * 100:.2f}%"

    def ms(value: Optional[float]) -> str:
        return "N/A" if value is None else f"{value:.2f} ms"

    lines = [
        "===== KẾT QUẢ ĐÁNH GIÁ =====",
        f"Số ảnh: {summary['num_images']} "
        f"(có biển: {summary['num_with_plate']}, "
        f"không biển: {summary['num_without_plate']}, "
        f"ảnh lỗi: {summary['num_invalid']})",
        f"Plate Detection Rate: {pct(summary['plate_detection_rate'])}",
        f"Detection Precision: {pct(summary['detection_precision'])} "
        f"(TP={summary['detection_true_positive']}, "
        f"FP={summary['detection_false_positive']}, "
        f"FN={summary['detection_false_negative']}, "
        f"TN={summary['detection_true_negative']})",
        f"Detection Recall: {pct(summary['detection_recall'])}",
        f"Character Segmentation Accuracy: "
        f"{pct(summary['character_segmentation_accuracy'])} "
        f"({', '.join(summary['character_segmentation_method']) or 'n/a'})",
        f"Character Accuracy: {pct(summary['character_accuracy'])} "
        f"(trên tổng ký tự nhãn: {pct(summary['character_accuracy_over_gt'])})",
        f"Exact Plate Accuracy: {pct(summary['exact_plate_accuracy'])} "
        f"({summary['exact_plate_matches']}/{summary['num_with_plate']})",
        f"Thời gian trung bình: {ms(summary['average_processing_time_ms'])}",
    ]
    for stage, value in summary["stage_average_time_ms"].items():
        lines.append(f"  - {stage}: {ms(value)}")
    lines.append(f"Failure/Rejection Rate: {pct(summary['failure_rate'])}")
    lines.append(f"Success Rate: {pct(summary['success_rate'])}")
    lines.append(f"Trạng thái: {summary['status_counts']}")
    return "\n".join(lines)


def run_evaluation(
    recognizer: LicensePlateRecognizer,
    labels: Sequence[LabelRow],
    image_dir: str | Path,
    config: Config,
    split: Optional[str] = None,
    progress: Optional[Callable[[int, int, str], None]] = None,
    stop_flag: Optional[Callable[[], bool]] = None,
) -> Tuple[List[ImageEvaluation], Dict[str, Any]]:
    image_dir = Path(image_dir)
    selected = [
        row
        for row in labels
        if not split or not row.split or row.split.lower() == split.lower()
    ]
    if split:
        selected = [row for row in selected if row.split.lower() == split.lower()]
    results: List[ImageEvaluation] = []
    total = len(selected)
    t_start = time.perf_counter()
    for idx, label in enumerate(selected, start=1):
        if stop_flag and stop_flag():
            break
        path = image_dir / label.image_name
        result = recognizer.recognize(path)
        results.append(evaluate_row(result, label, config))
        if progress:
            progress(idx, total, label.image_name)
    summary = compute_summary(results)
    summary["split"] = split or "all"
    summary["image_dir"] = str(image_dir)
    summary["elapsed_seconds"] = time.perf_counter() - t_start
    return results, summary


def write_evaluation_csv(
    rows: Sequence[ImageEvaluation], path: str | Path
) -> Path:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].as_csv_row().keys()) if rows else [
        "image_name",
        "ground_truth",
        "condition",
        "status",
        "detected_text",
    ]
    with out.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row.as_csv_row())
    return out


def write_summary_json(summary: Dict[str, Any], path: str | Path) -> Path:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=2)
    return out


def write_summary_markdown(
    summary: Dict[str, Any], path: str | Path
) -> Path:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    text = format_summary_text(summary)
    with out.open("w", encoding="utf-8") as fh:
        fh.write("# Kết quả đánh giá\n\n")
        fh.write("```\n" + text + "\n```\n")
    return out
