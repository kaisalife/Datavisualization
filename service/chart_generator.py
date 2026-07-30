import asyncio
import json
import os
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

from agent_tools.sandbox import run_python_safely

try:
    from agent import BaseAgent
    from service.utils import extract_code_from_response
except ImportError:
    from ..agent import BaseAgent
    from .utils import extract_code_from_response

project_root = Path(__file__).parent.parent

# 通过 header 注入 monkey-patch pyecharts 渲染路径，
# 避免脆弱的 `./charts` 字符串替换 + 多目录 fallback 扫描。
# LLM 生成代码中 chart.render(...) 的 path 会被强制重定向到
# 环境变量 CHART_OUTPUT_DIR / CHART_OUTPUT_NAME 指定的位置。
_RENDER_HEADER = '''# --- auto-injected by chart_generator (unified render path) ---
import os as _os
from pathlib import Path as _Path

_CHART_OUTPUT_DIR = _os.environ.get("CHART_OUTPUT_DIR", ".")
_CHART_OUTPUT_NAME = _os.environ.get("CHART_OUTPUT_NAME", "render.html")
_os.makedirs(_CHART_OUTPUT_DIR, exist_ok=True)

try:
    from pyecharts.charts.base import Base as _PyBase
    _orig_render = _PyBase.render

    def _patched_render(self, *args, **kwargs):
        target = _Path(_CHART_OUTPUT_DIR) / _CHART_OUTPUT_NAME
        # 丢弃 path 参数，统一改写为目标路径
        if args:
            args = (str(target),) + args[1:]
        else:
            kwargs["path"] = str(target)
        return _orig_render(self, *args, **kwargs)

    _PyBase.render = _patched_render
except Exception as _e:
    print(f"[chart_generator header] pyecharts patch skipped: {_e}")
# --- end header ---

'''

async def generate_single_chart(
    chat: BaseAgent,
    plan: dict,
    data_file_path: str,
    data_preview: str,
    output_folder: Path,
    engine=None,
    generate_prompt=None,
    debug_prompt=None,
    generate_chain=None,
    debug_chain=None,
    retriever=None,
    max_retries: int = 3,
    dataset_summary: str = "",
) -> tuple[bool, str, str]:
    plan_id = plan.get("plan_id", "unknown")
    plan_name = plan.get("plan_name", "Unknown Plan")
    
    print(f"\n{'='*60}")
    print(f"📊 开始执行计划 {plan_id}: {plan_name}")
    print(f"{'='*60}")
    
    plans_folder = output_folder / "plans"
    code_folder = output_folder / "code"
    charts_folder = output_folder / "charts"
    plans_folder.mkdir(exist_ok=True)
    code_folder.mkdir(exist_ok=True)
    charts_folder.mkdir(exist_ok=True)
    
    plan_file = plans_folder / f"plan_{plan_id}.json"
    with open(plan_file, "w", encoding="utf-8") as f:
        json.dump(plan, f, ensure_ascii=False, indent=2)
    print(f"💾 计划已保存: {plan_file}")
    
    plan_details = json.dumps(plan, ensure_ascii=False, indent=2)
    final_code = ""
    
    # 使用 RAG 检索相关文档
    reference_docs = ""
    if retriever is not None:
        chart_type = plan.get("chart_type", "Line")
        chart_title = plan.get("chart_title", "")

        # 主查询以 chart_type 为核心（RAG 索引按图表类型组织），
        # 只叠加 chart_title 作为微弱语义提示；避免拼接 plan_description /
        # data_analysis 稀释 embedding 主语义。
        search_query = f"pyecharts {chart_type} chart example"
        if chart_title:
            search_query += f" {chart_title}"
        print(f"🔍 正在检索相关文档，查询: {search_query}")
        try:
            docs = retriever.retrieve(search_query)
            if docs:
                doc_parts = []
                for i, doc in enumerate(docs):
                    doc_parts.append(doc.page_content)

                reference_docs = "\n\n---\n\n".join(doc_parts)
                print(f"✅ 找到 {len(docs)} 个示例")
            else:
                print("⚠️ 未找到相关示例")
        except Exception as e:
            print(f"⚠️ 检索失败: {e}")
    
    code = ""
    last_error = ""
    for attempt in range(max_retries):
        if engine and engine.aborted:
            print("⚠️ QueryEngine 已中止，停止生成")
            break

        print(f"\n🔄 尝试 {attempt + 1}/{max_retries}")
        attempt_start_ts = time.time()

        try:
            if attempt == 0:
                print(f"📝 正在生成图表代码...")
                gen_input = {
                    "data_file_path": data_file_path,
                    "data_preview": data_preview,
                    "plan_details": plan_details,
                    "reference_docs": reference_docs,
                    "dataset_summary": dataset_summary or "(未提供)",
                }
                if engine and generate_prompt:
                    content = await engine.run_prompt(generate_prompt.invoke(gen_input))
                else:
                    response = await generate_chain.ainvoke(gen_input)
                    content = response.get("content", "") if isinstance(response, dict) else str(response)
                code = extract_code_from_response(content)
            else:
                print(f"🔧 使用 Debug Agent 修复代码...")
                debug_input = {
                    "plan_details": plan_details,
                    "failed_code": code,
                    "error_message": last_error,
                    "data_preview": data_preview,
                    "dataset_summary": dataset_summary or "(未提供)",
                }
                if engine and debug_prompt:
                    content = await engine.run_prompt(debug_prompt.invoke(debug_input))
                else:
                    response = await debug_chain.ainvoke(debug_input)
                    content = response.get("content", "") if isinstance(response, dict) else str(response)
                code = extract_code_from_response(content)
            
            final_code = code
            print(f"💻 生成的代码:\n{code}\n")
            
            print(f"🚀 执行代码...")
            
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            chart_filename = f"chart_{plan_id}_{timestamp}.html"
            # 使用绝对路径，避免 subprocess cwd 与相对 CHART_OUTPUT_DIR 叠加导致文件写到嵌套目录
            charts_folder_abs = str(Path(charts_folder).resolve())

            # 通过 header 注入 + 环境变量注入统一渲染路径，
            # 无需再对 LLM 代码做字符串替换 / 事后扫描多个 fallback 目录。
            modified_code = _RENDER_HEADER + code

            proc_result = None
            execution_success = False
            output_result = ""

            try:
                run_env = dict(os.environ)
                run_env["CHART_OUTPUT_DIR"] = charts_folder_abs
                run_env["CHART_OUTPUT_NAME"] = chart_filename

                proc_result = run_python_safely(
                    modified_code,
                    cwd=str(charts_folder),
                    timeout=60,
                    env=run_env,
                    extra_pythonpath=str(project_root),
                )

                if proc_result.success:
                    output_result = proc_result.stdout
                    print(f"✅ 执行成功\n输出:\n{output_result}")
                    execution_success = True
                else:
                    if proc_result.error:
                        output_result = f"Error: {proc_result.error}"
                    else:
                        output_result = f"Error:\nStderr: {proc_result.stderr}\nStdout: {proc_result.stdout}"
                    print(f"❌ 执行失败\n{output_result}")
                    execution_success = False

            except Exception as e:
                output_result = f"Exception: {traceback.format_exc()}"
                print(f"❌ 异常: {output_result}")
                execution_success = False

            print(f"📋 执行结果:\n{output_result}\n")

            if execution_success:
                code_file = code_folder / f"code_{plan_id}_success.py"
                with open(code_file, "w", encoding="utf-8") as f:
                    f.write(final_code)
                print(f"💾 代码已保存: {code_file}")

                chart_path = str(charts_folder / chart_filename)
                # header 注入的 monkey-patch 已强制把 pyecharts 输出写到目标路径。
                # 若极少数场景（LLM 未使用 pyecharts.render 或采用其他后端）导致文件缺失，
                # 保留最小兜底：在 charts_folder 内取本轮新增的第一个 html。
                if not Path(chart_path).exists():
                    new_files = [
                        p for p in charts_folder.glob("*.html")
                        if p.stat().st_mtime >= attempt_start_ts and p.name != chart_filename
                    ]
                    if new_files:
                        fallback = sorted(new_files, key=lambda p: p.stat().st_mtime)[-1]
                        try:
                            fallback.rename(charts_folder / chart_filename)
                            print(f"📦 兜底重命名 {fallback.name} -> {chart_filename}")
                        except Exception as move_err:
                            chart_path = str(fallback)
                            print(f"⚠️ 兜底重命名失败，直接使用 {chart_path}: {move_err}")

                print(f"✅ 计划 {plan_id} 执行成功!")
                print(f"📁 图表路径: {chart_path}")

                return True, chart_path, ""
            else:
                last_error = output_result
                print(f"❌ 执行失败: {last_error}")

                # 沙箱静态拒绝（AST 安全检查）不适合走 debug，debug 也改不了规则
                if "安全检查失败" in last_error:
                    print(f"⚠️ 静态安全检查失败，跳过 debug（debug 无法修复被拒规则）")
                    code_file = code_folder / f"code_{plan_id}_rejected.py"
                    with open(code_file, "w", encoding="utf-8") as f:
                        f.write(final_code)
                    print(f"💾 被拒代码已保存: {code_file}")
                    break

                if attempt < max_retries - 1:
                    print(f"⏳ 准备使用 Debug Agent 修复...")
                else:
                    code_file = code_folder / f"code_{plan_id}_failed.py"
                    with open(code_file, "w", encoding="utf-8") as f:
                        f.write(final_code)
                    print(f"💾 失败代码已保存: {code_file}")
                    print(f"❌ 已达到最大重试次数 {max_retries}")
                    
        except Exception as e:
            last_error = str(e)
            print(f"❌ 异常: {last_error}")
            traceback.print_exc()
            
            if attempt >= max_retries - 1:
                if final_code:
                    code_file = code_folder / f"code_{plan_id}_failed.py"
                    with open(code_file, "w", encoding="utf-8") as f:
                        f.write(final_code)
                    print(f"💾 失败代码已保存: {code_file}")
                print(f"❌ 已达到最大重试次数 {max_retries}")
    
    return False, "", last_error
