import os
import re
import json
from pathlib import Path

from service.observability import get_logger

logger = get_logger(__name__)

JSON_PATTERN = re.compile(r'```json\s*(.*?)\s*```', re.DOTALL)
CODE_PATTERN = re.compile(r'```python\s*(.*?)\s*```', re.DOTALL)
CODE_FALLBACK_PATTERN = re.compile(r'```\s*(.*?)\s*```', re.DOTALL)
CHART_PATH_PATTERN = re.compile(r'chart_.*?\.html')
# 上传文件落盘时加了 32 位 hex 前缀防重名，展示表名要去掉
UPLOAD_PREFIX_PATTERN = re.compile(r"^[0-9a-f]{32}_", re.IGNORECASE)


def display_name_from_path(path: str | Path) -> str:
    """去掉上传文件名的 UUID 前缀，返回展示用表名。

    接口保存上传文件时用 ``<32位hex>_<原名>`` 防重名；这个前缀不该进入
    表名 / series 名 / agent 上下文。没有前缀时原样返回 stem。

    Args:
        path: 上传文件的磁盘路径（或任意带文件名的路径）

    Returns:
        str: 去掉 UUID 前缀后的文件名 stem；清理后为空时回退原 stem。
    """
    stem = Path(path).stem
    cleaned = UPLOAD_PREFIX_PATTERN.sub("", stem)
    return cleaned or stem


def get_env_int(name: str, default: int) -> int:
    """读取正整数环境变量，非法值回退默认。"""
    try:
        value = int(os.getenv(name, str(default)))
        return value if value > 0 else default
    except (TypeError, ValueError):
        return default


def get_llm_extra_headers() -> dict[str, str]:
    """读取 ``LLM_EXTRA_HEADERS``（JSON 对象）并返回 OpenAI 请求头。

    有些 OpenAI 兼容网关需要自定义请求头才能路由，例如 opencode zen 的
    ``x-opencode-session``、OpenRouter 的 ``HTTP-Referer``。配置示例：

        LLM_EXTRA_HEADERS={"x-opencode-session": "550e8400-e29b-41d4-a716-446655440000"}

    Returns:
        dict[str, str]: 请求头；未配置或格式非法时返回空字典（不阻断主流程）。
    """
    raw = (os.getenv("LLM_EXTRA_HEADERS") or "").strip()
    if not raw:
        return {}

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.warning("LLM_EXTRA_HEADERS 不是合法 JSON，已忽略", error=str(e))
        return {}

    if not isinstance(data, dict):
        logger.warning("LLM_EXTRA_HEADERS 必须是 JSON 对象，已忽略")
        return {}

    return {str(k): str(v) for k, v in data.items() if str(k).strip()}



def _find_balanced_json(text: str) -> str | None:
    """在文本中扫描第一段花括号平衡的 JSON 对象，返回字符串或 None。

    使用栈计数括号（跳过字符串内的括号），比贪婪正则 `\\{.*\\}` 更稳定，
    避免 LLM 说明中夹杂的 `{...}` 拖坏解析。
    """
    n = len(text)
    for start in range(n):
        if text[start] != '{':
            continue
        depth = 0
        in_str = False
        escape = False
        for i in range(start, n):
            ch = text[i]
            if escape:
                escape = False
                continue
            if ch == '\\':
                escape = True
                continue
            if ch == '"':
                in_str = not in_str
                continue
            if in_str:
                continue
            if ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    return text[start:i + 1]
        # 首个 '{' 起始的扫描已用尽，尝试下一个候选起点
    return None


def _try_load_json(json_str: str):
    """双重尝试解析：先原样，再做常见转义规范化。"""
    json_str = json_str.replace('{{', '{').replace('}}', '}')
    try:
        return json.loads(json_str, strict=False)
    except json.JSONDecodeError:
        try:
            fixed = json_str.replace('\\\\', '\\').replace("\\'", "'").replace('\\"', '"')
            return json.loads(fixed, strict=False)
        except json.JSONDecodeError:
            return None


def extract_json_from_response(response_text: str) -> dict:
    try:
        json_match = JSON_PATTERN.search(response_text)
        if json_match:
            parsed = _try_load_json(json_match.group(1))
            if parsed is not None:
                return parsed

        # 用栈匹配定位平衡的 JSON 对象，替代贪婪正则
        balanced = _find_balanced_json(response_text)
        if balanced:
            parsed = _try_load_json(balanced)
            if parsed is not None:
                return parsed

        parsed = _try_load_json(response_text)
        if parsed is not None:
            return parsed
    except Exception as e:
        logger.warning("Failed to extract JSON", error=str(e))
    return None

def extract_code_from_response(response_text: str) -> str:
    try:
        code_match = CODE_PATTERN.search(response_text)
        if code_match:
            return code_match.group(1)

        code_match = CODE_FALLBACK_PATTERN.search(response_text)
        if code_match:
            return code_match.group(1)

        # 提取不到代码块：返回空串（非代码文本不得当代码执行）
        return ""
    except Exception as e:
        logger.warning("Failed to extract code", error=str(e))
        return ""
