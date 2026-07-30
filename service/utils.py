import re
import json

JSON_PATTERN = re.compile(r'```json\s*(.*?)\s*```', re.DOTALL)
CODE_PATTERN = re.compile(r'```python\s*(.*?)\s*```', re.DOTALL)
CODE_FALLBACK_PATTERN = re.compile(r'```\s*(.*?)\s*```', re.DOTALL)
CHART_PATH_PATTERN = re.compile(r'chart_.*?\.html')


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
        print(f"⚠️  Failed to extract JSON: {e}")
    return None

def extract_code_from_response(response_text: str) -> str:
    try:
        code_match = CODE_PATTERN.search(response_text)
        if code_match:
            return code_match.group(1)

        code_match = CODE_FALLBACK_PATTERN.search(response_text)
        if code_match:
            return code_match.group(1)

        return response_text
    except Exception as e:
        print(f"⚠️  Failed to extract code: {e}")
        return response_text
