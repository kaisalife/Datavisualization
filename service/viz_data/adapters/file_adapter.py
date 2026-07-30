"""FileAdapter：把 CSV/Excel/Parquet/PDF 文件转成 VizDataset。

fetch 阶段：无 LLM。读文件 → 落盘 parquet（如果不是 parquet 的话）
normalize 阶段：从 parquet 读 schema → 推断 semantic → 组装 VizDataset

- PDF 文件会内部委托给 PdfAdapter 处理表格提取
- 多文件时：目前只取第一个（保持与旧行为一致），后续可扩展为多 tabular。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import pandas as pd

from service.introspection.df_stats import (
    dataframe_to_column_schemas,
    infer_semantic_hints,
)
from service.constants import CSV_ENCODINGS
from service.viz_data.adapters.base import AdapterError, VizDataAdapter
from service.viz_data.capabilities import AdapterCapabilities
from service.viz_data.schema import (
    DataAccessor,
    DataRef,
    RawDataBundle,
    TabularBlock,
    VizDataset,
)
from service.viz_data.source_descriptor import SourceDescriptor
from service.viz_data.storage import new_dataset_dir, save_dataframe_to_parquet


_CSV_ENCODINGS = list(CSV_ENCODINGS)


class FileAdapter(VizDataAdapter):
    """CSV/Excel/Parquet/PDF 文件 → VizDataset。

    多文件策略：
    - 单文件：按后缀走对应处理逻辑
    - 多文件全为 Excel/CSV：委托给 MultiExcelAdapter 做智能列对齐合并
    - 多文件包含非 Excel/CSV：依次独立读入作为 related_datasets
    """

    def __init__(self, file_paths: list[str]):
        self.file_paths = list(file_paths or [])
        # lazy 实例化的代理
        self._pdf_adapter: Optional["PdfAdapter"] = None  # type: ignore[name-defined]
        self._multi_excel_adapter: Optional["MultiExcelAdapter"] = None  # type: ignore[name-defined]
        self._json_adapter: Optional["JsonAdapter"] = None  # type: ignore[name-defined]
        self._folder_adapter: Optional["FolderAdapter"] = None  # type: ignore[name-defined]
        self._strategy: str = "single"  # single / pdf / multi_excel / multi_file / json / folder

    def source_kind(self) -> str:
        return "file"

    def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(
            needs_llm=False,
            supports_multi_query=True,  # 支持多文件上传（related_datasets）
        )

    def descriptor(self) -> SourceDescriptor:
        if self._strategy == "pdf" and self._pdf_adapter:
            return self._pdf_adapter.descriptor()
        if self._strategy == "multi_excel" and self._multi_excel_adapter:
            return self._multi_excel_adapter.descriptor()
        if self._strategy == "json" and self._json_adapter:
            return self._json_adapter.descriptor()
        if self._strategy == "folder" and self._folder_adapter:
            return self._folder_adapter.descriptor()
        if not self.file_paths:
            return SourceDescriptor(
                kind="file", label="FileAdapter", logical_id="file_unknown"
            )
        first = Path(self.file_paths[0])
        stem = first.stem or "file"
        label = stem if len(self.file_paths) == 1 else f"{stem} (+{len(self.file_paths) - 1})"
        return SourceDescriptor(
            kind="file",
            label=label,
            logical_id=_sanitize_id(stem),
            tags=("file",),
        )

    def validate(self) -> None:
        if not self.file_paths:
            raise AdapterError("FileAdapter 需要至少一个 file_paths")
        for p in self.file_paths:
            if not Path(p).exists():
                raise AdapterError(f"文件不存在: {p}")

        # 判断策略
        first = Path(self.file_paths[0])

        if len(self.file_paths) == 1:
            suffix = first.suffix.lower()
            if suffix == ".pdf":
                self._strategy = "pdf"
                from service.viz_data.adapters.pdf_adapter import PdfAdapter
                self._pdf_adapter = PdfAdapter(str(first))
            elif suffix in (".json", ".jsonl"):
                self._strategy = "json"
                from service.viz_data.adapters.json_adapter import JsonAdapter
                self._json_adapter = JsonAdapter(str(first))
            elif suffix == ".zip":
                self._strategy = "folder"
                from service.viz_data.adapters.folder_adapter import FolderAdapter
                self._folder_adapter = FolderAdapter(str(first))
            else:
                self._strategy = "single"
        else:
            # 多文件：判断是否都是 Excel/CSV
            all_excel = all(Path(p).suffix.lower() in (".xlsx", ".xls", ".csv")
                            for p in self.file_paths)
            if all_excel:
                self._strategy = "multi_excel"
                from service.viz_data.adapters.multi_excel_adapter import MultiExcelAdapter
                self._multi_excel_adapter = MultiExcelAdapter(self.file_paths)
            else:
                self._strategy = "multi_file"

    async def adapt(self, engine=None) -> VizDataset:
        """根据策略分发。"""
        self.validate()
        if self._strategy == "pdf" and self._pdf_adapter:
            return await self._pdf_adapter.adapt(engine)
        if self._strategy == "multi_excel" and self._multi_excel_adapter:
            return await self._multi_excel_adapter.adapt(engine)
        if self._strategy == "json" and self._json_adapter:
            return await self._json_adapter.adapt(engine)
        if self._strategy == "folder" and self._folder_adapter:
            return await self._folder_adapter.adapt(engine)
        # 其余策略：走原有 fetch -> normalize
        raw = await self.fetch(engine)
        return self.normalize(raw)

    async def fetch(self, engine=None) -> RawDataBundle:
        """读文件 → 落盘 parquet。"""
        ds_id, ds_dir = new_dataset_dir()

        tabular_files = []
        used_names: set[str] = set()
        for idx, f in enumerate(self.file_paths):
            df = _read_file_as_dataframe(f)
            base_name = Path(f).stem
            # 避免同名文件覆盖
            name = base_name
            if name in used_names:
                name = f"{base_name}_{idx}"
            used_names.add(name)

            parquet_path = save_dataframe_to_parquet(df, ds_dir, name=name)
            tabular_files.append({
                "name": name,
                "path": str(parquet_path.resolve()),
                "row_count": int(len(df)),
                "col_count": int(len(df.columns)),
                "original_source": str(Path(f).resolve()),
            })

        return RawDataBundle(
            source_kind="file",
            source_meta={"file_paths": [str(Path(p).resolve()) for p in self.file_paths]},
            tabular_files=tabular_files,
            array_files=[],
            fetch_context={"dataset_id": ds_id},
            temp_dir=str(ds_dir.resolve()),
        )

    def normalize(self, raw: RawDataBundle) -> VizDataset:
        """从 raw.tabular_files 组装 VizDataset。多文件时，第一个为 primary，其余为 related。"""
        if not raw.tabular_files:
            raise AdapterError("FileAdapter.normalize: 没有 tabular_files")

        primary_ds = self._build_dataset(raw, raw.tabular_files[0], is_primary=True)

        # 多文件：其余转成 related_datasets
        for extra in raw.tabular_files[1:]:
            related = self._build_dataset(raw, extra, is_primary=False)
            primary_ds.related_datasets.append(related)

        return primary_ds

    def _build_dataset(self, raw: RawDataBundle, file_info: dict,
                       is_primary: bool = True) -> VizDataset:
        """把单个 tabular_file 组装成 VizDataset。"""
        parquet_path = file_info["path"]

        # 从 parquet 反查 schema + preview
        df = pd.read_parquet(parquet_path, engine="pyarrow")

        columns = dataframe_to_column_schemas(df)
        preview_rows = df.head(10).astype(str).values.tolist()

        data_ref = DataRef(
            kind="parquet",
            path=parquet_path,
            size_bytes=os.path.getsize(parquet_path),
        )

        tabular = TabularBlock(
            columns=columns,
            row_count=int(len(df)),
            preview_rows=preview_rows,
            data_ref=data_ref,
        )

        semantic_hints = infer_semantic_hints(df, columns=columns)

        accessor = DataAccessor(
            accessor_id="load_data",
            signature="def load_data() -> pd.DataFrame",
            docstring=f"读取 {file_info['name']} 全部数据为 DataFrame",
            returns_description=f"DataFrame with {len(df)} rows and columns {list(df.columns)}",
            code_file=None,
        )

        dataset_id = raw.fetch_context.get("dataset_id", "ds_unknown")
        if not is_primary:
            # 次级 dataset 拼上文件名后缀，避免 id 冲突
            dataset_id = f"{dataset_id}__{file_info['name']}"

        return VizDataset(
            dataset_id=dataset_id,
            name=file_info["name"],
            source_kind="file",
            source_meta=raw.source_meta,
            primary_form="tabular",
            tabular=tabular,
            arrays={},
            semantic_hints=semantic_hints,
            accessors=[accessor],
            # 只有 primary 挂载 _temp_dir，related 共享该目录（cleanup 由 primary 负责）
            _temp_dir=raw.temp_dir if is_primary else None,
        )


# ============================================================
# 内部工具
# ============================================================

def _sanitize_id(raw: str) -> str:
    """把任意字符串转成安全的 logical_id：只保留字母/数字/下划线/中文。"""
    if not raw:
        return "file"
    keep = "_"
    return "".join(c if (c.isalnum() or c in keep) else "_" for c in raw).strip("_") or "file"


def _read_file_as_dataframe(path: str) -> pd.DataFrame:
    """按后缀选择合适的 pandas 读取方式。"""
    lower = path.lower()

    if lower.endswith(".parquet"):
        return pd.read_parquet(path, engine="pyarrow")

    if lower.endswith((".xls", ".xlsx", ".xlsm")):
        return pd.read_excel(path)

    if lower.endswith(".json"):
        return pd.read_json(path)

    # 默认 CSV，尝试多编码
    last_err: Optional[Exception] = None
    for enc in _CSV_ENCODINGS:
        try:
            return pd.read_csv(path, encoding=enc)
        except UnicodeDecodeError:
            continue
        except Exception as e:
            last_err = e
            continue
    if last_err:
        # 最后一次容错读取
        return pd.read_csv(path, encoding="utf-8", encoding_errors="ignore")
    raise AdapterError(f"无法读取文件: {path}")
