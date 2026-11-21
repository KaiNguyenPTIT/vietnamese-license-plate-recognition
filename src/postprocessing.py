"""Hậu xử lý chuỗi và kiểm tra định dạng biển số.

Nguyên tắc quan trọng: module này KHÔNG tự sửa ký tự, không đoán ký tự thiếu
và không đổi ký tự chỉ để chuỗi trông giống một biển số hợp lệ hơn. Nó chỉ ghép
chuỗi, đánh giá độ tin cậy và báo cảnh báo định dạng.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from typing import Dict, List, Optional, Sequence

from .character_recognition import CharacterPrediction
from .config import Config


@dataclass
class ValidationResult:
    is_valid: bool
    normalized_text: str
    issues: List[str] = field(default_factory=list)
    checks: Dict[str, bool] = field(default_factory=dict)
    matched_pattern: Optional[str] = None


@dataclass
class PlateTextResult:
    raw_text: str
    normalized_text: str
    formatted_text: str
    validation: ValidationResult
    mean_score: float
    min_score: float
    mean_margin: float
    confident_ratio: float
    char_count: int
    unknown_count: int
    has_unknown: bool
    status: str
    message: str
    warnings: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, object]:
        return {
            "raw_text": self.raw_text,
            "normalized_text": self.normalized_text,
            "formatted_text": self.formatted_text,
            "validation": {
                "is_valid": self.validation.is_valid,
                "issues": list(self.validation.issues),
                "checks": dict(self.validation.checks),
                "matched_pattern": self.validation.matched_pattern,
            },
            "mean_score": round(self.mean_score, 4),
            "min_score": round(self.min_score, 4),
            "mean_margin": round(self.mean_margin, 4),
            "confident_ratio": round(self.confident_ratio, 4),
            "char_count": self.char_count,
            "unknown_count": self.unknown_count,
            "status": self.status,
            "message": self.message,
            "warnings": list(self.warnings),
        }


def normalize_ground_truth(text: str) -> str:
    """Chuẩn hóa nhãn: chữ hoa, bỏ dấu phân cách và khoảng trắng."""
    if text is None:
        return ""
    return re.sub(r"[^A-Z0-9]", "", str(text).upper())


def compact_from_predictions(predictions: Sequence[CharacterPrediction]) -> str:
    """Ghép chuỗi theo thứ tự đọc, giữ nguyên vị trí chưa xác định bằng '?'."""
    chars: List[str] = []
    for pred in predictions:
        if pred.status in {"UNKNOWN", "AMBIGUOUS", "EMPTY"}:
            chars.append("?")
        else:
            chars.append(pred.label.upper())
    return "".join(chars)


def _label_type(label: str) -> str:
    if not label or len(label) != 1:
        return "?"
    if label.isdigit():
        return "D"
    if label.isalpha():
        return "L"
    return "?"


def infer_position_types(
    predictions: Sequence[CharacterPrediction],
) -> Optional[List[str]]:
    """Suy ra kiểu ký tự kỳ vọng (D=chữ số, L=chữ cái) theo thứ tự đọc.

    Cấu trúc chung của biển Việt Nam là 2 chữ số tỉnh, 1-2 chữ cái series,
    sau đó 4-6 chữ số. Với biển hai dòng, thứ tự đọc vẫn là dòng trên rồi
    dòng dưới, nên chỉ cần độ dài chuỗi là đủ để suy ra kiểu từng vị trí.
    """
    total = len(predictions)
    if total < 7 or total > 10:
        return None
    candidates: List[tuple[float, int, List[str]]] = []
    for series_len in (1, 2):
        digit_count = total - 2 - series_len
        if not 4 <= digit_count <= 6:
            continue
        types = ["D", "D"] + ["L"] * series_len + ["D"] * digit_count
        type_score = 0.0
        for prediction, expected in zip(predictions, types):
            actual = _label_type(prediction.label)
            if actual == expected:
                type_score += 1.0
            elif actual != "?":
                type_score -= 0.5
        # Khi điểm bằng nhau, ưu tiên series 1 chữ cái vì phổ biến hơn.
        candidates.append((type_score, -series_len, types))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return candidates[0][2]


def _resolve_prediction(
    prediction: CharacterPrediction, expected: str, config: Config
) -> CharacterPrediction:
    """Chọn lại trong các ứng viên template cùng kiểu với vị trí hiện tại."""
    if prediction.status == "OK" and _label_type(prediction.label) == expected:
        return prediction
    ranked = prediction.ranked or []
    if not ranked:
        return prediction
    valid = [
        (label, float(score))
        for label, score in ranked
        if _label_type(label) == expected
    ]
    if not valid:
        return prediction
    valid.sort(key=lambda item: item[1], reverse=True)
    best_label, best_score = valid[0]
    if best_score < config.recognition.score_threshold:
        return prediction
    second_valid = valid[1][1] if len(valid) > 1 else None
    # Hai ứng viên cùng kiểu vẫn quá sát nhau: cấu trúc biển không giúp phân
    # biệt, nên tiếp tục từ chối thay vì chọn bừa. Ngưỡng ở đây thấp hơn
    # min_margin chung vì vị trí đã được cấu trúc biển xác nhận kiểu ký tự.
    if (
        second_valid is not None
        and best_score - second_valid
        < config.postprocessing.position_min_margin
    ):
        return prediction
    if prediction.status == "OK":
        # Ký tự hiện tại sai kiểu nhưng điểm cao hơn hẳn ứng viên đúng kiểu:
        # có thể biển thuộc định dạng đặc biệt, không ép đổi.
        if (
            prediction.score - best_score
            > config.postprocessing.position_resolve_max_drop
        ):
            return prediction
    second_label = valid[1][0] if len(valid) > 1 else prediction.second_label
    second_score = valid[1][1] if len(valid) > 1 else prediction.second_score
    margin = best_score - second_valid if second_valid is not None else prediction.margin
    return replace(
        prediction,
        label=best_label,
        status="OK",
        score=best_score,
        margin=margin,
        best_label=best_label,
        second_label=second_label,
        second_score=second_score,
        message=(
            f"Ràng buộc vị trí {expected} chọn '{best_label}' trong danh sách "
            "template đã chấm điểm; không tạo ký tự mới."
        ),
    )


def resolve_position_constraints(
    predictions: Sequence[CharacterPrediction], config: Config
) -> List[CharacterPrediction]:
    """Rerank ký tự theo cấu trúc biển, chỉ dùng ứng viên template có sẵn."""
    if (
        not config.postprocessing.position_constraints
        or not predictions
    ):
        return list(predictions)
    types = infer_position_types(predictions)
    if types is None:
        return list(predictions)
    return [
        _resolve_prediction(prediction, expected, config)
        for prediction, expected in zip(predictions, types)
    ]


def format_plate_text(compact: str, config: Config) -> str:
    """Định dạng hiển thị (ví dụ 51F12345 -> 51F-123.45)."""
    m = re.fullmatch(r"(\d{2})([A-Z]{1,2})(\d{4,5})", compact)
    if not m:
        return compact
    province, series, numbers = m.groups()
    prefix = f"{province}{series}"
    if len(numbers) == 5:
        return f"{prefix}-{numbers[:3]}.{numbers[3:]}"
    return f"{prefix}-{numbers}"


def validate_format(text: str, config: Config) -> ValidationResult:
    """Kiểm tra chuỗi theo quy tắc cấu hình, không sửa chuỗi."""
    pc = config.postprocessing
    normalized = re.sub(r"[^A-Z0-9?]", "", str(text).upper())
    issues: List[str] = []
    checks: Dict[str, bool] = {}
    matched: Optional[str] = None

    has_unknown = "?" in normalized
    checks["no_unknown"] = not has_unknown
    if has_unknown:
        issues.append(
            "Chuỗi còn ký tự chưa xác định (?); không tự đoán để lấp chỗ trống."
        )

    checks["length"] = 7 <= len(normalized) <= 10
    if normalized and not checks["length"]:
        issues.append(
            f"Độ dài chuỗi {len(normalized)} không nằm trong khoảng 7-10."
        )

    checks["alnum"] = bool(re.fullmatch(r"[A-Z0-9?]*", normalized))
    if not checks["alnum"]:
        issues.append("Chuỗi chứa ký tự không thuộc tập chữ số/chữ cái.")

    # Khớp với ít nhất một pattern đã cấu hình
    pattern_ok = False
    if normalized and "?" not in normalized:
        for pattern in pc.patterns:
            if re.fullmatch(pattern, normalized):
                pattern_ok = True
                matched = pattern
                break
    checks["pattern"] = pattern_ok
    if normalized and not pattern_ok:
        issues.append(
            "Chuỗi không khớp quy tắc định dạng: 2 số tỉnh + 1-2 chữ series "
            "+ 4-6 số."
        )

    # Kiểm tra series có nằm trong tập chữ cái hợp lệ của Việt Nam
    series_ok = True
    if normalized and len(normalized) >= 3 and "?" not in normalized[:4]:
        m = re.match(r"^(\d{2})([A-Z]+)", normalized)
        if m:
            series = m.group(2)
            allowed = getattr(pc, "allowed_series_letters", "")
            if allowed and any(ch not in allowed for ch in series):
                series_ok = False
                issues.append(
                    f"Series '{series}' chứa chữ cái ngoài tập hợp lệ {allowed}."
                )
    checks["series_letters"] = series_ok

    # Mã tỉnh: 2 chữ số, 01-99
    province_ok = True
    if normalized and len(normalized) >= 2 and normalized[:2].isdigit():
        code = int(normalized[:2])
        if not (1 <= code <= 99):
            province_ok = False
            issues.append(f"Mã tỉnh {normalized[:2]} không hợp lệ (01-99).")
    checks["province_code"] = province_ok

    is_valid = bool(normalized) and pattern_ok and series_ok and province_ok
    return ValidationResult(
        is_valid=is_valid,
        normalized_text=normalized,
        issues=issues,
        checks=checks,
        matched_pattern=matched,
    )


def decide_status(
    predictions: Sequence[CharacterPrediction],
    validation: ValidationResult,
    segmentation_status: str,
    config: Config,
) -> str:
    """Quyết định trạng thái toàn biển theo thứ tự ưu tiên của đặc tả."""
    if not predictions:
        return "LOW_CONFIDENCE"
    if segmentation_status != "OK":
        return "LOW_CONFIDENCE"
    pc = config.postprocessing
    scores = [p.score for p in predictions]
    mean_score = float(sum(scores) / len(scores)) if scores else 0.0
    min_score = float(min(scores)) if scores else 0.0
    confident = sum(1 for p in predictions if p.status == "OK")
    ratio = confident / max(1, len(predictions))
    if any(p.status in {"UNKNOWN", "AMBIGUOUS", "EMPTY"} for p in predictions):
        return "LOW_CONFIDENCE"
    if not validation.is_valid:
        return "FORMAT_WARNING"
    if (
        mean_score < pc.min_mean_confidence
        or min_score < pc.min_char_confidence
        or ratio < pc.min_confident_ratio
    ):
        return "LOW_CONFIDENCE"
    return "SUCCESS"


def build_text_result(
    predictions: Sequence[CharacterPrediction],
    segmentation_status: str,
    config: Config,
) -> PlateTextResult:
    """Ghép chuỗi, kiểm tra định dạng và quyết định trạng thái."""
    raw = compact_from_predictions(predictions)
    validation = validate_format(raw, config)
    formatted = (
        format_plate_text(validation.normalized_text, config)
        if validation.is_valid
        else raw
    )
    scores = [p.score for p in predictions]
    margins = [p.margin for p in predictions]
    mean_score = float(sum(scores) / len(scores)) if scores else 0.0
    min_score = float(min(scores)) if scores else 0.0
    mean_margin = float(sum(margins) / len(margins)) if margins else 0.0
    confident = sum(1 for p in predictions if p.status == "OK")
    ratio = confident / max(1, len(predictions))
    unknown_count = sum(
        1 for p in predictions if p.status in {"UNKNOWN", "AMBIGUOUS", "EMPTY"}
    )
    status = decide_status(predictions, validation, segmentation_status, config)
    warnings: List[str] = []
    warnings.extend(validation.issues)

    if status == "SUCCESS":
        message = "Nhận dạng thành công và chuỗi khớp quy tắc định dạng."
    elif status == "FORMAT_WARNING":
        message = (
            "Đã nhận dạng được chuỗi nhưng chuỗi không khớp quy tắc định dạng. "
            "Kết quả chỉ mang tính tham khảo, không tự sửa ký tự."
        )
    elif status == "LOW_CONFIDENCE":
        if unknown_count:
            message = (
                f"Có {unknown_count} ký tự chưa đủ tin cậy. Hệ thống từ chối "
                "khẳng định thay vì đoán ký tự."
            )
        elif segmentation_status != "OK":
            message = (
                "Phân đoạn ký tự không đáng tin cậy (số lượng/hình học bất thường)."
            )
        else:
            message = "Điểm nhận dạng trung bình hoặc điểm thấp nhất chưa đạt ngưỡng."
    else:
        message = "Không thể quyết định trạng thái."
    return PlateTextResult(
        raw_text=raw,
        normalized_text=validation.normalized_text,
        formatted_text=formatted,
        validation=validation,
        mean_score=mean_score,
        min_score=min_score,
        mean_margin=mean_margin,
        confident_ratio=ratio,
        char_count=len(predictions),
        unknown_count=unknown_count,
        has_unknown="?" in raw,
        status=status,
        message=message,
        warnings=warnings,
    )
