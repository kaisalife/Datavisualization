"""数据视图层（DataView）：声明式、确定性、可缓存的派生数据变换。

对外最小 API：

```python
from service.data_view import ViewSpec, DataViewEngine

spec = ViewSpec(kind="sql", inputs=["table_0"],
                sql="select 月份, sum(销售额) as 销售额 from table_0 group by 月份 order by 月份")
result = DataViewEngine().execute(spec, {"table_0": df}, mode="materialize",
                                  datasets_dir=datasets_dir)
result.view_id   # vw_<hex16>，同一 spec + 同一数据 + 同一引擎版本必得同一 id
```

设计文档：``docs/数据清洗工具集/03-数据视图设计.md``。
"""
from __future__ import annotations

try:  # 包导入 / 脚本直跑双写法
    from spec import (  # noqa: F401
        DATA_VIEW_VERSION,
        DataViewError,
        ViewSpec,
        payload_of,
        spec_hash,
        spec_summary,
        validate_spec,
        view_id,
        SPEC_INVALID,
        WRITE_STATEMENT_REJECTED,
        UNORDERED_OUTPUT,
        PLUGIN_NOT_FOUND,
        PLUGIN_FORBIDDEN,
        EXEC_ERROR,
        SCHEMA_MISMATCH,
        EMPTY_RESULT,
        ROW_LIMIT_EXCEEDED,
        INPUT_NOT_FOUND,
        INPUT_INVALID,
    )
    from engine import (  # noqa: F401
        DEFAULT_MAX_ROWS,
        DataViewEngine,
        DataViewResult,
        ViewSchemaColumn,
        fingerprint_dataframe,
    )
    from cache import (  # noqa: F401
        list_views,
        load_cached,
        materialize_view,
        views_dir,
    )
    from registry import (  # noqa: F401
        PluginEntry,
        PluginRegistry,
        get_default_registry,
        set_default_registry,
    )
except ImportError:  # pragma: no cover - 兼容直接运行
    from .spec import (  # type: ignore # noqa: F401
        DATA_VIEW_VERSION,
        DataViewError,
        ViewSpec,
        payload_of,
        spec_hash,
        spec_summary,
        validate_spec,
        view_id,
        SPEC_INVALID,
        WRITE_STATEMENT_REJECTED,
        UNORDERED_OUTPUT,
        PLUGIN_NOT_FOUND,
        PLUGIN_FORBIDDEN,
        EXEC_ERROR,
        SCHEMA_MISMATCH,
        EMPTY_RESULT,
        ROW_LIMIT_EXCEEDED,
        INPUT_NOT_FOUND,
        INPUT_INVALID,
    )
    from .engine import (  # type: ignore # noqa: F401
        DEFAULT_MAX_ROWS,
        DataViewEngine,
        DataViewResult,
        ViewSchemaColumn,
        fingerprint_dataframe,
    )
    from .cache import (  # type: ignore # noqa: F401
        list_views,
        load_cached,
        materialize_view,
        views_dir,
    )
    from .registry import (  # type: ignore # noqa: F401
        PluginEntry,
        PluginRegistry,
        get_default_registry,
        set_default_registry,
    )
