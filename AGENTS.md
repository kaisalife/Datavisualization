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

.venv\Scripts\python.exe -m pytest -q                                     # 免 LLM 全集（当前 159 passed / 21 deselected）
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
| `api/*_api.py` | 各领域接口；共享依赖经 `api/common.py:init_app()` 注入，用 `current_app.config[...]` 取，不要跨模块 import 全局 |
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

## Excel 合并表头 / 标题行

中文报表常见「一行合并大标题 + 两行合并表头」。`ExcelReader` 直接从 xlsx/xlsm 的 zip XML 读合并区域
（不加载整个 openpyxl 工作簿），再决定怎么读：

- 顶部跨列的单值合并行（如 `A1:E1`「2024 年销售报表」）→ 当标题跳过，最多 2 行；
- 表头自身有纵向/横向合并（如 `B1:C1`「2023 年」+ `B2`「销售额」）→ 把 2–3 行表头压成单行，
  用 `_` 连接成 `2023 年_销售额`；纵向合并产生的重复值会去重（`城市` 不会变 `城市_城市`）；
- 没有合并、靠空白格表达的两行表头也能识别（第二行首列为空、非空值更多、全文字，且第三行有数字）；
  不满足这些条件就按普通表处理，不会吃掉数据行；
- 合并区域必须**与首行表头相交**才触发**表头压缩**；数据区里的合并单元格不改变表头，
  但纵向合并的**文本**（如 `城市` 跨多行）会在读取后向下填满；数值合并（合计/小计）不填，
  避免重复计量；
- 没有表头问题的文件只多一次 4 行 peek；有数据区纵向合并时按合并区域补全文本；
- 实测 1 万行合并表头 0.85 秒、2 万行普通表 3.5–4 秒（比原先 openpyxl 全量加载 + pandas 双读快约 30%）。

实现：`service/data_ingestion/readers/excel_reader.py`；回归 `tests/test_excel_reader.py`
（两行表头、标题行、空白格表头、正常表、数据区合并、多 sheet、xlsm、ingest 全链路）。

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

## Series 拆分：长表透视

`城市 / 月份 / 销售额` 这类「时间 + 维度 + 指标」长表，不再把不同城市混成一条时间线：

- 维度类别 ≤12：透视成 `时间 × 类别` 宽表，一条 series 多列（多折线）；
- 类别 >12：按维度聚合排行（率/均价取平均，其余求和），最多 20 行；
- 多个指标每个一条 series；多个维度选基数最小且 ≥2 的维度；
- 只有一个类别时回退到普通「时间 + 指标」序列。

回归：`tests/test_series_split.py`（透视、自然时间序、多指标、多维度、高基数排行、重复单元格聚合）。

## CSV 编码

`FileReader` 读 CSV/TSV 前先探测编码（`_detect_encoding`）：UTF-8 BOM / UTF-16 BOM（含无 BOM
按奇偶字节判断端序）> UTF-8 > GB18030（兼容 GBK/GB2312）。Windows 上 Excel 默认导出的 GBK CSV
不再报 `UnicodeDecodeError`；分隔符嗅探复用同一编码，并只统计**引号外**的分隔符
（`"说明,含逗号"` 不会把逗号误判成列分隔符）。回归 `tests/test_csv_encoding.py`。

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
  `runtime/logs/datavisual.jsonl`
- 覆盖用环境变量（`.env`）：`TEMP_UPLOAD_DIR`、`TEMP_DATASETS_DIR`、`CHARTS_DIR`、`LOG_PATH`
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
  stdout/stderr 切 UTF-8；服务代码里不要 `print`（`BaseAgent` / `agent/retry.py` 已改 structlog）

## 文档可信度

- 以代码为准。`docs/技术资料.md` / `docs/开发计划.md` / `docs/问题清单.md` **已过期**（还在描述
  已删除的 `main.rs` / `webview.rs` / `pages/` 和"纯 Win32"方案），只有 `docs/构建指南.md` 跟得上实现
