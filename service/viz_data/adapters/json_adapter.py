"""JSON / JSONL Adapter。

适用场景：
- 埋点日志（JSONL 每行一个事件）
- API 响应导出
- 实验平台数据

核心能力：
- 自动扁平化嵌套字段（a.b.c → a_b_c）
- 数组字段可选展开（一行变多行）或 JSON 字符串序列化
- 支持单 JSON 对象文件或 JSONL 文件（按行读取）
- 自动识别是 JSON 还是 JSONL 格式
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Optional, Any

import pandas as pd

from service.viz_data.adapters.base import AdapterError, VizDataAdapter
from service.viz_data.capabilities import AdapterCapabilities
from service.viz_data.schema import DataRef, RawDataBundle, TabularBlock, VizDataset
from service.viz_data.source_descriptor import SourceDescriptor
from service.viz_data.storage import new_dataset_dir, save_dataframe_to_parquet

if TYPE_CHECKING:
    from service.query_engine import QueryEngine


class JsonAdapter(VizDataAdapter):
    """把 JSON / JSONL 文件转成 VizDataset。

    Args:
        file_path: JSON / JSONL 文件路径
        flatten: 是否扁平化嵌套字段（默认 True）
        expand_arrays: 遇到数组时，是否展开为多行（默认 False，保留 JSON 字符串）
        array_column_prefix: 展开数组时，数组元素字段的列名前缀（默认 "item_"）
        dataset_name: 数据集名称（默认取文件名）
    """

    def __init__(
        self,
        file_path: str,
        flatten: bool = True,
        expand_arrays: bool = False,
        array_column_prefix: str = "item_",
        dataset_name: Optional[str] = None,
    ):
        self.file_path = Path(file_path)
        self.flatten = flatten
        self.expand_arrays = expand_arrays
        self.array_column_prefix = array_column_prefix
        self.dataset_name = dataset_name or self.file_path.stem

    def source_kind(self) -> str:
        return "file"

    def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(needs_llm=False, supports_multi_query=True)

    def validate(self) -> None:
        if not self.file_path.exists():
            raise AdapterError(f"JSON 文件不存在: {self.file_path}")
        if self.file_path.suffix.lower() not in (".json", ".jsonl"):
            raise AdapterError(f"仅支持 .json / .jsonl，不支持: {self.file_path.suffix}")

    async def fetch(self, engine: "QueryEngine | None") -> RawDataBundle:
        """Phase 1: 读取 JSON -> 扁平化 -> 落盘 parquet。"""
        dataset_dir = new_dataset_dir()

        # Step 1: 判断格式并读取
        suffix = self.file_path.suffix.lower()
        raw_objects: list[dict] = []

        if suffix == ".jsonl":
            with open(self.file_path, "r", encoding="utf-8") as f:
                for line_no, line in enumerate(f, 1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                        if isinstance(obj, dict):
                            raw_objects.append(obj)
                        elif isinstance(obj, list):
                            raw_objects.extend(obj)  # 行是数组也接受
                    except json.JSONDecodeError as e:
                        raise AdapterError(f"第 {line_no} 行 JSONL 解析失败: {e}") from e
        else:  # .json
            with open(self.file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                # 顶层是数组字段才展开，否则作为单个对象
                has_array_value = any(isinstance(v, list) and v for v in data.values())
                if has_array_value and len(data) == 1:
                    # {"data": [...]} 形式，取数组作为行
                    key = list(data.keys())[0]
                    items = data[key]
                    if isinstance(items, list):
                        for idx, item in enumerate(items):
                            if isinstance(item, dict):
                                item.setdefault("_jsonl_row_idx", idx)
                                raw_objects.append(item)
                else:
                    raw_objects.append(data)
            elif isinstance(data, list):
                raw_objects = list(data)
            else:
                raise AdapterError(f"JSON 文件格式不支持: 根节点是 {type(data).__name__}")

        if not raw_objects:
            raise AdapterError("JSON 文件中未读到有效数据对象")

        # Step 2: 扁平化（可选）
        processed: list[dict] = []
        for obj in raw_objects:
            if self.flatten:
                flat = self._flatten_dict(obj)
                processed.append(flat)
            else:
                processed.append(dict(obj))

        # Step 3: 数组展开（可选）
        if self.expand_arrays:
            processed = self._expand_arrays(processed)

        # Step 4: 转 DataFrame 并落盘
        df = pd.DataFrame(processed)

        # 类型优化：把能转数字的列转掉
        for col in df.columns:
            if df[col].dtype == object:
                try:
                    numeric = pd.to_numeric(df[col], errors="coerce")
                    if numeric.notna().mean() >= 0.5:
                        df[col] = numeric
                except Exception:
                    pass

        parquet_path = dataset_dir / "data.parquet"
        save_dataframe_to_parquet(df, parquet_path)

        return RawDataBundle(
            dataset_dir=str(dataset_dir),
            tabular_files=[{
                "path": str(parquet_path),
                "shape": [len(df), len(df.columns)],
                "columns": list(df.columns),
            }],
            meta={
                "source": "json",
                "original_file": str(self.file_path),
                "flatten": self.flatten,
                "expand_arrays": self.expand_arrays,
                "format": suffix.lstrip("."),
            },
        )

    def normalize(self, raw: RawDataBundle) -> VizDataset:
        """Phase 2: 构建 VizDataset。"""
        tabular_files = raw.tabular_files or []
        if not tabular_files:
            raise AdapterError("JsonAdapter.normalize: 没有 tabular_files")

        parquet_path = tabular_files[0]["path"]
        df = pd.read_parquet(parquet_path)

        from service.viz_data.introspection.df_stats import dataframe_to_column_schemas

        columns = dataframe_to_column_schemas(df)
        preview_rows = [df.columns.tolist()] + df.head(10).fillna("").values.tolist()

        tabular = TabularBlock(
            columns=columns,
            row_count=len(df),
            preview_rows=preview_rows,
            data_ref=DataRef(
                kind="parquet",
                path=str(Path(parquet_path).resolve()),
                size_bytes=Path(parquet_path).stat().st_size,
            ),
        )

        return VizDataset(
            name=self.dataset_name,
            source_kind="file",
            tabular=tabular,
            descriptor=SourceDescriptor(
                kind="file",
                label=f"JSON: {self.dataset_name}",
                logical_id=f"json_{self.file_path.stem}",
                extra={
                    "flatten": self.flatten,
                    "expand_arrays": self.expand_arrays,
                    "rows": len(df),
                    "columns": len(df.columns),
                },
            ),
        )

    def _sync_fetch(self) -> RawDataBundle:
        """同步版本 fetch（供 FolderAdapter 调用）。"""
        import asyncio

        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(self.fetch(None))
        finally:
            loop.close()

    # -------- 内部工具 --------

    def _flatten_dict(self, d: dict, parent_key: str = "", sep: str = "_") -> dict:
        """递归扁平化字典，支持嵌套 dict 和 list。

        示例：
        {"user": {"name": "A", "age": 18}, "items": [1, 2]}
        => {"user_name": "A", "user_age": 18, "items": "[1, 2]"}
        """
        items: dict = {}
        for k, v in d.items():
            new_key = f"{parent_key}{sep}{k}" if parent_key else k
            if isinstance(v, dict):
                if v:
                    items.update(self._flatten_dict(v, new_key, sep=sep))
                else:
                    items[new_key] = None  # 空 dict 转 None
            elif isinstance(v, list):
                # expand_arrays=False 时保留 JSON 字符串
                if self.expand_arrays:
                    # expand_arrays 逻辑在后续统一处理，这里先保留原 list
                    items[new_key] = v
                else:
                    items[new_key] = json.dumps(v, ensure_ascii=False)
            else:
                items[new_key] = v
        return items

    def _expand_arrays(self, objects: list[dict]) -> list[dict]:
        """把每个对象中的数组字段展开成多行。

        有多个数组字段时取笛卡尔积（与 pandas.DataFrame.explode 行为一致）。
        展开后的字段名加前缀：如 items -> item_0, item_1...

        注意：数组内的元素如果是 dict 会进一步扁平化（但不再递归）。
        """
        result: list[dict] = []
        for obj in objects:
            # 收集数组字段
            array_keys = {k for k, v in obj.items() if isinstance(v, list)}
            if not array_keys:
                result.append({k: v for k, v in obj.items() if not isinstance(v, list)})
                continue

            # 从对象中抽出数组字段，其余保留
            base = {k: v for k, v in obj.items() if k not in array_keys}
            arrays = {k: list(obj[k]) for k in array_keys}

            # 递归展开（一层一层展开，直到没有数组字段为止）
            def _explode_rec(keys: list[str], idx: int, current: dict[str, Any]):
                if idx >= len(keys):
                    result.append(dict(current))
                    return
                key = keys[idx]
                arr = arrays.get(key, [])
                if not arr:
                    # 空数组，置 None
                    for k in array_keys:
                        current[f"{self.array_column_prefix}{k}"] = None
                    _explode_rec(keys, idx + 1, current)
                elif all(isinstance(item, dict) for item in arr):
                    # 数组元素全是 dict，扁平化后合并
                    for item in arr:
                        flat_item = self._flatten_dict(item, parent_key=f"{self.array_column_prefix}{key}", sep="_")
                        merged = {**current, **flat_item}
                        _explode_rec(keys, idx + 1, merged)
                else:
                    # 非字典元素，直接作为列值
                    for item in arr:
                        current[f"{self.array_column_prefix}{key}"] = item
                        _explode_rec(keys, idx + 1, current)

            _explode_rec(list(array_keys), 0, dict(base))

        return result
