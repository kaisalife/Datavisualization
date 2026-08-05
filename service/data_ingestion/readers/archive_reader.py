"""ZIP/压缩包 Reader。

解压 ZIP 文件后，对内部每个文件递归路由到对应 reader。
"""

from __future__ import annotations

import gzip
import shutil
import tarfile
import zipfile
from pathlib import Path

from service.data_ingestion.duckdb_manager import DuckDBManager
from service.data_ingestion.models import DataProfile
from service.data_ingestion.profiler import build_profiles_for_multiple_tables


class ArchiveReader:
    """解压 ZIP 文件并递归处理内部文件。"""

    @staticmethod
    def can_handle(path: str) -> bool:
        ext = Path(path).suffix.lower()
        return ext in {".zip", ".tar", ".gz", ".tar.gz", ".tgz"}

    @staticmethod
    def read(
        db: DuckDBManager,
        path: str,
        table_name: str | None = None,
        extract_dir: str | Path | None = None,
    ) -> DataProfile:
        """解压 ZIP 并递归处理内部文件。

        Args:
            db: DuckDBManager 实例
            path: ZIP 文件路径
            table_name: 基础表名 (可选)
            extract_dir: 解压目录 (可选, 默认在临时目录)

        Returns:
            DataProfile (第一个文件的 profile, related_tables 包含其余文件)
        """
        # 延迟导入避免循环
        from service.data_ingestion.readers.file_reader import FileReader
        from service.data_ingestion.readers.excel_reader import ExcelReader
        from service.data_ingestion.readers.document_reader import DocumentReader

        base_name = table_name or DuckDBManager.safe_table_name(Path(path).name)

        # 解压目录
        if extract_dir is None:
            extract_dir = Path(path).parent / f"{Path(path).stem}_extracted"
        extract_dir = Path(extract_dir)
        extract_dir.mkdir(parents=True, exist_ok=True)

        # 解压（按格式选择后端）
        ArchiveReader._extract_archive(path, extract_dir)

        # 递归处理解压后的文件
        table_specs = []
        profiles = []
        idx = 0

        for file_path in sorted(extract_dir.rglob("*")):
            if not file_path.is_file():
                continue
            if file_path.suffix.lower() in {".zip", ".tar", ".gz", ".tgz"}:
                # 嵌套压缩包，递归处理
                nested_profile = ArchiveReader.read(
                    db, str(file_path),
                    table_name=f"{base_name}_nested{idx}",
                    extract_dir=extract_dir / f"nested_{idx}",
                )
                profiles.append(nested_profile)
                idx += 1
                continue

            str_path = str(file_path)
            profile = None

            # 按优先级尝试各 reader
            if FileReader.can_handle(str_path):
                name = f"{base_name}_{idx}" if idx > 0 else base_name
                profile = FileReader.read(db, str_path, table_name=name)
            elif ExcelReader.can_handle(str_path):
                name = f"{base_name}_{idx}" if idx > 0 else base_name
                profile = ExcelReader.read(db, str_path, table_name=name)
            elif DocumentReader.can_handle(str_path):
                name = f"{base_name}_{idx}" if idx > 0 else base_name
                profile = DocumentReader.read(db, str_path, table_name=name)

            if profile:
                profiles.append(profile)
                idx += 1

        if not profiles:
            raise ValueError(f"ZIP 文件中无可处理的文件: {path}")

        if len(profiles) == 1:
            return profiles[0]

        # 多文件: 设置 related_tables
        profiles[0].related_tables = profiles[1:]
        return profiles[0]

    @staticmethod
    def _extract_archive(path: str, extract_dir: Path) -> None:
        """按压缩格式解压到 extract_dir。

        支持三类后端：
        - ZIP (.zip)
        - TAR (.tar / .tar.gz / .tgz)
        - 纯 GZIP 单文件 (.gz，非 tar 归档)

        Args:
            path: 压缩文件路径
            extract_dir: 解压目标目录（已存在）
        """
        lower_path = path.lower()
        if lower_path.endswith(".zip"):
            with zipfile.ZipFile(path, "r") as zf:
                zf.extractall(str(extract_dir))
        elif lower_path.endswith((".tar", ".tar.gz", ".tgz")):
            mode = "r:gz" if lower_path.endswith((".tar.gz", ".tgz")) else "r:"
            with tarfile.open(path, mode) as tf:
                try:
                    # Python 3.12+ 推荐 filter="data" 防路径穿越
                    tf.extractall(str(extract_dir), filter="data")
                except TypeError:
                    # Python < 3.12 不支持 filter 参数
                    tf.extractall(str(extract_dir))
        elif lower_path.endswith(".gz"):
            # 纯 gzip 单文件（非 tar 归档），解压为去掉 .gz 后缀的单文件
            out_path = extract_dir / Path(path).stem
            out_path.parent.mkdir(parents=True, exist_ok=True)
            with gzip.open(path, "rb") as gf, open(out_path, "wb") as f:
                shutil.copyfileobj(gf, f)
        else:
            raise ValueError(f"不支持的压缩格式: {path}")
