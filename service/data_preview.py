import pandas as pd
import os
import asyncio
import traceback
from pathlib import Path

try:
    from prompts.agent_prompt import get_agent_data_preview_prompt
    from service.utils import extract_code_from_response
    from service.cache.file_read_cache import read_file, get_file_cache
    from service.constants import CSV_ENCODINGS
    from agent_tools.sandbox import run_python_safely
except ImportError:
    from ..prompts.agent_prompt import get_agent_data_preview_prompt
    from .utils import extract_code_from_response
    from .cache.file_read_cache import read_file, get_file_cache
    from .constants import CSV_ENCODINGS
    from ..agent_tools.sandbox import run_python_safely

project_root = Path(__file__).parent.parent

def load_pandas_reference():
    pandas_file = project_root / "RAG" / "basic_author_knowleage" / "pandas.md"
    if pandas_file.exists():
        content, _ = read_file(str(pandas_file))
        return content or ""
    return ""

def get_file_preview(files:list):
    cache = get_file_cache()
    res_str = ""
    id=1
    for f in files:
        print(f)
        res_str=res_str+f"###{id:}\n"
        if f.endswith(".csv"):
            print("csv file")
            res_str=res_str+cache.get_or_compute(f, _compute_csv_preview)
        elif f.endswith(".xls") or f.endswith(".xlsx"):
            print("excel file")
            res_str=res_str+cache.get_or_compute(f, _compute_xls_preview)
        id=id+1
    return res_str

def _compute_csv_preview(f:str):
    df = None
    for encoding in CSV_ENCODINGS:
        try:
            df = pd.read_csv(f, encoding=encoding)
            print(f"✅ 使用 {encoding} 编码读取成功")
            break
        except UnicodeDecodeError:
            continue
        except Exception as e:
            print(f"⚠️ 使用 {encoding} 编码读取失败: {e}")
            continue
    if df is None:
        df = pd.read_csv(f, encoding='utf-8', errors='ignore')
        print("⚠️ 使用 utf-8 编码并忽略错误读取")
    
    rows, cols = df.shape
    res_str = f"文件: {os.path.basename(f)}\n"
    res_str += f"数据形状: {rows} 行 × {cols} 列\n"
    res_str += f"列名: {list(df.columns)}\n"
    res_str += f"\n前10行数据预览:\n"
    res_str += df.head(10).to_string()
    print(res_str)
    return res_str

def get_csv(f:str):
    return get_file_cache().get_or_compute(f, _compute_csv_preview)

def _compute_xls_preview(f:str):
    df=pd.read_excel(f)
    
    rows, cols = df.shape
    res_str = f"文件: {os.path.basename(f)}\n"
    res_str += f"数据形状: {rows} 行 × {cols} 列\n"
    df_rows=df.iloc[:,0]
    res_str += f"行名:{df_rows.to_string()}\n"
    res_str += f"\n前10行数据预览:\n"
    res_str += df.head(10).to_string()
    print(res_str)
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

async def get_smart_file_preview(chat, files:list, max_retries: int = 1, output_folder: Path = None):
    res_str = ""
    data_interface_codes = []
    pandas_reference = load_pandas_reference()
    
    for idx, f in enumerate(files, 1):
        print(f"\n{'='*60}")
        print(f"📄 智能处理文件 {idx}/{len(files)}: {os.path.basename(f)}")
        print(f"{'='*60}")
        
        preview, interface_code = await get_smart_single_file_preview(chat, f, max_retries, pandas_reference)
        res_str += f"###{idx}\n{preview}\n"
        
        if interface_code and output_folder:
            file_name = Path(f).stem
            code_folder = output_folder / file_name / "code"
            code_folder.mkdir(parents=True, exist_ok=True)
            code_file = code_folder / "data_preview.py"
            with open(code_file, "w", encoding="utf-8") as cf:
                cf.write(interface_code)
            print(f"💾 数据接口代码已保存: {code_file}")
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
        print(f"\n🔄 [{step_name}] 尝试 {attempt + 1}/{max_retries}")

        try:
            print(f"📝 [{step_name}] 正在生成代码...")
            try:
                response = await asyncio.wait_for(
                    preview_chain.ainvoke(invoke_input),
                    timeout=60,
                )
            except asyncio.TimeoutError:
                print(f"⚠️ [{step_name}] LLM 调用超时（60s）")
                break

            code = extract_code_from_response(response.get("content", ""))
            print(f"💻 [{step_name}] 生成的代码:\n{code}\n")

            print(f"🚀 [{step_name}] 执行代码...")
            try:
                proc_result = run_python_safely(
                    code,
                    cwd=str(project_root),
                    timeout=60,
                )

                if proc_result.success:
                    print(f"✅ [{step_name}] 执行成功\n输出:\n{proc_result.stdout}")
                    return proc_result.stdout, code, ""

                if proc_result.error:
                    last_error = f"Error: {proc_result.error}"
                else:
                    last_error = (
                        f"Error:\nStderr: {proc_result.stderr}\n"
                        f"Stdout: {proc_result.stdout}"
                    )
                print(f"❌ [{step_name}] 执行失败\n{last_error}")

            except Exception:
                last_error = f"Exception: {traceback.format_exc()}"
                print(f"❌ [{step_name}] 沙箱异常: {last_error}")

        except Exception as e:
            last_error = str(e)
            print(f"❌ [{step_name}] LLM 异常: {last_error}")
            traceback.print_exc()

    return "", "", last_error


async def get_smart_single_file_preview(chat, file_path: str, max_retries: int = 1, pandas_reference: str = ""):
    data_preview_prompt = get_agent_data_preview_prompt(pandas_reference)
    preview_chain = data_preview_prompt | chat

    print(f"\n{'='*60}")
    print(f"📊 第一步：获取简单数据预览")
    print(f"{'='*60}")

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
        print(f"⚠️ 预览获取失败，回退到基础预览...")
        if file_path.endswith(".csv"):
            preview_content = get_csv(file_path)
        elif file_path.endswith(".xls") or file_path.endswith(".xlsx"):
            preview_content = get_xsl(file_path)
        else:
            preview_content = f"文件: {os.path.basename(file_path)}\n无法智能预览，格式不支持"

    print(f"\n{'='*60}")
    print(f"🔧 第二步：构建数据接口")
    print(f"{'='*60}")

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

