import json
import sys
from pathlib import Path

try:
    from agent import BaseAgent
    from service.exceptions import ConfigError
except ImportError:
    from ..agent import BaseAgent
    from .exceptions import ConfigError

def get_agent_class(agent_name, agent_url, agent_key, mcp_config):
    return BaseAgent(agent_name, agent_url, agent_key, mcp_config, verbose=True)

def load_config(config_path=None):
    if config_path is None:
        config_path = Path(__file__).parent.parent / "configs" / "default_config.json"
    else:
        config_path = Path(config_path)

    if not config_path.exists():
        raise ConfigError(f"Configuration file does not exist: {config_path}")

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
        _normalize_mcp_python_command(config)
        print(f"✅ Successfully loaded configuration file: {config_path}")
        return config
    except json.JSONDecodeError as e:
        raise ConfigError(f"Configuration file JSON format error: {e}") from e
    except Exception as e:
        raise ConfigError(f"Failed to load configuration file: {e}") from e


def _normalize_mcp_python_command(config: dict) -> None:
    """把 mcp_config 中 `"command": "python"` 替换为当前解释器绝对路径。

    避免在 venv 环境下 subprocess 拿到系统 python 导致模块缺失。
    """
    mcp_cfg = config.get("mcp_config") or {}
    for _name, server in mcp_cfg.items():
        if isinstance(server, dict) and server.get("command") in ("python", "python3", "py"):
            server["command"] = sys.executable
