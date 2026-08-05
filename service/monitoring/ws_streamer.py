"""WebSocket 实时事件推送器。

复用 flask_sock 机制，向前端实时推送 trace / error / token 事件。
"""

import json
from typing import Set


class WsStreamer:
    """按 task_id 管理 WebSocket 连接，广播事件到所有订阅者。"""

    def __init__(self):
        self._connections: dict[str, Set] = {}

    def register(self, task_id: str, ws):
        """注册一个 WebSocket 连接到指定 task_id。"""
        self._connections.setdefault(task_id, set()).add(ws)

    def unregister(self, task_id: str, ws):
        """注销连接。"""
        conns = self._connections.get(task_id)
        if conns:
            conns.discard(ws)
            if not conns:
                del self._connections[task_id]

    def broadcast(self, task_id: str, event: dict):
        """向所有订阅该 task_id 的 WebSocket 连接推送事件。

        无连接时静默跳过，不阻塞调用方。
        """
        conns = self._connections.get(task_id)
        if not conns:
            return

        data = json.dumps(event, ensure_ascii=False)
        dead = []
        for ws in conns:
            try:
                ws.send(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            conns.discard(ws)


ws_streamer = WsStreamer()
