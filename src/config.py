"""Cấu hình tập trung cho toàn bộ hệ thống.

Toàn bộ tham số thuật toán được đọc từ ``config.yaml`` và ánh xạ vào các
dataclass trong module này. Có thể ghi đè từng tham số bằng khóa dạng
``section.key`` khi chạy thực nghiệm, ví dụ::

    load_config(overrides={"preprocessing.blur_method": "median"})
"""

from __future__ import annotations

import copy
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]


@dataclass
class ProjectConfig:
    name: str = "Nhan dang bien so xe Viet Nam"
    seed: int = 42


@dataclass
class PathsConfig:
    templates_dir: str = "data/templates"
    samples_dir: str = "data/samples"
    labels_file: str = "data/labels.csv"
    results_dir: str = "results"


@dataclass
class ImageConfig:
    max_side: int = 1600
    min_side: int = 40
    allowed_extensions: List[str] = field(
        default_factory=lambda: [".jpg", ".jpeg", ".png", ".webp"]
    )


@dataclass
class PreprocessingConfig:
    blur_method: str = "gaussian"
    gaussian_kernel: int = 5
    median_kernel: int = 5
    use_clahe: bool = False
    clahe_clip_limit: float = 2.0
    clahe_tile_grid: Tuple[int, int] = (8, 8)
    canny_low: int = 60
    canny_high: int = 180
    auto_canny: bool = False
    threshold_method: str = "otsu"
    adaptive_block_size: int = 11
    adaptive_c: int = 2


@dataclass
class DetectionWeights:
    ratio: float = 0.35
    area: float = 0.15
    edge: float = 0.30
    fill: float = 0.15

    def normalized(self) -> "DetectionWeights":
        total = self.ratio + self.area + self.edge + self.fill
        if total <= 0:
            return DetectionWeights()
        return DetectionWeights(
            ratio=self.ratio / total,
            area=self.area / total,
            edge=self.edge / total,
            fill=self.fill / total,
        )


@dataclass
class DetectionConfig:
    close_kernel: Tuple[int, int] = (17, 3)
    extra_close_kernels: List[Tuple[int, int]] = field(
        default_factory=lambda: [(25, 5), (15, 7)]
    )
    min_area_ratio: float = 0.0008
    # Biển chụp cận cảnh có thể chiếm gần như toàn bộ ảnh. Ngưỡng cao hơn
    # giúp không loại mất các ảnh biển lớn; bước chấm điểm vẫn kiểm soát
    # tỷ lệ, mật độ cạnh và bằng chứng vùng chữ.
    max_area_ratio: float = 0.95
    min_ratio: float = 1.10
    max_ratio: float = 7.0
    ratio_targets: List[float] = field(default_factory=lambda: [4.6, 1.45])
    ratio_tolerance: float = 0.75
    ideal_area_ratio: float = 0.05
    area_sigma: float = 1.7
    edge_density_min: float = 0.02
    edge_density_ideal: float = 0.12
    edge_density_max: float = 0.40
    fill_ratio_min: float = 0.30
    weights: DetectionWeights = field(default_factory=DetectionWeights)
    text_likeness_weight: float = 0.20
    require_text_evidence: bool = True
    min_text_likeness: float = 0.15
    min_score: float = 0.45
    top_k: int = 5
    padding_ratio: float = 0.03
    merge_iou: float = 0.45
    max_candidates: int = 25
    # Ứng viên cụm chữ thường cắt sát các ký tự nên OCR tốt nhưng IoU với
    # biển thật thấp. Khi một ứng viên hình học bao trọn cụm chữ, dùng hộp
    # hình học làm hộp báo cáo (không đổi vùng cắt dùng cho OCR).
    text_bbox_hint: bool = True
    text_bbox_hint_min_containment: float = 0.80
    text_bbox_hint_max_area_ratio: float = 4.0
    text_bbox_hint_min_score: float = 0.50


@dataclass
class RectificationConfig:
    padding_ratio: float = 0.10
    # Padding dọc tính theo chiều rộng biển: biển rất rộng nhưng thấp, nếu
    # chỉ pad theo chiều cao thì các góc của biển nghiêng dễ bị cắt mất.
    vertical_padding_ratio: float = 0.06
    approx_epsilon_ratio: float = 0.02
    min_quad_area_ratio: float = 0.45
    output_min_width: int = 60
    output_min_height: int = 20
    fallback_deskew: bool = True
    deskew_min_angle: float = 2.5
    deskew_max_angle: float = 18.0
    max_output_ratio: float = 8.0


@dataclass
class SegmentationConfig:
    plate_width: int = 640
    threshold_method: str = "auto"
    adaptive_block_size: int = 21
    adaptive_c: int = 5
    blur_kernel: int = 3
    use_clahe: bool = True
    clahe_clip_limit: float = 2.0
    clahe_tile_grid: Tuple[int, int] = (8, 8)
    border_margin_ratio: float = 0.015
    close_kernel: Tuple[int, int] = (2, 2)
    min_char_height_ratio: float = 0.42
    max_char_height_ratio: float = 1.02
    min_char_width_ratio: float = 0.008
    max_char_width_ratio: float = 0.24
    min_char_area_ratio: float = 0.0003
    min_fill_ratio: float = 0.08
    row_min_height_ratio: float = 0.17
    row_gap_min_ratio: float = 0.012
    row_projection_threshold: float = 0.02
    # Tách dòng bằng connected components là phương án dự phòng khi
    # projection profile gộp hai dòng sát nhau (biển chụp cận cảnh).
    component_row_fallback: bool = True
    adaptive_block_max: int = 71
    split_wide: bool = True
    split_valley_ratio: float = 0.30
    merge_gap_px: int = 2
    # Biển chuẩn 7-9 ký tự. Biển đặc biệt 10 ký tự chỉ được chấp nhận khi
    # hai dòng cân bằng (ví dụ 5/5), tránh việc một mảnh nhiễu ở mép làm
    # chuỗi 4/6 được coi là hợp lệ.
    expected_chars: Tuple[int, int] = (7, 9)
    allow_balanced_long_plate: bool = True
    min_chars: int = 5
    char_padding: int = 2


@dataclass
class RecognitionConfig:
    method: str = "TM_CCOEFF_NORMED"
    score_threshold: float = 0.60
    min_margin: float = 0.035
    # Ảnh ký tự thực tế thường đậm hơn template. Kéo giãn ink box về đúng
    # canvas giúp giảm lệch độ dày nét và cải thiện rõ rệt trên biển thật.
    normalize_mode: str = "stretch"  # stretch | aspect
    normalized_width: int = 32
    normalized_height: int = 48
    padding: int = 2
    template_extensions: List[str] = field(
        default_factory=lambda: [".png", ".jpg", ".jpeg"]
    )
    require_all_labels: bool = False
    upscale_templates: bool = True
    # Các nhãn không hợp lệ trên biển số Việt Nam (theo quy định series không
    # dùng I, J, O, Q, W). Vẫn giữ template để tham khảo nhưng không chấm điểm.
    excluded_labels: List[str] = field(
        default_factory=lambda: ["I", "J", "O", "Q", "W"]
    )
    match_blur_sigma: float = 2.0
    shift_tolerance: int = 1
    # Ưu tiên topology: số lỗ trắng bên trong ký tự là đặc trưng hình học
    # mạnh để phân biệt 6/B, 0/8, D/B... Chỉ trừ điểm ứng viên có số lỗ khác
    # với đa số template của nhãn; không tạo ký tự mới.
    hole_prior: bool = True
    hole_penalty: float = 0.20
    hole_min_area: float = 25.0
    # Bổ sung biến thể chữ 4 hở đỉnh (nét dọc phải bắt đầu từ giữa) cho các
    # font biển thật. Đây là augmentation template thủ công, không học máy.
    open_top_four_variant: bool = True
    max_templates_per_label: int = 60
    template_min_diff_ratio: float = 0.005
    coarse_templates_per_label: int = 6
    coarse_top_labels: int = 6


@dataclass
class PostprocessingConfig:
    patterns: List[str] = field(
        default_factory=lambda: [r"^[0-9]{2}[A-Z]{1,2}[0-9]{4,6}$"]
    )
    supported_description: str = (
        "Biển Việt Nam: 2 số tỉnh + 1-2 chữ series + 4-6 số"
    )
    allowed_series_letters: str = "ABCDEFGHKLMNPSTUVXYZ"
    # Dùng cấu trúc biển (2 số tỉnh + 1-2 chữ series + 4-6 số) để chọn lại
    # trong danh sách template đã chấm điểm. Không tạo ký tự mới ngoài các
    # ứng viên đã có, chỉ loại ứng viên sai kiểu tại vị trí đó.
    position_constraints: bool = True
    position_resolve_max_drop: float = 0.15
    # Khi cấu trúc biển đã xác định kiểu ký tự, hai ứng viên cùng kiểu sát
    # nhau vẫn có thể phân biệt được nhờ ngữ cảnh. Ngưỡng này thấp hơn
    # min_margin chung nhưng chỉ dùng trong rerank theo vị trí.
    position_min_margin: float = 0.02
    min_mean_confidence: float = 0.60
    min_char_confidence: float = 0.50
    min_confident_ratio: float = 0.85


@dataclass
class PipelineConfig:
    max_candidates_to_try: int = 8
    save_debug: bool = False
    debug_dir: str = "results/debug"
    fail_on_missing_templates: bool = True


@dataclass
class EvaluationConfig:
    iou_threshold: float = 0.5
    ipc_confidence_threshold: float = 0.55
    output_csv: str = "results/evaluation.csv"
    output_summary: str = "results/evaluation_summary.json"


@dataclass
class UIConfig:
    theme: str = "clam"
    max_display_width: int = 760
    max_display_height: int = 560


@dataclass
class Config:
    project: ProjectConfig = field(default_factory=ProjectConfig)
    paths: PathsConfig = field(default_factory=PathsConfig)
    image: ImageConfig = field(default_factory=ImageConfig)
    preprocessing: PreprocessingConfig = field(default_factory=PreprocessingConfig)
    detection: DetectionConfig = field(default_factory=DetectionConfig)
    rectification: RectificationConfig = field(default_factory=RectificationConfig)
    segmentation: SegmentationConfig = field(default_factory=SegmentationConfig)
    recognition: RecognitionConfig = field(default_factory=RecognitionConfig)
    postprocessing: PostprocessingConfig = field(
        default_factory=PostprocessingConfig
    )
    pipeline: PipelineConfig = field(default_factory=PipelineConfig)
    evaluation: EvaluationConfig = field(default_factory=EvaluationConfig)
    ui: UIConfig = field(default_factory=UIConfig)

    project_root: Path = field(default_factory=lambda: PROJECT_ROOT, repr=False)
    config_path: Optional[Path] = field(default=None, repr=False)
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    # ------------------------------------------------------------------
    def resolve(self, value: str | Path) -> Path:
        """Chuyển đường dẫn tương đối thành tuyệt đối theo gốc dự án."""
        p = Path(value)
        return p if p.is_absolute() else (self.project_root / p)

    @property
    def templates_dir(self) -> Path:
        return self.resolve(self.paths.templates_dir)

    @property
    def samples_dir(self) -> Path:
        return self.resolve(self.paths.samples_dir)

    @property
    def labels_file(self) -> Path:
        return self.resolve(self.paths.labels_file)

    @property
    def results_dir(self) -> Path:
        return self.resolve(self.paths.results_dir)

    def to_dict(self) -> Dict[str, Any]:
        """Chụp lại toàn bộ cấu hình để lưu vào kết quả/CSV."""
        data = asdict(self)
        data.pop("project_root", None)
        data.pop("config_path", None)
        data.pop("raw", None)

        def _convert(obj: Any) -> Any:
            if isinstance(obj, Path):
                return str(obj)
            if isinstance(obj, tuple):
                return list(obj)
            if isinstance(obj, dict):
                return {k: _convert(v) for k, v in obj.items()}
            if isinstance(obj, list):
                return [_convert(v) for v in obj]
            return obj

        return _convert(data)


# ----------------------------------------------------------------------
# Hàm hỗ trợ nạp cấu hình
# ----------------------------------------------------------------------
_SECTION_TYPES = {
    "project": ProjectConfig,
    "paths": PathsConfig,
    "image": ImageConfig,
    "preprocessing": PreprocessingConfig,
    "detection": DetectionConfig,
    "rectification": RectificationConfig,
    "segmentation": SegmentationConfig,
    "recognition": RecognitionConfig,
    "postprocessing": PostprocessingConfig,
    "pipeline": PipelineConfig,
    "evaluation": EvaluationConfig,
    "ui": UIConfig,
}


def _build_dataclass(cls, data: Dict[str, Any]):
    """Khởi tạo dataclass, bỏ qua khóa lạ và giữ mặc định cho khóa thiếu."""
    if not isinstance(data, dict):
        return cls()
    allowed = {f.name for f in fields(cls)}
    kwargs = {k: v for k, v in data.items() if k in allowed}
    if cls is DetectionConfig and isinstance(kwargs.get("weights"), dict):
        kwargs["weights"] = DetectionWeights(**kwargs["weights"])
    for key in ("clahe_tile_grid", "close_kernel", "blur_kernel", "expected_chars"):
        if key in kwargs and isinstance(kwargs[key], list):
            kwargs[key] = tuple(kwargs[key])
    if cls is DetectionConfig:
        if "extra_close_kernels" in kwargs:
            kwargs["extra_close_kernels"] = [
                tuple(x) if isinstance(x, list) else x
                for x in kwargs["extra_close_kernels"]
            ]
        if "ratio_targets" in kwargs:
            kwargs["ratio_targets"] = list(kwargs["ratio_targets"])
    return cls(**kwargs)


def _apply_override(data: Dict[str, Any], dotted_key: str, value: Any) -> None:
    parts = dotted_key.split(".")
    node = data
    for part in parts[:-1]:
        if part not in node or not isinstance(node[part], dict):
            node[part] = {}
        node = node[part]
    node[parts[-1]] = value


def _merge_dict(base: Dict[str, Any], extra: Dict[str, Any]) -> Dict[str, Any]:
    result = copy.deepcopy(base)
    for key, value in extra.items():
        if (
            key in result
            and isinstance(result[key], dict)
            and isinstance(value, dict)
        ):
            result[key] = _merge_dict(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def load_config(
    path: str | Path | None = None,
    overrides: Optional[Dict[str, Any]] = None,
) -> Config:
    """Đọc ``config.yaml`` và áp dụng các ghi đè dạng ``section.key``."""
    cfg_path = Path(path) if path else PROJECT_ROOT / "config.yaml"
    if not cfg_path.is_absolute():
        # Ưu tiên đường dẫn tương đối theo thư mục làm việc hiện tại.
        if not cfg_path.exists():
            cfg_path = PROJECT_ROOT / cfg_path
    data: Dict[str, Any] = {}
    if cfg_path.exists():
        with cfg_path.open("r", encoding="utf-8") as fh:
            loaded = yaml.safe_load(fh) or {}
        if not isinstance(loaded, dict):
            raise ValueError(f"File cấu hình không hợp lệ: {cfg_path}")
        data = loaded
    else:
        raise FileNotFoundError(f"Không tìm thấy file cấu hình: {cfg_path}")

    if overrides:
        for key, value in overrides.items():
            if "." in key:
                _apply_override(data, key, value)
            else:
                # Ghi đè cả một section bằng dict
                if isinstance(value, dict) and isinstance(data.get(key), dict):
                    data[key] = _merge_dict(data[key], value)
                else:
                    data[key] = value

    sections: Dict[str, Any] = {}
    for name, cls in _SECTION_TYPES.items():
        sections[name] = _build_dataclass(cls, data.get(name, {}))

    cfg = Config(**sections)
    cfg.project_root = PROJECT_ROOT
    cfg.config_path = cfg_path
    cfg.raw = data

    # Kiểm tra nhanh tính hợp lệ của trọng số
    w = cfg.detection.weights.normalized()
    if abs((w.ratio + w.area + w.edge + w.fill) - 1.0) > 1e-6:
        raise ValueError("Trọng số detection không hợp lệ")
    return cfg


def save_config(config: Config, path: str | Path) -> Path:
    """Lưu cấu hình hiện tại (đã áp dụng ghi đè) ra YAML."""
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(
            config.to_dict(),
            fh,
            allow_unicode=True,
            sort_keys=False,
            default_flow_style=False,
        )
    return out
