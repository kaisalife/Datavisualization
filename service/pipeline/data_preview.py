import pandas as pd
import os
import asyncio
from pathlib import Path

try:
    from prompts.agent_prompt import get_agent_data_preview_prompt
    from service.runtime.utils import extract_code_from_response
    from service.runtime.cache.file_read_cache import read_file, get_file_cache
    from service.runtime.constants import CSV_ENCODINGS
    from agent_tools.sandbox import run_python_safely
except ImportError:
    from prompts.agent_prompt import get_agent_data_preview_prompt
    from ..runtime.utils import extract_code_from_response
    from ..runtime.cache.file_read_cache import read_file, get_file_cache
    from ..runtime.constants import CSV_ENCODINGS
    from agent_tools.sandbox import run_python_safely

from service.observability import get_logger
from service.monitoring import trace

logger = get_logger(__name__)

project_root = Path(__file__).parent.parent.parent

def load_pandas_reference():
    pandas_file = project_root / "RAG" / "basic_author_knowleage" / "pandas.md"
    if pandas_file.exists():
        content, _ = read_file(str(pandas_file))
        return content or ""
    return ""

@trace(category="preview")
def get_file_preview(files:list):
    cache = get_file_cache()
    res_str = ""
    id=1
    for f in files:
        res_str=res_str+f"###{id:}\n"
        if f.endswith(".csv"):
            res_str=res_str+cache.get_or_compute(f, _compute_csv_preview)
        elif f.endswith(".xls") or f.endswith(".xlsx"):
            res_str=res_str+cache.get_or_compute(f, _compute_xls_preview)
        id=id+1
    return res_str

def _read_text_preview(f: str, max_chars: int = 8000) -> str:
    """按文本方式读取文件前 max_chars 个字符，自动尝试常见编码。"""
    encodings = list(CSV_ENCODINGS) if CSV_ENCODINGS else ["utf-8"]
    if "utf-8" not in encodings:
        encodings.append("utf-8")

    for encoding in encodings:
        try:
            with open(f, "r", encoding=encoding) as fh:
                content = fh.read(max_chars)
            logger.info("使用 %s 编码读取文本成功", encoding)
            return content.replace("\r\n", "\n")
        except UnicodeDecodeError:
            continue
        except Exception as e:
            logger.warning("使用 %s 编码读取文本失败: %s", encoding, e)
            continue

    with open(f, "r", encoding="utf-8", errors="ignore") as fh:
        content = fh.read(max_chars)
    logger.warning("使用 utf-8 编码并忽略错误读取文本")
    return content.replace("\r\n", "\n")


def _compute_csv_preview(f: str):
    """CSV 不再用 pandas 解析，直接读原始文本交给 AI 判断格式。"""
    preview = _read_text_preview(f, max_chars=8000)
    res_str = f"文件: {os.path.basename(f)}\n"
    res_str += f"原始文本预览（前 {len(preview)} 字符）:\n{preview}\n"
    if len(preview) >= 8000:
        res_str += "（内容已截断，后续由代码生成阶段按需读取完整文件）\n"
    logger.debug("CSV 预览结果：\n%s", res_str)
    return res_str

def get_csv(f:str):
    return get_file_cache().get_or_compute(f, _compute_csv_preview)

def _compute_xls_preview(f: str):
    """Excel 仅做最小化读取，输出为原始文本表格，由 AI 判断结构。"""
    try:
        df = pd.read_excel(f)
        preview = df.head(50).to_csv(sep="\t", index=False)
        res_str = f"文件: {os.path.basename(f)}\n"
        res_str += f"原始文本预览（前 50 行，制表符分隔）:\n{preview}\n"
        logger.debug("Excel 预览结果：\n%s", res_str)
        return res_str
    except Exception as e:
        res_str = f"文件: {os.path.basename(f)}\n"
        res_str += f"Excel 读取失败: {e}\n"
        logger.debug("Excel 读取失败结果：\n%s", res_str)
        return res_str

def get_xsl(f:str):
    return get_file_cache().get_or_compute(f, _compute_xls_preview)

def parse_data_preview_output(output: str):
    separator = "---DATA_INTERFACE_CODE---"
    if separator in output:
        parts = output.split(separator)
        preview_part = parts[0].strip()
        code_part = parts[1].strip() if len(parts) > 1 else ""
        return preview_part, code_part
    return output, ""

def _chat_fingerprint(chat) -> str:
    """从 chat 实例提取模型指纹。

    不同 LLM（不同 model_url / model_type）跑同一文件应得到独立缓存，
    避免弱模型生成的预览污染强模型的输出。
    """
    try:
        url = getattr(chat, "model_url", "") or ""
        mt = getattr(chat, "model_type", "") or ""
        if not mt and not url:
            return "unknown"
        return f"{mt or '?'}:{hash(url) % 10000}"
    except Exception:
        return "unknown"


@trace(category="preview")
async def get_smart_file_preview(chat, files:list, max_retries: int = 1, output_folder: Path = None):
    res_str = ""
    data_interface_codes = []
    pandas_reference = load_pandas_reference()
    fingerprint = _chat_fingerprint(chat)

    for idx, f in enumerate(files, 1):
        logger.info("智能处理文件 %s/%s: %s", idx, len(files), os.path.basename(f))

        preview, interface_code = await get_smart_single_file_preview(
            chat, f, max_retries, pandas_reference, chat_fingerprint=fingerprint,
        )
        res_str += f"###{idx}\n{preview}\n"

        if interface_code and output_folder:
            file_name = Path(f).stem
            code_folder = output_folder / file_name / "code"
            code_folder.mkdir(parents=True, exist_ok=True)
            code_file = code_folder / "data_preview.py"
            with open(code_file, "w", encoding="utf-8") as cf:
                cf.write(interface_code)
            logger.info("数据接口代码已保存: %s", code_file)
            data_interface_codes.append({
                "file_path": f,
                "code_file": str(code_file),
                "code": interface_code
            })

    return res_str, data_interface_codes

async def _run_preview_step(
    preview_chain,
    invoke_input: dict,
    step_name: str,
    max_retries: int,
) -> tuple[str, str, str]:
    """执行一步 LLM → 沙箱 循环。

    返回 (stdout, code, last_error)。stdout 非空表示成功。
    step_name 仅用于日志（"preview" / "interface"）。
    """
    last_error = ""
    for attempt in range(max_retries):
        logger.info("[%s] 尝试 %s/%s", step_name, attempt + 1, max_retries)

        try:
            logger.info("[%s] 正在生成代码", step_name)
            try:
                response = await asyncio.wait_for(
                    preview_chain.ainvoke(invoke_input),
                    timeout=60,
                )
            except asyncio.TimeoutError:
                logger.warning("[%s] LLM 调用超时（60s）", step_name)
                break

            code = extract_code_from_response(response.get("content", ""))
            logger.debug("[%s] 生成的代码:\n%s", step_name, code)

            logger.info("[%s] 执行代码", step_name)
            try:
                proc_result = run_python_safely(
                    code,
                    cwd=str(project_root),
                    timeout=60,
                )

                if proc_result.success:
                    logger.info("[%s] 执行成功\n输出:\n%s", step_name, proc_result.stdout)
                    return proc_result.stdout, code, ""

                if proc_result.error:
                    last_error = f"Error: {proc_result.error}"
                else:
                    last_error = (
                        f"Error:\nStderr: {proc_result.stderr}\n"
                        f"Stdout: {proc_result.stdout}"
                    )
                logger.warning("[%s] 执行失败\n%s", step_name, last_error)

            except Exception:
                logger.exception("[%s] 沙箱异常", step_name)
                last_error = f"sandbox exception (see logs for traceback)"

        except Exception:
            logger.exception("[%s] LLM 异常", step_name)
            last_error = "llm exception (see logs for traceback)"

    return "", "", last_error


async def get_smart_single_file_preview(chat, file_path: str, max_retries: int = 1, pandas_reference: str = "", chat_fingerprint: str = ""):
    data_preview_prompt = get_agent_data_preview_prompt(pandas_reference)
    preview_chain = data_preview_prompt | chat

    if chat_fingerprint:
        logger.info("数据预览 chat_fingerprint=%s", chat_fingerprint)

    logger.info("第一步：获取简单数据预览")

    preview_content, _, _ = await _run_preview_step(
        preview_chain,
        invoke_input={
            "data_file_path": file_path,
            "current_step": "preview",
            "data_preview": "",
        },
        step_name="preview",
        max_retries=max_retries,
    )

    if not preview_content:
        logger.warning("预览获取失败，回退到基础预览")
        if file_path.endswith(".csv"):
            preview_content = get_csv(file_path)
        elif file_path.endswith(".xls") or file_path.endswith(".xlsx"):
            preview_content = get_xsl(file_path)
        else:
            preview_content = f"文件: {os.path.basename(file_path)}\n无法智能预览，格式不支持"

    logger.info("第二步：构建数据接口")

    _, interface_code, _ = await _run_preview_step(
        preview_chain,
        invoke_input={
            "data_file_path": file_path,
            "current_step": "interface",
            "data_preview": preview_content,
        },
        step_name="interface",
        max_retries=max_retries,
    )

    return preview_content, interface_code

