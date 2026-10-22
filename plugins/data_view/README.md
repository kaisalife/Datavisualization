# 数据视图插件目录

数据视图层（`service/data_view/`）的唯一扩展点。每个 `<name>.py` 必须暴露：

```python
VERSION = 1            # int：函数语义改动必须递增，否则旧缓存继续命中旧结果
OUTPUT_SCHEMA = [...]  # 可选；声明后引擎执行后会按它校验输出列

def apply(df, params):
    """纯函数：只用 df 和 params，返回新 DataFrame。"""
```

## 纯函数契约（注册时静态扫描）

- 输入只有 `df` 和 `params`；禁止读盘 / 网络 / 随机 / 当前时间；
- 所有影响行为的量（窗口大小、阈值、字段名映射）都从 `params` 显式传入；
- 不修改传入的 `df`（返回 copy 或新对象）；
- 输出必须稳定有序（同一输入永远产出同一行序），排序由插件自己保证。

命中 `import random` / `open(` / `requests` / `datetime.now` 等禁用 token 的插件
会被拒绝登记（`PLUGIN_FORBIDDEN`），失败原因记入日志、不影响其他插件。

## 与 spec 的关系

插件不进 plan，也不进生成代码：LLM 只产出
`ViewSpec(kind="plugin", plugin=name, plugin_version=VERSION, params=..., inputs=[...])`，
由引擎调用 `apply`。阶段产物（`vw_<hash>` parquet / manifest）与 SQL 视图完全同构。

当前为空目录是正常状态（P0 骨架不带内置插件）；P1 按真实场景需要再沉淀第一个插件。
