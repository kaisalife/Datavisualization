"""ZIP/压缩包 Reader（v4）。

解压 ZIP 文件后，对内部每个文件递归路由到对应 reader，
汇总为 list[RawTable]（不再注册到 DuckDB）。
"""

from __future__ import annotations

import gzip
import shutil
import tarfile
import zipfile
from pathlib import Path

from service.data_ingestion.models import RawTable, safe_table_name
from service.runtime.utils import get_env_int

# 解压安全上限（可用环境变量覆盖）
_DEFAULT_MAX_FILES = 500
_DEFAULT_MAX_BYTES = 512 * 1024 * 1024
_COPY_CHUNK = 1024 * 1024


def _safe_target(extract_dir: Path, name: str) -> Path:
    """把压缩包内路径解析到 extract_dir 内；越界（zip slip）直接拒绝。"""
    root = extract_dir.resolve()
    target = (extract_dir / name).resolve()
    if target != root and not target.is_relative_to(root):
        raise ValueError(f"压缩包路径越界，已拒绝: {name}")
    return target


def _check_limits(count: int, total_bytes: int, max_files: int, max_bytes: int) -> None:
    """校验成员数量与解压后总大小。"""
    if count > max_files:
        raise ValueError(f"压缩包文件数超过上限（{count} > {max_files}）")
    if total_bytes > max_bytes:
        raise ValueError(f"压缩包解压后大小超过上限（{total_bytes} > {max_bytes} 字节）")


class ArchiveReader:
    """解压 ZIP 文件并递归处理内部文件。"""

    @staticmethod
    def can_handle(path: str) -> bool:
        ext = Path(path).suffix.lower()
        return ext in {".zip", ".tar", ".gz", ".tar.gz", ".tgz"}

    @staticmethod
    def read(
        path: str,
        table_name: str | None = None,
        extract_dir: str | Path | None = None,
    ) -> list[RawTable]:
        """解压 ZIP 并递归处理内部文件。

        Args:
            path: ZIP 文件路径
            table_name: 基础表名 (可选)
            extract_dir: 解压目录 (可选, 默认在临时目录)

        Returns:
            list[RawTable]（解压后每个可处理文件一条，逐级平铺）
        """
        # 延迟导入避免循环
        from service.data_ingestion.readers.file_reader import FileReader
        from service.data_ingestion.readers.excel_reader import ExcelReader
        from service.data_ingestion.readers.document_reader import DocumentReader

        base_name = safe_table_name(table_name or Path(path).name)

        if extract_dir is None:
            extract_dir = Path(path).parent / f"{Path(path).stem}_extracted"
        extract_dir = Path(extract_dir)
        existed = extract_dir.exists()
        extract_dir.mkdir(parents=True, exist_ok=True)

        try:
            ArchiveReader._extract_archive(path, extract_dir)
        except Exception:
            # 本次新建的目录解压失败时清掉半成品；调用方自带目录不动
            if not existed:
                shutil.rmtree(extract_dir, ignore_errors=True)
            raise

        raw_tables: list[RawTable] = []
        idx = 0

        for file_path in sorted(extract_dir.rglob("*")):
            if not file_path.is_file():
                continue
            if file_path.suffix.lower() in {".zip", ".tar", ".gz", ".tgz"}:
                raw_tables.extend(
                    ArchiveReader.read(
                        str(file_path),
                        table_name=f"{base_name}_nested{idx}",
                        extract_dir=extract_dir / f"nested_{idx}",
                    )
                )
                idx += 1
                continue

            str_path = str(file_path)
            name = f"{base_name}_{idx}" if idx > 0 else base_name

            if FileReader.can_handle(str_path):
                raw_tables.extend(FileReader.read(str_path, table_name=name))
            elif ExcelReader.can_handle(str_path):
                raw_tables.extend(ExcelReader.read(str_path, table_name=name))
            elif DocumentReader.can_handle(str_path):
                raw_tables.extend(DocumentReader.read(str_path, table_name=name))
            else:
                continue
            idx += 1

        if not raw_tables:
            raise ValueError(f"ZIP 文件中无可处理的文件: {path}")

        return raw_tables

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
        max_files = get_env_int("ARCHIVE_MAX_FILES", _DEFAULT_MAX_FILES)
        max_bytes = get_env_int("ARCHIVE_MAX_BYTES", _DEFAULT_MAX_BYTES)

        if lower_path.endswith(".zip"):
            _extract_zip(path, extract_dir, max_files, max_bytes)
        elif lower_path.endswith((".tar", ".tar.gz", ".tgz")):
            _extract_tar(path, extract_dir, max_files, max_bytes)
        elif lower_path.endswith(".gz"):
            _extract_gzip(path, extract_dir, max_bytes)
        else:
            raise ValueError(f"不支持的压缩格式: {path}")


def _extract_zip(path: str, extract_dir: Path, max_files: int, max_bytes: int) -> None:
    """安全解压 ZIP：拒绝越界路径，限制文件数与解压体积。"""
    with zipfile.ZipFile(path, "r") as zf:
        members = zf.infolist()
        total = 0
        for member in members:
            if member.is_dir():
                continue
            _safe_target(extract_dir, member.filename)
            total += max(0, member.file_size)
        _check_limits(len(members), total, max_files, max_bytes)

        for member in members:
            if member.is_dir():
                continue
            _safe_target(extract_dir, member.filename)
            zf.extract(member, extract_dir)


def _extract_tar(path: str, extract_dir: Path, max_files: int, max_bytes: int) -> None:
    """安全解压 TAR：拒绝越界路径、符号链接/硬链接与特殊文件。"""
    lower_path = path.lower()
    mode = "r:gz" if lower_path.endswith((".tar.gz", ".tgz")) else "r:"
    with tarfile.open(path, mode) as tf:
        members = tf.getmembers()
        total = 0
        for member in members:
            if member.issym() or member.islnk():
                raise ValueError(f"压缩包包含符号链接/硬链接，已拒绝: {member.name}")
            if not (member.isfile() or member.isdir()):
                raise ValueError(f"压缩包包含不支持的成员类型，已拒绝: {member.name}")
            if member.isfile():
                _safe_target(extract_dir, member.name)
                total += max(0, member.size)
        _check_limits(len(members), total, max_files, max_bytes)

        for member in members:
            if member.isdir():
                continue
            _safe_target(extract_dir, member.name)
            try:
                tf.extract(member, extract_dir, filter="data")
            except TypeError:
                tf.extract(member, extract_dir)


def _extract_gzip(path: str, extract_dir: Path, max_bytes: int) -> None:
    """解压单文件 GZIP，边读边限制输出体积。"""
    out_path = _safe_target(extract_dir, Path(path).stem)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    try:
        with gzip.open(path, "rb") as src, open(out_path, "wb") as dst:
            while True:
                chunk = src.read(_COPY_CHUNK)
                if not chunk:
                    break
                written += len(chunk)
                if written > max_bytes:
                    raise ValueError(f"GZIP 解压后大小超过上限（> {max_bytes} 字节）")
                dst.write(chunk)
    except Exception:
        out_path.unlink(missing_ok=True)
        raise