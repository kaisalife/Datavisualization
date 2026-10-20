"""上传文件名展示化：去掉 32 位 hex 前缀，但不影响磁盘目录。"""
from pathlib import Path

from service.runtime.utils import display_name_from_path


def test_strips_upload_uuid_prefix():
    path = Path("runtime/uploads/d3ea568317e54264a2de53169a9d47b8_two_tables.heic")
    assert display_name_from_path(path) == "two_tables"


def test_keeps_names_without_prefix():
    assert display_name_from_path("sales_2024.csv") == "sales_2024"
    assert display_name_from_path(r"C:\data\report.docx") == "report"


def test_does_not_strip_short_hex_like_names():
    # 不是 32 位 hex 前缀就不动，避免误伤正常文件名
    assert display_name_from_path("abc123_report.xlsx") == "abc123_report"
    assert display_name_from_path("0123456789abcdef_report.xlsx") == "0123456789abcdef_report"


def test_strips_uppercase_prefix():
    prefix = "A" * 32
    assert display_name_from_path(f"{prefix}_表格.png") == "表格"


def test_keeps_extra_dots_in_name():
    prefix = "b" * 32
    assert display_name_from_path(f"/tmp/{prefix}_report.v2.pdf") == "report.v2"
