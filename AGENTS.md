# AGENTS.md - 数据可视化服务项目规范

本文件是项目级记忆：记录已踩过的坑与现有技术规范，帮助后续会话快速上手且不破坏既有设计。
根目录没有 README，文档在 `docs/`（部分已过期，见文末）。

## 一句话架构

`app.py`（Flask）收任务 → `service/pipeline/service_main.py` 编排 → `viz_mode=agent/auto`（默认）走
`agent_pipeline.py` 的 LLM 自主规划，其余 `legacy/chart/scientific` 走固定 plan → generate → debug
→ 产物落到 `runtime/charts/<数据集名>/`。
前端 `front-winui/` 是 Rust（winio WinUI3）外壳 + 编译期内嵌的 HTML/JS；JS 不能直接访问后端，必须经本地桥接发回 Rust。

## 版本与提交（重要）

- 每交付一版改动就**在本地提交一次**：`git add -A; git commit -m "<中文摘要>"`。
- **不要 `git push`**：不要发布到远程，何时推送由用户决定。
- 提交前扫一眼 `git status`：`tests/.env`（真实模型凭证）、`front-winui/settings.json`、`runtime/`
  必须不在列表里，三者都在 `.gitignore`。

## 常用命令

### 后端

```powershell
# 项目根目录，使用已有 venv（不要用 uv sync，见下文）
.venv\Scripts\python.exe app.py       # 监听 0.0.0.0:5000，自动 load_dotenv()
```

- 首次启动要 import torch / chromadb，约 30–60 秒；**重定向输出时 stdout 是缓冲的，没有输出不代表失败**。
  以 5000 端口是否 LISTEN 为准：`Get-NetTCPConnection -State Listen -LocalPort 5000`
- 启动耗时**不是**优化目标（按服务方式部署，启动次数很少）；别为提速牺牲可读性
- 健康检查：`GET /api/health`（存活，不鉴权）、`GET /api/ready`（目录可写 + 对话库可用，未就绪 503）
- 项目已以 editable 方式装在 venv 里，改代码无需重装
- **Windows 上 Werkzeug 会设 `SO_REUSEADDR`，两个后端进程可以同时绑定 5000**：请求会随机落到
  不同的进程，表现为刚提交的任务立刻 `404 Task not found`（任务在另一个进程的内存里）、
  `/api/health` 的 `tasks.total` 忽高忽低。起服务前先确认只有一个监听进程：
  `Get-NetTCPConnection -State Listen -LocalPort 5000`（多行 = 有重复实例，先停掉多余的）

### 测试

```powershell
# venv 已装好 pytest / pytest-asyncio；换机器时再装
.venv\Scripts\python.exe -m pip install pytest pytest-asyncio pytest-cov

.venv\Scripts\python.exe -m pytest -q                                     # 免 LLM 全集（当前 343 passed / 21 deselected）
.venv\Scripts\python.exe -m pytest tests/test_refactor_smoke.py -q         # 接入/plan 冒烟
.venv\Scripts\python.exe -m pytest tests/test_multimodal_tabularize.py -q  # 多模态抽表（假模型，含错误分支）
.venv\Scripts\python.exe -m pytest tests/test_service_hardening.py -q      # 探针 + 任务回收
.venv\Scripts\python.exe -m pytest tests/test_chart_prompt_rules.py tests/test_llm_headers.py tests/test_query_engine_usage.py -q   # prompt 规则 / 网关请求头 / token 计量
.venv\Scripts\python.exe -m pytest tests/test_file/test_end_to_end.py -o addopts="" -m "needs_llm and integration" -q   # 真模型
```

`pytest.ini` 的 `addopts` 默认 `-m "not needs_llm and not needs_network"`；跑真模型测试要
`-o addopts=""` 并显式带标记。`asyncio_mode = auto`，异步测试不用手写 marker。
新增测试放 `tests/`，共享 fixture 在 `tests/conftest.py`。

### 真实模型与表格效果评估

`tests/.env`（**已 gitignore，放真实凭证，绝不提交**）配 `TEST_LLM_BASE_URL` / `TEST_LLM_API_KEY` /
`TEST_LLM_MODEL`，由 `tests/conftest.py` 的 `test_llm` fixture 读取；当前是
`https://opencode.ai/zen/go/v1` + `deepseek-v4.1-flash`。

```powershell
.venv\Scripts\python.exe -m pytest tests/test_table_generation_eval.py -o addopts="" -m "needs_llm and needs_network" -q -s
```

- **该网关必须带 `x-opencode-session` 头**（任意 UUID，每次请求一个），否则 400 `MissingSessionID`。
  直接拿它做 OpenAI 兼容调用时要自己加；`tests/conftest.py` 已注入。服务侧用同类网关时设
  `LLM_EXTRA_HEADERS`（JSON），`BaseAgent` / 多模态 / LLM 表格化 / 报告生成都会带上；Agent 输出上限用
  `AGENT_MAX_TOKENS`（推理模型同样要留足）。
- **根 `.env` 可能是半套配置**（有 `BASE_URL`/`MODEL_NAME`、`API_KEY` 为空）。`tests/test_file/conftest.py`
  必须整组回退到 `tests/.env`，不能逐项用 `or` 拼接，否则会把 opencode 的 key 发到 bigmodel 网关，
  表现为 401“令牌已过期”，但直接调用 opencode 却成功。fixture 还会用新 UUID **覆盖**根 `.env` 里
  残留的占位 `LLM_EXTRA_HEADERS`（保留其他自定义头）。
- **新增任何 `ChatOpenAI` 构造点都要带** `default_headers=get_llm_extra_headers() or None`
  （`service/runtime/utils.py`），否则自定义网关直接 400。`get_env_int()` 也在这里，别再写本地小工具。
- `deepseek-v4.1-flash` 是**推理模型**：`reasoning_tokens` 也占 `max_tokens`，给小了会
  `finish_reason=length` 且 `content` 为空（内容都在 `reasoning_content` 里）。所以测试给
  `TEST_LLM_MAX_TOKENS=12000`；服务侧对应 `VISION_MAX_TOKENS`，被推理耗尽时 reader 会报错点名它。
- 该模型**支持视觉**，可直接跑图片 → 表格评估。
- **thinking 模式 + 工具多轮**有坑：网关要求把上一轮的 `reasoning_content` 原样回传，而
  `langchain-openai` 明确不提取该字段，debug agent 偶尔收到 400
  `The reasoning_content in the thinking mode must be passed back`；`chart_generator` 已兜底为
  "退回 prompt 重试"，任务仍能成功。
- 评估口径是"能不能直接支撑画图"，不是逐字一致：列名双向包含即命中，数值按容差比（图表估读 ±12%）。
  基线 13/13：Markdown 表、日志、表格截图、柱状图估读（误差约 2%）、无表格图不臆造、合并单元格下填、多表选主表、docx 内嵌表格截图、一图多表全抽、HEIC 照片、扫描版 PDF、PDF 多页（`_p1`/`_p2`）、pptx 内嵌表格截图。
- 造图用 Pillow + `C:\Windows\Fonts\msyh.ttc`（否则中文渲染成方框）；"无表格"用例用渐变图检验不臆造。
- 改了多模态 prompt / reader 后，先在 `-s` 下看真实输出，再决定阈值和是否调 prompt；别只跑假模型单测就收工。

### 前端

```powershell
cd front-winui
cargo build --target x86_64-pc-windows-gnu           # 本机只有 GNU 工具链，见下
powershell -ExecutionPolicy Bypass -File scripts\setup-windows-app-runtime.ps1 -Clean
$env:BACKEND_URL="http://localhost:5000"
.\target\x86_64-pc-windows-gnu\debug\datavisual-winui.exe
```

## 前端专属坑（都实际踩过）

1. **必须准备 WinUI3 运行库**。`winio` 的 `winui` 后端在非 MSIX 场景要靠"把 WindowsAppRuntime 框架包
   挂进进程"完成 WinRT 类注册：
   - exe 旁没有运行库 → 启动即退，`Error(找不到指定的模块。(0x8007007E))`
   - exe 旁放了 `Microsoft.ui.xaml.dll` → `winio` 误判已就绪、跳过注入，崩溃 `0x80040154`（没有注册类；
     事件日志表现为 `Microsoft.ui.xaml.dll` + `0xc000027b`）
   - 唯一正确做法是跑 `scripts/setup-windows-app-runtime.ps1`（只拷 4 个文件，刻意不拷 XAML 主 DLL）。
     **每次 `cargo clean` 后都要重跑**
2. 该脚本必须保存为 **UTF-8 with BOM**，否则 PowerShell 5.1 按 GBK 解析中文会报语法错误。
3. `front-winui/.cargo/config.toml` 写死 `target = "x86_64-pc-windows-msvc"`。本机没有 MSVC 工具链时
   `cargo build` 直接失败，必须显式 `--target x86_64-pc-windows-gnu`（产物路径多一层 target 目录）。
4. **没有热重载**：`app.html` / `app.css` / `js/*.js` 由 `include_str!` 编译进二进制（`src/component.rs`），
   改前端资源必须重新 `cargo build`。
5. **JS ↔ Rust 桥**：JS 只能 `fetch("http://127.0.0.1:<随机端口>/api", {method:"POST", body:{action,data}})`，
   由 `src/handlers.rs` 分发；对后端的 HTTP 调用集中在 `src/api/client.rs`。新增交互要同时改 JS + handlers
   （必要时加 `api/types.rs`）。
6. **配置优先级**：`AppSettings::load()` 先读 `front-winui/settings.json`（已 gitignore），不存在才用
   `BACKEND_URL` / `API_KEY` / `MODEL_*` 环境变量。改环境变量前先删或改 settings.json，否则不生效。
7. **数据预览面板**：输入框旁「预览」按钮把当前文件/数据库/API 配置经 `previewData` 交给 Rust，Rust 同步调
   `POST /api/data-profile`（图片/PDF 会走视觉模型，可能耗时几十秒；数据库/API 用 `db_config` /
   `api_config` JSON 表单字段），再把返回 JSON 交给 `js/preview.js` 的 `window.app.showDataPreview` 渲染。
   下载按钮走 `downloadDataExport`，Rust 只接受
   `/api/data-profile/export` 开头的相对地址，落盘到 `%USERPROFILE%\Downloads`（同名自动加序号）。
   预览面板的原始表依赖 `/api/data-profile` 的 `save_raw=True`；图表任务本身仍不保存原始表。
8. **上下文卡片「补充说明」**：计划卡带待确认项时，`js/charts.js` 会渲染按钮，点击后从
   `state.lastFiles` 恢复本次数据源并填入“在…基础上调整：”；`sendPrompt` 发送前会保存
   `state.files` 的浅拷贝，`newChat` 清空。不要假设任务结束后 `state.files` 还在。
   历史对话恢复时传 `interactive:false`，避免把当前 `lastFiles` 套到旧任务上。
9. **剪贴板截图**：`js/preview.js` 监听 `paste`，把图片读成 data URL 经 `saveClipboardImage` 交给 Rust；
   Rust 解码（上限 8MB）后写到 `%TEMP%\datavisual_clipboard`，再回调 `window.app.addClipboardFile(path)`
   加入文件列表。剪贴板同时带文本（Excel/网页复制单元格）且在输入框内粘贴时，保留正常文本粘贴。

## 依赖约束（不要随手升级）

- `langchain-mcp-adapters 0.3.x` 要求 `mcp<2`；`mcp 2.x` 删除了 `mcp.shared.context.RequestContext`，
  升级后 `agent` 直接 ImportError，后端起不来。
- `fastmcp 4.x` 强制依赖 `mcp 2.x`，因此 `fastmcp` 必须留在 `3.4.x`。
- 已验证可用组合（已写入 `pyproject.toml` 与 `uv.lock`）：
  `langchain-core 1.6.12` / `langchain-openai 1.7.2` / `langchain-community 0.4.2` /
  `langchain-classic 1.0.8` / `langchain-text-splitters 1.1.3` / `langchain-mcp-adapters 0.3.2` /
  `mcp 1.30.0` / `fastmcp 3.4.9` / `pandas 2.3.3` / `pyarrow 26.0.0` / `pillow-heif 1.8.1`
- **`pyarrow` 是硬依赖**：series 全程用 `.parquet`（`splitter.py` 写、注入代码读），缺了主流程必挂
  （`get_engine` 报 "Unable to find a usable engine"）。安装后 `pandas.to_parquet/read_parquet` 自动选它。
- 本机直连 pypi.org 只有 15–20 kB/s；**用清华镜像快 100 倍以上**（实测 5.3 MB/s）：
  - 装包：`.venv\Scripts\python.exe -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple <pkg>`
  - 改锁文件：`$env:UV_INDEX_URL="https://pypi.tuna.tsinghua.edu.cn/simple"; uv lock`
    （加镜像后 uv 不再卡死，几分钟内可完成；生成的 `uv.lock` 会记录该镜像地址）
  - 加/改依赖顺序：先改 `pyproject.toml` → 用 pip 装好 → `uv lock`（或 `uv lock --offline` 走本地缓存）
  - uv 创建的 venv 默认没有 pip，必要时 `.venv\Scripts\python.exe -m ensurepip`
- `langchain-community` 已进入 sunset 状态（导入时有 DeprecationWarning），但 `Chroma` / document loaders
  仍在用；迁移到独立包属于额外工作，不要顺手改。

## 目录与职责

| 路径 | 职责 |
|---|---|
| `app.py` | Flask 入口：全局错误处理、蓝图注册、WebSocket `/ws/task/<id>`、`/ws/trace/<id>` |
| `api/*_api.py` | 各领域接口；共享依赖经 `api/common.py:init_app()` 注入，用 `current_app.config[...]` 取，不要跨模块 import 全局。`db_config`/`api_config` 表单解析与校验统一走 `api/source_config.py` |
| `service/pipeline/` | 编排：`service_main`、`agent_pipeline`、`plan_*`、`chart_generator/debugger/executor/sandbox` |
| `service/data_ingestion/` | `router` → `readers/`（Excel/CSV/DB/文档/LLM 表格化/**多模态**）→ `profiler` → `series/`（切分 + parquet） |
| `service/runtime/` | 配置、异常、常量、会话存储、`runtime_cleanup` |
| `service/monitoring/`、`service/observability/` | trace / 耗时 / 错误监控、structlog 日志 |
| `agent/`、`agent_tools/` | `BaseAgent`（LangChain + MCP）、`run_code` 沙箱工具 |
| `RAG/` | Chroma 知识库；`RAG/basic_author_knowleage/` 是第三方参考代码，**不要改** |
| `front-winui/src/` | Rust 外壳（`component.rs` / `handlers.rs` / `api/client.rs`）+ 内嵌前端资源 |

新增 API 的固定步骤：路由写进 `api/xxx_api.py` → 在 `api/__init__.py` 导出 Blueprint →
`app.py` 里 `app.register_blueprint` → 更新 `api/README.md` 的接口表。

`agent_tools/tool_run_code.py` 跑在独立 MCP 进程里（stdio）。`configs/default_config.json` 里的
`"command": "python"` 会被 `service/runtime/config.py` 自动替换为当前解释器绝对路径。

## RAG 知识库（Qwen3-Embedding-0.6B）

- 模型放在 `D:/myLangchain/QwenEmbedding`（`QWEN_EMBEDDING_PATH`），Qwen3-Embedding-0.6B，
  1024 维，`model.safetensors` 约 1.1 GB；知识库是 `RAG/RAG_Data` 下 177 篇 pyecharts Markdown。
- 下载（本机 `huggingface.co` 不通，走镜像）：
  `HF_ENDPOINT=https://hf-mirror.com HF_HUB_DISABLE_XET=1 hf download Qwen/Qwen3-Embedding-0.6B --local-dir D:/myLangchain/QwenEmbedding`
  **必须关 Xet**（`HF_HUB_DISABLE_XET=1`），否则会绕过镜像直连 `cas-server.xethub.hf.co` 报 401。
- **CPU 上必须 fp32**：模型 `config.json` 是 `bfloat16`，CPU 没有原生 bf16 指令，直接加载慢约 10 倍
  （实测 32 条 500-token 文本要 8 分钟）；`SentenceTransformerEmbeddings` 已在 CPU 强制
  `torch_dtype=float32`。本机 torch 是 `+cpu`，没有 CUDA。
- 177 篇切完约 **398 个 chunk / 10.7 万 token**（平均 271、最长 1296）。首次启动建库在 CPU 上约
  30–40 分钟（`RAG_EMBED_BATCH_SIZE=8`、`RAG_MAX_SEQ_LENGTH=1024`、按长度排序分批减少 padding），
  建好后持久化到 `runtime/chroma`，之后只做 query（短查询约 0.8 秒）。**换 embedding 模型必须删/改名
  `runtime/chroma`**，代码会检查维度并给出明确报错。建库是边算边写，**中途中断会留下部分向量**
  （代码只识别 0 条的空库），中断后务必删掉 `runtime/chroma` 重来。
- **新增/改动文档不必全量重建**：`RAG/sync_index.py` 按 `source` 元数据增量 upsert
  （`.venv\Scripts\python.exe -m RAG.sync_index --missing` 只补缺失文件；显式给文件/目录则覆盖，
  `--prune` 清理源文件已删除的条目）。切分器抽成 `RAG_main.split_documents` / `SPLIT_SEPARATORS`，
  增量同步与建库必须共用，否则 chunk 边界不一致。已补 `RAG/RAG_Data/Scatter/scatter_base.md`
  （原先 `Scatter` 只能命中 `effectscatter_base.md`），当前 400 条向量。
- 已验证检索质量：`柱状图 标题设置`、`Grid 多图组合` 等查询能命中对应示例文档。
- 图表生成检索走 `service/pipeline/chart_rag.py`：query 用「中文功能词 + 英文类型名」
  （如 `柱状图 Bar 基础 多系列 示例`、`Grid 网格布局 GridOpts 多图组合 垂直布局 水平布局`），
  **不拼业务标题**（会稀释 embedding）；未知类型回退到 `<类型> 图表示例`。回归 `tests/test_chart_rag.py`。
- 检索器用 `get_default_retriever()` 进程内复用（模型约 2.4 GB、加载约 8 秒）；`agent_pipeline` 与
  `chart_executor` 都走它，不要再直接 `RAGRetriever()`，并发任务会把内存吃满。

## 图表生成规范

- 只用 `pyecharts`；禁止 matplotlib / seaborn / plotly
- 优先 Line / Bar / Scatter / Pie / HeatMap / Grid（多图组合）
- 每个图表独立 HTML，用 `.render()` 落盘
- 中文标题/轴标签；默认 `opts.InitOpts(width="900px", height="500px")` + `ThemeType.LIGHT`
- 选项类**必须带 `opts.` 前缀**（裸写 `InitOpts(` 会 NameError，真机踩过）；回归测试见
  `tests/test_chart_prompt_rules.py`
- `ThemeType` 在 `pyecharts.globals`，不是 `opts.ThemeType`；Grid 边距只能走
  `Grid(...).add(chart, grid_opts=opts.GridOpts(...))`，`set_global_opts()` 没有 `grid_opts`
  （以上三条都是真机 debug 循环里踩出来的）
- 这些规则写在 `prompts/chart_gen_prompt.py`，改规则要同时改 prompt 和该测试
- **pyecharts 2.1 没有 `BarOpts` / `LineOpts`**：柱宽用 `add_yaxis(..., bar_max_width=42)`，
  折线点标记用 `add_yaxis(..., is_symbol_show=False)`；`tests/test_chart_prompt_rules.py`
  会扫描 prompt 中所有 `opts.XxxOpts` 并确认在当前版本真实存在，别写不存在的选项类
- **矩形树图的类名是 `TreeMap`（大写 M）**，不是 `Treemap`；plan 里的 `chart_type` 仍写 `Treemap`，
  生成代码必须 `from pyecharts.charts import TreeMap`，否则 ImportError（已有 prompt 回归）
- `Histogram` 用 `pd.cut` + `Bar`；分箱数按样本量
  `min(10, max(4, int(len(values) ** 0.5)))`，不要固定 8/10 箱（小样本遇离群值会大量空柱）
- `Boxplot` 叠加散点时，所有散点共用同一个 x 类目，不要 `add_xaxis([指标名] * n)`；
  同位置 Grid 子图的重复坐标轴/图例由 `chart_polish` 合并

### 图表视觉质量后处理

`service/pipeline/chart_polish.py` 在 `chart_sandbox` 的 render monkey-patch 中、落盘前
统一润色 `chart.options`，只补缺失项/修正明显不合理的默认值，不覆盖用户显式配色、标签位置和
自定义 tooltip。规则：

- 统一 Tableau 10 调色板（`set_colors` 显式配置优先）；中文无衬线字体；标题居中 + 2% 顶距
- x 轴名称默认贴右端（`nameLocation="end"`）会被画布裁掉：统一改为居中，并按类目标签旋转角度
  补 `nameGap`（无旋转 30、30°/45°/60° 依次 64/72/81）；有轴名时底部预留 16%，标签旋转时 20%
- 默认顶部居中图例与标题必然重叠时移到下方，并按标题/图例宽度估算右上角是否撞车；单图
  `grid.containLabel=True`，补 top/bottom 边距，避免轴标签被裁切
- 数值轴/数据标签/tooltip 用 `toLocaleString('zh-CN')` 加千分位；tooltip 默认柱/折线用
  `axis` 联动（自定义 formatter 时保留 `item`）；柱状图/直方图默认隐藏 0 值数据标签，
  避免稀疏分箱时一排 0 把画布塞满
- 柱状图标签默认 `top`（横向 `right`、堆叠 `inside`），柱宽上限 42；饼图默认半径 32%–58%、
  标签 `{b}: {d}%`、`avoidLabelOverlap=True`
- 类目点过多时自动隐藏标签（折线/柱 >20、饼 >15；多系列总点数 >20），折线 >30 点关闭
  `showSymbol`；长 x 轴类目按宽度估算旋转 30/45/60°，横向柱状图长类目截断到 140px
- 单层矩形树图隐藏冗余的 breadcrumb / upperLabel / 单 series 图例（否则会压住标题），
  并补 `top=14%`、`bottom=4%`；标签默认深色 + 浅色描边，显式白字则补深色描边，
  黄/粉块也能读清
- **同位置叠加的 Grid 子图会合并坐标轴**：pyecharts 的 `Grid.add` 给每个子图各建
  xAxis/yAxis，箱线图叠加散点时会出现重复类目标签、双份 y 轴刻度和两组图例。
  `chart_polish` 只在 Grid 位置完全相同、轴类型/轴名称兼容时，把 series 重映射到
  第 0 套轴并隐藏多余轴、合并图例；真正的上下多图或双轴图不动
- **`polish_options` 内部先深拷贝**：pyecharts 的默认 `LabelOpts` / `SplitLineOpts` 等可能被
  多张图共享，直接改会让上一张图的颜色/位置泄漏到下一张图；深拷贝后再写回原 `chart.options`
- 回归：`tests/test_chart_polish.py`（含渲染链路 HTML 断言）；改规则要同时改 prompt 和该测试

### 图表数据检查（渲染后、成功前）

`service/pipeline/chart_data_check.py` 在 `chart_sandbox` 的 render monkey-patch 中读取
`chart.options`，统计每个 series 的数据点数/空值/数值/0 值，用 `__CHART_DATA_STATS__` 标记
经 stdout 回传，父进程剥离标记后放进 `SandboxResult.data_stats`。`generation_validation.runtime_report`
再据此判断：

- series 缺失、0 个数据点、全部为空 -> `CHART_DATA_EMPTY` / `CHART_DATA_ALL_NULL`（可修复错误，
  触发 debug 重试，不会静默产出空图）；
- 过半数据点为空 -> `CHART_DATA_MOSTLY_EMPTY`（警告）；
- 所有数值都等于 0 -> `CHART_DATA_ALL_ZERO`（警告，不阻断）；
- 实际 series 类型完全不含 `plan.chart_type` -> `CHART_TYPE_MISMATCH`（警告；Histogram→bar、
  Area→line、Scatter→effectscatter 等别名不算偏离；Boxplot+Scatter 叠加观测值、Bar+Line
  双轴等辅助层只要包含计划类型就不算偏离）；
- 使用 `dataset` 的图表跳过空数据判断，避免误伤。

统计摘要写入 `report["data"]`。回归：`tests/test_chart_data_check.py`、
`tests/test_generation_validation.py`。**不要**在沙箱里用 HTML 正则猜数据，options 才是真相。

## 图表类型选择（数据驱动，避免每回柱状图）

默认 `viz_mode=agent/auto` 走 `prompts/agent_planning_prompt.py`。图表类型不再只靠模型自由发挥：

- `service/data_ingestion/series/shape.py` 在 series 落盘时计算 `extra_semantics.shape`
  （`rows` / `row_labels` / `measure_count` / `numeric_columns` / `time_like` / `non_negative` /
  `row_label_examples` 等），`SeriesCatalog.to_index_prompt()` 直接带
  `12 个时间点 × 2 个指标；建议 Line/Area（备选 Bar）`，规划阶段不用再读 parquet。
- `service/pipeline/chart_recommend.py`：
  - `recommend_chart_types()` 结合数据形态 + 用户意图给出首选/备选；`list_series` / `get_series`
    工具输出直接展示；`create_plan` 对明显不匹配（如 12 个点的时间序列画 Bar）当场提示；
  - `diversify_plans()` 在规划完成后做确定性守护：时间序列（≥3 个点；用户明确要“趋势”时 ≥2 个点）
    的 Bar/Pie 安全改成 Line/Area；≤6 个非负类别且没有构成图时补 Pie，7–20 个非负类别补 Treemap；
    同一 series + 同一指标不重复；同一分析角度最多 2 张；**保留 LLM 已规划的有效图**
    （如 Bar+Scatter 不会为了凑构成图被硬改成 Pie）；
  - 没有行标签、只有一列数值的 generic series 按“一组观测值”处理，推荐并为分布补 Histogram/Boxplot，
    不再强行当类别柱状图；
  - 用户明确点名类型（“柱状图”“饼图”…）不自动改；用户说“画两个图”是硬上限；数据只支持一个角度时宁可少画。
- prompt 同步：`agent_planning_prompt`（默认路径）、`chart_designer_prompt`（回退）、
  `chart_gen_prompt` 的类型实现约定（Area / Histogram / Boxplot / Treemap / Heatmap）。
- **ChatPromptTemplate 花括号坑**：prompt 里的 JSON 示例、`formatter="{b}: {d}%"` 必须写成
  `{{...}}`，否则模板把 `b/d` 当变量，生成阶段直接 `KeyError`。回归
  `tests/test_chart_prompt_rules.py::test_generate_prompt_template_can_be_formatted`。
- 真机规划验过：12 个月月度数据产出 Area / Line / Scatter / Histogram；6 城市数据产出 Bar + Pie；
  10 城市数据产出 Bar + TreeMap，单列销售额产出 Boxplot + 观测散点
  （`tests/test_file/test_chart_variety_e2e.py`），不再全是柱状图。
  Area / Histogram / TreeMap / Boxplot 单图生成均成功（每张约 30–65 秒）。
- 回归：`tests/test_series_shape.py`、`tests/test_chart_selection.py`、`tests/test_chart_prompt_rules.py`。

## Excel 合并表头 / 标题行

中文报表常见「一行合并大标题 + 两行合并表头」。`ExcelReader` 对 xlsx/xlsm 直接从 zip XML 读合并区域
（不加载整个 openpyxl 工作簿），.xls 用 xlrd 的 `merged_cells`（读取失败自动退回 pandas），再决定怎么读：

- 顶部跨列的单值合并行（如 `A1:E1`「2024 年销售报表」）→ 当标题跳过，最多 2 行；
- 表头自身有纵向/横向合并（如 `B1:C1`「2023 年」+ `B2`「销售额」）→ 把 2–3 行表头压成单行，
  用 `_` 连接成 `2023 年_销售额`；纵向合并产生的重复值会去重（`城市` 不会变 `城市_城市`）；
- 没有合并、靠空白格表达的两行表头也能识别（第二行首列为空、非空值更多、全文字，且第三行有数字）；
  不满足这些条件就按普通表处理，不会吃掉数据行；
- 合并区域必须**与首行表头相交**才触发**表头压缩**；数据区里的合并单元格不改变表头，
  但纵向合并的**文本**（如 `城市` 跨多行）会在读取后向下填满；数值合并（合计/小计）不填，
  避免重复计量；
- 没有表头问题的文件只多一次 4 行 peek；有数据区纵向合并时按合并区域补全文本；
- **封面页 / 空白页自动跳过**：只有标题、0 行数据或全空行的 sheet 不进入 RawTable，避免主表变成
  「0 行 1 列的大标题」；跳过后按剩余 sheet 重新编号（`<文件名>`、`<文件名>_sheet2`…）。
  所有 sheet 都为空时抛「没有可读取的数据」，让 chart-only 工作簿走 router 的内嵌图片兜底；
  显式 `sheet_name=` 时保持原行为（空表照常返回）；
- 实测 1 万行合并表头 0.85 秒、2 万行普通表 3.5–4 秒（比原先 openpyxl 全量加载 + pandas 双读快约 30%）。

实现：`service/data_ingestion/readers/excel_reader.py`；回归 `tests/test_excel_reader.py`
（两行表头、标题行、空白格表头、正常表、数据区合并、多 sheet、xlsm、ingest 全链路，
以及 `tests/fixtures/legacy_merged.xls` 真实 .xls 夹具）。

## 数值文本与列语义

`service/data_ingestion/normalize.py` 在 profiling / series 拆分前统一跑一遍：

- 整列都是 `1,200` / `12.5%` / `(1,200)` / `¥1,200` / `1.234,56` / 全角数字时转成数值；
  **任何一个值解析失败就整列保留原样**，不做部分转换；
- 逗号按「3 位分组 = 千分位、1–2 位 = 欧式小数逗号」判断：`1,200` → 1200，`1,5` → 1.5，
  `1,2,3` 这种无法判断的整列保持原样；
- 列名像编号（`编号`/`order_id`/`phone`…）不转；`00123`、无分隔符的 12 位以上长数字保留字符串；
- 带单位（`1,200 万元`）不转，避免丢失量纲；
- 空值占位符（`—`/`暂无`/`N/A`）在其余值都是数字时变成 NaN。

`profiler._is_time_label()` 只把 `2023 年` / `1 月` / `年份` / `order_date` 这类列名当时间轴；
`2023 年_销售额`、`销售额_2023`、`year_sales` 是指标（否则宽表会被错误拆成「指标×时间」）。
`_is_id_label()` 按英文整词匹配，`width` 不会因为含 `id` 被当成编号。

回归：`tests/test_numeric_coercion.py`、`tests/test_series_split.py`。

## 数据库读取

`DatabaseReader` 入口统一把 `db_type` 去空格、转小写，并把 `postgres` 归一到 `postgresql`：前端设置里
默认发的是 `MySQL` / `PostgreSQL`，不能直接拿原值去比较。表名按方言引用（MySQL 反引号，其余双引号），
连接串用 SQLAlchemy `URL.create` 转义账号密码里的 `@/:?#`；未显式指定表名时自动列举的表也用**真实表名**
（不会退化成 `data`）。回归见 `tests/test_database_reader.py`。

前端设置里的数据库连接可填「表名」（逗号/分号分隔，Rust 侧序列化成 JSON 数组，后端也兼容字符串
并统一归一化）或「自定义 SQL」（优先于表名），留空则读取全部表；这两个字段同时作用于预览和图表任务。

自定义 SQL 统一经 `service/data_ingestion/sql_safety.py` 的 `ensure_read_only()` 校验：只接受单条
`SELECT` / `VALUES` / `SHOW` / `EXPLAIN` / `DESCRIBE`，或主语句仍是 `SELECT` 的 `WITH` CTE；写操作、
DDL、多语句（`select 1; drop table x`）在 `validate_source_configs` 阶段就返回 400，`DatabaseReader.read`
执行前再校验一次（防绕过）。校验前会剥离字符串字面量和注释，`WHERE note = 'a;b'` 不会被误判。
回归见 `tests/test_sql_safety.py`。

设置面板的「测试连接」走 `POST /api/data-source/db-tables`（`DatabaseReader.list_tables`，建连超时 5 秒），
返回排好序的表名，点击 chip 可填入「表名」：连接失败返回 502，配置非法（含 sqlite 文件不存在）返回 400。
**sqlite 必须是已存在的文件**——`sqlite3.connect` 会自动建空库，`_make_engine` 提前拦截，避免路径写错时
悄悄生成一个空数据库。设置面板新增连接只列后端支持的三种方言，历史配置里的 SQL Server 仍保留原值
（标记「暂不支持」），不会在编辑时被静默改成 MySQL。回归见 `tests/test_db_tables_api.py`。

## 表头清洗

`_assemble_profile` 在数值归一化 / 拆 series 前统一清洗列名：去首尾空白、换行/制表符压成空格、
重复列名加 `.1`/`.2` 后缀；MultiIndex 列保持原样。手写 CSV 的 `" 城市 "` 不会再让列语义识别失败，
也不会让 parquet 因重复列名报错。回归 `tests/test_column_normalization.py`。

## Series 拆分：长表透视

`城市 / 月份 / 销售额` 这类「时间 + 维度 + 指标」长表，不再把不同城市混成一条时间线：

- 维度类别 ≤12：透视成 `时间 × 类别` 宽表，一条 series 多列（多折线）；
- 类别 >12：按维度聚合排行（率/均价取平均，其余求和），最多 20 行；
- 多个指标每个一条 series；多个维度选基数最小且 ≥2 的维度；
- 只有一个类别时回退到普通「时间 + 指标」序列；
- 普通时间序列按自然时间排序（`1月 < 2月 < 10月`），同一时间点多行按指标语义聚合
  （率/均价取平均，其余求和），避免折线来回折、x 轴重复；
- 自然排序同时支持中文数字：`一月 < 二月 < 十月 < 十一月`、`第一季度…第四季度`、
  `星期一…星期日`；中文数字只在时间标签/序数/逐位年份上下文展开，不改写「统一」等普通词。

回归：`tests/test_series_split.py`（透视、自然时间序、中文月份/季度/星期、多指标、多维度、
高基数排行、重复单元格聚合）。

## CSV 编码

`FileReader` 读 CSV/TSV 前先探测编码（`_detect_encoding`）：UTF-8 BOM / UTF-16 BOM（含无 BOM
按奇偶字节判断端序）> UTF-8 > GB18030（兼容 GBK/GB2312）。Windows 上 Excel 默认导出的 GBK CSV
不再报 `UnicodeDecodeError`；分隔符嗅探复用同一编码，并只统计**引号外**的分隔符
（`"说明,含逗号"` 不会把逗号误判成列分隔符）。回归 `tests/test_csv_encoding.py`。

## JSON / JSONL

`FileReader` 先判断 `.json` 是整个 JSON 文档还是逐行 JSON：整体能解析就按文档读
（对象、数组、`列名 -> 数组` 宽表都支持）；整体解析失败且首个非空行是对象/数组时才按 JSONL。
单条对象会包成一行，嵌套字段用 `json_normalize` 展开成 `指标.销售额` 这类点号列。
错误信息带文件名/行号。回归 `tests/test_file_reader_json.py`。

## 预览数据导出

`POST /api/data-profile` 的响应新增 `session_id`、`exports[]`（每个 series 的 `csv_url`）与
`raw_tables[]`（归一化后、拆 series 前的原始表，用于核对 OCR/抽表结果）。
预览不再立即删除 series 会话目录：保留到下一次 `allocate_session_dir` 时按 24 小时 TTL 清理。

- `ingest(save_raw=True)` / `ingest_files(save_raw=True)` 会把原始表额外写成
  `<session>/raw/raw_<i>.parquet` + `manifest.json`；图表任务默认不写，避免额外磁盘/耗时。
- `GET /api/data-profile/export?session_id=...&series_id=...` 返回单系列 CSV（UTF-8 BOM，Excel 不乱码）；
  不传 `series_id` 时打包全部系列为 ZIP。
- 原始表：`...&raw=<index>` 单表 CSV，`raw=all` 打包全部；`raw` 与 `series_id` 不能同时使用。
- `session_id` 必须匹配 `ds_<12位hex>`；`series_id` 只从 `manifest.json` 查，原始表序号只从
  `raw/manifest.json` 查，解析后的 parquet 路径必须落在会话目录内，防路径穿越。
- 上传文件落盘前统一取 `Path(filename).name`（data / chart / code 三个接口一致），防止 `../` 越界。
- 回归：`tests/test_data_profile_export.py`（series / 原始表 / ZIP / 非法序号 / 非法会话 / 越界路径）。

## 多模态输入（图片 / PDF → 表格）

多模态不是独立链路，而是数据接入层的一个 reader，抽表后与 CSV 完全同构：

```
上传图片/PDF → router._route_file → MultimodalReader（视觉模型）
上传 docx/pptx/xlsx（内嵌图片）→ DocumentReader 失败/退化 → OfficeImageReader（视觉模型）
            → {"columns", "rows"} → DataFrame → RawTable
            → series 拆分(.parquet) → 与普通表格一样进 plan / 图表生成
```

代码位置：`service/data_ingestion/readers/multimodal_reader.py`，
prompt 在 `prompts/multimodal_tabularize_prompt.py`；
Office 内嵌图片在 `service/data_ingestion/readers/office_image_reader.py`。

- **模型凭证优先级**：`VISION_BASE_URL`/`VISION_API_KEY` > 请求带来的 `model_url`/`model_api_key`
  > `.env` 的 `BASE_URL`/`API_KEY`。`.env` 目前是空模板，实际凭证由前端 `settings.json` 下发。
- **列名保真**：有表头就逐字沿用（含单位），不得补全业务含义——真机踩过把 `2023 年` 写成
  `2023年销售额`（用户 prompt 里提到销售额）。评估里对列名做严格比对。
- **模型名**：`VISION_MODEL_NAME`，缺省 `glm-4.5v`（智谱）。换厂商必须显式改（如 `gpt-4o`、`qwen-vl-max`），
  否则会拿文本模型跑图片。
- **图片预处理**：Pillow 按 EXIF 转正、最大边 `VISION_MAX_IMAGE_SIDE`(2000)，截图类存 PNG，
  超过 4MB 再降级 JPEG；PDF 用 pypdfium2 渲染前 `VISION_MAX_PDF_PAGES`(5) 页。
  扫描版 PDF（无文字层）逐页走视觉抽表，命名 `_p1`/`_p2`；两页各一张表的真机用例已纳入评估。
- **图片格式**：png/jpg/jpeg/webp/bmp/gif/tif/tiff + AVIF（Pillow 内置，须 >=11.3）+
  HEIC/HEIF（iPhone 照片，`pillow-heif` 解码，`_register_heif()` 懒注册）。缺 pillow-heif 时
  会抛带安装命令的 RuntimeError，而不是 UnidentifiedImageError。前端文件过滤器同步加了这三种格式。
- **调用参数**：`VISION_MAX_TOKENS`(8192) / `VISION_TIMEOUT`(90)。用推理模型做视觉时 reasoning
  会吃掉 max_tokens，输出被截断会报错点名 `VISION_MAX_TOKENS`，宁可调大。
- **降级顺序**：图片先视觉模型，失败回退 Unstructured OCR（本机没装 tesseract，回退基本必失败）；
  PDF 先文字层解析，只有退化成单列 `content` 时才走视觉模型。两条路都失败要抛带两段原因的错误。
- **Office 内嵌图片**：docx/pptx/xlsx 里的表格常是截图，Unstructured 只拿文字层。文字层为空、
  解析抛错或退化成单列 `content` 时，`OfficeImageReader` 按 OOXML zip 读 `word|ppt|xl/media`
  下的图片交给视觉模型；默认一张图一条 RawTable（多图时命名 `<名字>_img1`…），
  开启 `VISION_MULTI_TABLE=1` 后同图多表再叠 `_t1`/`_t2`。过滤规则：
  字节数 >= `VISION_MIN_IMAGE_BYTES`(4096)、最短边 >= `VISION_MIN_IMAGE_SIDE`(160)、
  最多 `VISION_MAX_OFFICE_IMAGES`(8) 张（按 `image2 < image10` 自然序）。纯文字文档（没有图片）
  保留文字结果且**不标** degraded；有图片但抽表失败才标 `multimodal_failed`。
  真机验过“只贴一张表格截图的 docx”：Unstructured 抛“未提取到任何内容”→ 兜底 → 7.4 秒拿到
  列名逐字一致（`城市`/`2023 年`/`2024 年`）的 3 行表；同一张图里两张不同表也全部抽出
  （多表模式 9.1 秒、2/2，值逐字一致）。
- **PDF 跨页续表**：相邻页的表格列结构完全一致、页边界没有合计/小计行时，才按保守规则合并：
  有时间列且时间轴严格递增（上一页最后一个时间 < 下一页第一个时间）才合并；两页各自只有一个
  固定期间（如「1 月表」「2 月表」）视为独立快照，不合并；无时间列时只有下一页重复上一页最后一行
  （分页重叠）才合并。合并后的表名去掉 `_pN`，`source_path` 记为 `#pageN-M`。真机用两页销售表
  验证：同表 2 页合并为 40 行，两个月份快照仍保持 2 张表。
- **一图多表**：`VISION_MULTI_TABLE=1`（或 `MultimodalReader.read(..., multi_table=True)`）时
  prompt 换成 `MULTIMODAL_MULTI_TABLE_PROMPT`，输出 `{"tables":[{title,columns,rows}]}`，
  一图/一页可产出多条 RawTable（命名 `_t1`/`_t2`，PDF 再叠 `_p1`），每页最多
  `VISION_MAX_TABLES`(5) 张。默认关闭（只取主表），避免把页眉/键值对误当表；
  单表模式即使模型返回 `tables` 数组也只取第一张。真机验过左右两张列结构不同的表全部抽出、5/5。
  请求级开关：`/api/data-profile` 表单 `multi_table=1` 或 `GenerateChartWithPromptRequest.multi_table=true`，
  经 `build_file_options(..., multi_table=True)` 变成 `vision_multi_table` option；未设置时回落到环境变量。
  真机 HTTP 验过：HEIC（两张不同表）+ `multi_table=1` → 返回 `..._t1` / `..._t2` 两张表，
  `related_tables` 与 `series_index` 都含第二张，值逐字一致。
- **用户意图**：`ingest_data_source` 把 `user_prompt` 作为 `vision_hint` 透传，帮助模型在多张表中选主表；
  单文件用 `build_file_options()`，多文件用 `ingest_files(..., hint=..., vision_cfg=...)`。
- **抽表结果缓存**：图片 / PDF / Office 内嵌图片的抽表结果按「文件内容 + `hint` + 多表开关 +
  页数上限 + 图片预处理参数 + 模型签名」命中 `runtime/cache/vision`（默认开启；
  `VISION_CACHE=0` 关闭，`VISION_CACHE_TTL_DAYS` 默认 14 天，`VISION_CACHE_DIR` 可改目录）。
  文本表格化（HTML / Markdown / 日志）同样按内容哈希缓存到 `runtime/cache/llm_text`
  （`LLM_TEXT_CACHE_DIR` 可改），键额外包含 `max_text_chars`；`VISION_CACHE=0` 同时关闭两者。
  前端先预览再生成图表时不会重复调用 LLM；只缓存成功结果，测试注入假模型时不走缓存
  （`service/data_ingestion/vision_cache.py`）。改抽表 prompt 或输出结构时要递增 `_CACHE_VERSION`，
  否则旧缓存会继续命中。真机验过：表格截图 3.4s→0.1s、docx 内嵌图
  3.0s→0.1s、Markdown 文本 3.6s→0.0s，结果与 `source_path` 均一致。
- `/api/data-profile` 也能直接传图片/PDF（多模态这一步会调用 LLM），可用于抽表预览。
- 测试注入假模型即可，不联网：`MultimodalReader.read(path, llm=FakeLLM(...))`。
- **真机 E2E 已验**：`/api/generate-chart-with-prompt` 传 PNG + `model_url/model_api_key` +
  `model_type=deepseek-v4.1-flash`、`viz_mode=auto`，约 60–90 秒返回 4 张图表；抽表值与原图逐值一致
  （近期一次 58 秒、0 次 debug 重试）。
- **整条链路真机验过**（docx 里只贴一张表格截图 → 图表）：约 96 秒产出 4 张图，图表 HTML 里含
  原图数值；HEIC 一图两表 + `multi_table=1` 时，两张表都成为 series（`..._t1` / `..._t2`），
  agent 分别出图（约 73 秒）。
- **`multi_table` 请求级开关**：`/api/generate-chart-with-prompt` 与 `/api/data-profile` 都解析表单
  字段并透传（`chart_api` 曾漏接，只有 data-profile 生效；回归见 `chart_api` + `data_source`）。
  WinUI 输入框下方有「多表抽取」chip，开启后经 Rust `GenerateChartRequest.multi_table` 以
  `multi_table=1` 下发；未开启时不下发，仍由 `VISION_MULTI_TABLE` 兜底。
- **上传文件名的 UUID 前缀只用于磁盘防冲突**：接口存成 `<32位hex>_<原名>`，但表名 / series 名 / 预览名
  用 `display_name_from_path()`（`service/runtime/utils.py`）去掉前缀；`runtime/charts/` 目录仍保留
  前缀，避免同名文件的两个任务互相覆盖。`ingest_files` 单文件分支也要带上 `multi_table`（已修）。
- **错误路径行为**：无表格图片 / 损坏图片 → HTTP 500，`detail` 同时给出视觉模型与 OCR 两段原因；
  纯文字 docx 没有表格也没有图片 → 200，退化为单列 `content` 表且**不标** degraded（沿用原设计）。
  多文件混合（HEIC + CSV）→ 200，series 目录同时包含视觉表与 CSV 表。

## 任务生命周期与探针

- `_tasks` 是内存字典（`app.py`），通过 `init_app` 注入给蓝图；任务记录带 `created_at`。
- 每次提交任务时 `api.common.prune_tasks()` 回收终态任务（success/failed/cancelled）：
  `TASK_RETENTION_SECONDS`（默认 3600 秒）+ `TASK_MAX_ENTRIES`（默认 500 条，按时间从旧到新淘汰）。
  进行中的任务永不清理。**不要**把回收逻辑塞进 `get_tasks()`，它会在读路径上隐式改数据。
- 进程退出时 `atexit` 调 `executor.shutdown(wait=False, cancel_futures=True)`，避免排队任务拖住停止。
- `/api/health`（liveness）只看进程；`/api/ready`（readiness）检查上传/图表目录可写 + 对话库可访问，
  未就绪返回 503。两个探针都不鉴权。

## series 读取契约（v4）

每个 plan 必须从 `series_index` 里选 `series_id`（plan 只存 id，读取代码本体留在 series 目录，单一真相）：

- **数据契约**：读取代码由框架执行并拼在生成代码开头，提供全局变量 `df`；series 文件路径不进入 LLM 上下文
- **禁止自写数据读取**：`import duckdb` / `read_parquet` 重新加载 / 建连接 / 写 SELECT 一律禁止，用注入的 `df`
- **变换**：按 `transform_hint` 在 `df` 上用 pandas 完成（如增长率 = (本年-上年)/上年*100）
- **自包含契约**：`code_<plan_id>_success.py` 是注入后的完整代码，拷走 + 对应 series `.parquet` 即可独立运行
- `series_id` 缺失（agent 自主规划）时走自备读取模式：直接从 `data_interface` 取数
- 校验在 `service/pipeline/plan_validator.py`；不要绕过它直接把 LLM 输出喂给执行器

## 产物路径与命名

```
runtime/charts/<首个上传文件 stem>/          # 可用 CHARTS_DIR 覆盖
├── all_plans.json
├── plans/plan_<plan_id>.json
├── code/code_<plan_id>_{success,failed,rejected}.py
└── charts/chart_<plan_id>_<YYYYmmdd_HHMMSS>.html
```

- 其他运行期目录：`runtime/uploads/`、`runtime/datasets/ds_<sid>/`、`runtime/traces/<task_id>.json`、
  `runtime/cache/vision/<hash>/`（多模态 / Office 抽表缓存）、`runtime/cache/llm_text/<hash>/`
  （文本表格化缓存）、`runtime/logs/datavisual.jsonl`
- 覆盖用环境变量（`.env`）：`TEMP_UPLOAD_DIR`、`TEMP_DATASETS_DIR`、`CHARTS_DIR`、`LOG_PATH`、
  `VISION_CACHE_DIR`、`LLM_TEXT_CACHE_DIR`
- `.gitignore` 里是 `/runtime/`（根锚定）。**不要改回 `runtime/`**，那样会连 `service/runtime/` 下的新文件一起忽略

## 代码风格

- Python 3.12（`.python-version`）；字符串优先双引号 `"`；路径用 `pathlib.Path`；import 顺序
  标准库 → 第三方 → 本项目
- 文档字符串用中文，说明用途、参数、返回值
- 模块要同时支持"包导入"和"脚本直跑"：沿用 `try: from service.x import y / except ImportError: from ..x import y`
  的双导入写法（`Entity/__init__.py` 还负责把项目根塞进 `sys.path`）
- plan 字段兼容 camelCase 别名（`parse_plans` 已处理）；变量/函数 snake_case，类名 PascalCase
- 日志统一用 `from service.observability import get_logger`，structlog 风格：
  `logger.info("事件名", key=value)`。**不要用 f-string 把变量拼进消息**，也不要 `print`

## 错误处理

- 图表生成失败进入 debug 循环（最多 3 次），用 `service/pipeline/chart_debugger.py` 分析错误
- 不要静默吞掉异常：错误信息必须回传到 `failed_plans` / task 状态
- 接口错误统一返回 `{"detail": "..."}`；`ConfigError` / `ServiceError` 已在 `app.py` 注册全局处理器
- `SERVICE_API_KEY` 为空 = 不鉴权；非空时请求需带 `X-API-Key`
- **stdout 可能是 GBK**：服务输出重定向到文件/管道时 Python 按系统 locale 编码，日志或异常里一旦出现
  emoji/生僻字就 `UnicodeEncodeError`，任务直接失败。`app.py` 启动即调 `_force_utf8_stdio()` 把
  stdout/stderr 切 UTF-8；服务代码里不要 `print`（`BaseAgent` / `agent/retry.py` 已改 structlog）。
  `run_python_safely` 也给子进程注入 `PYTHONIOENCODING=utf-8` / `PYTHONUTF8=1`，否则沙箱里
  print 的中文会被父进程按 UTF-8 解码成替换字符，debug 反馈和图表数据摘要都会失真。

## 文档可信度

- 以代码为准。`docs/技术资料.md` / `docs/开发计划.md` / `docs/问题清单.md` **已过期**（还在描述
  已删除的 `main.rs` / `webview.rs` / `pages/` 和"纯 Win32"方案），只有 `docs/构建指南.md` 跟得上实现
