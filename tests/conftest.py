"""Fixture dùng chung cho bộ kiểm thử pytest.

Bộ test chạy trực tiếp trên dữ liệu mẫu tổng hợp đi kèm dự án. Các fixture
phiên (session) giúp nạp bộ template đúng một lần, tránh tăng thời gian chạy
do mỗi test phải đọc lại hơn 1.400 template.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.character_recognition import TemplateLibrary, load_templates  # noqa: E402
from src.config import Config, load_config  # noqa: E402
from src.pipeline import LicensePlateRecognizer  # noqa: E402


@pytest.fixture(scope="session")
def config() -> Config:
    return load_config()


@pytest.fixture(scope="session")
def template_library(config: Config) -> TemplateLibrary:
    return load_templates(None, config)


@pytest.fixture(scope="session")
def recognizer(
    config: Config, template_library: TemplateLibrary
) -> LicensePlateRecognizer:
    return LicensePlateRecognizer(config, library=template_library)


@pytest.fixture(scope="session")
def samples_dir(config: Config) -> Path:
    return config.samples_dir
