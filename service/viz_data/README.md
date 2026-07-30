# viz_data 模块开发指南

数据可视化领域的**数据接入适配器层**。所有数据源（文件、数据库、未来的网页/文章）都经由本模块转换为统一的 `VizDataset` 契约，再供 planner / chart_generator 消费。

## 分层与职责

| 目录 / 模块 | 职责 | 是否允许 IO / LLM |
|---|---|---|
| [schema.py](./schema.py) | 领域模型（`VizDataset` / `TabularBlock` / `ColumnSchema` / `RawDataBundle` / ...） | 否 |
| [capabilities.py](./capabilities.py) | 端口值对象 `AdapterCapabilities`（Adapter 能力声明） | 否 |
| [source_descriptor.py](./source_descriptor.py) | 端口值对象 `SourceDescriptor`（脱敏数据源描述） | 否 |
| [ports.py](./ports.py) | 所有 Protocol 端口汇总（`VizDataAdapterPort` / `QueryPlannerPort`） | 否 |
| [registry.py](./registry.py) | `DataSourceRegistry` + `@register_source` 装饰器 | 否 |
| [factory.py](./factory.py) | `create_adapter(request)` 门面，转发到 Registry | 否 |
| [adapters/](./adapters/) | 具体 Adapter 实现（fetch 阶段允许 IO / LLM） | fetch: 是；normalize: 否 |
| [db_drivers/](./db_drivers/) | 数据库驱动（infrastructure） | 是 |
| [planning/](./planning/) | 领域服务：`QueryPlanner` 抽象 + `LlmSqlPlanner` 实现 | 是 |
| [storage.py](./storage.py) | 临时数据存储（parquet / npz） | 是 |

## 核心契约

### `VizDataAdapter` 抽象基类（[adapters/base.py](./adapters/base.py)）

所有 Adapter 必须实现：

- `async fetch(engine) -> RawDataBundle` — **允许**发起 IO / 调 LLM
- `normalize(raw) -> VizDataset` — **禁止** IO / LLM，纯函数
- `source_kind() -> str` — 返回 `"file"` / `"database"` / `"code"` 等

建议覆盖：

- `capabilities()` — 声明能力（是否需要 LLM、是否支持多查询）
- `descriptor()` — 返回脱敏 `SourceDescriptor`（供上层派生命名/日志）
- `preview_text(dataset)` — 派生 human-readable 预览文本（默认实现基于 tabular）

### `normalize()` 契约（**强约束**）

违反视为 bug：

- ✅ 允许：从 `raw.tabular_files` 里的路径读取 parquet（"解引用"）
- ❌ 禁止：发起新的 HTTP / DB 查询 / 文件下载
- ❌ 禁止：调用 LLM / QueryEngine
- ❌ 禁止：修改传入的 `raw`
- ✅ 必须幂等：多次调用返回相同结果

真正的脏活（LLM 交互、数据抓取）必须在 `fetch` 阶段完成。

## 新增数据源的 3 步指南

假设要接入一个新数据源 `xxx`：

**1. 建 Adapter：** `adapters/xxx_adapter.py`

```python
from service.viz_data.adapters.base import VizDataAdapter, AdapterError
from service.viz_data.capabilities import AdapterCapabilities
from service.viz_data.source_descriptor import SourceDescriptor
from service.viz_data.schema import RawDataBundle, VizDataset

class XxxAdapter(VizDataAdapter):
    def __init__(self, xxx_config: dict, user_prompt: str = ""):
        self.config = xxx_config
        self.user_prompt = user_prompt

    def source_kind(self) -> str:
        return "code"  # 或自定义 kind

    def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(needs_llm=True, supports_multi_query=False)

    def descriptor(self) -> SourceDescriptor:
        return SourceDescriptor(kind="code", label="Xxx: ...", logical_id="xxx_...")

    async def fetch(self, engine) -> RawDataBundle:
        # 允许 IO / LLM
        ...

    def normalize(self, raw: RawDataBundle) -> VizDataset:
        # 纯函数
        ...
```

**2. 注册：** 在 [adapters/\_\_init\_\_.py](./adapters/__init__.py) 里加装饰器

```python
from service.viz_data.adapters.xxx_adapter import XxxAdapter

@register_source(
    name="xxx",
    priority=15,     # 数字大者优先；database=20, file=10
    matches=lambda req: bool(getattr(req, "xxx_config", None)),
)
def _build_xxx_adapter(req):
    return XxxAdapter(req.xxx_config, getattr(req, "user_prompt", ""))
```

**3. 请求 DTO：** 在 [Entity/ApiModels.py](../../Entity/ApiModels.py) 加 `xxx_config` 字段。

完成后：
- `service_main.py` 不需要改一行
- `factory.py` 不需要改一行
- 契约测试 [test_env/test_adapter_contract.py](../../test_env/test_adapter_contract.py) 会自动覆盖新 Adapter

## Do / Don't

**Do**
- 用 `@dataclass(frozen=True)` 建值对象（`Query`, `SourceDescriptor`, ...）
- Adapter 内部依赖抽象端口（`QueryPlannerPort`），便于 Fake 测试
- 敏感字段（password/token/api_key）在 `redact_*` 函数里替换成 `"***"`
- 用 `dataset.logical_id()` 派生 output_folder 命名

**Don't**
- 不要在 `factory.py` 加 if/elif —— 用 `@register_source` 装饰器
- 不要在 Adapter 里直接 `import prompts.agent_prompt` —— 通过 QueryPlanner 抽象
- 不要把 `db_config` 或绝对路径塞进 `SourceDescriptor.label` —— 会泄漏到日志
- 不要在 `normalize` 里发起新 IO —— 会破坏纯函数契约

## 相关文档

- 重构原始计划：[.claude/my_files/ddd模式重构/plan_adapter_ddd.md](../../.claude/my_files/ddd模式重构/plan_adapter_ddd.md)
- 多源数据早期设计：[.claude/my_files/多源数据适配/plan_multi_source.md](../../.claude/my_files/多源数据适配/plan_multi_source.md)
