"""WebSocket：实时面试事件推送。

前端在面试进行中通过 WebSocket 订阅本场面试的实时事件
（面试官出题中 / 本轮评分完成 / 面试结束），主数据仍走 REST。

鉴权：浏览器 WebSocket 握手无法携带 Authorization 头，故 token 通过查询参数传入，
服务端复用 JWT 解析逻辑校验，并确认面试归属当前用户。
"""
import logging
import uuid
from typing import Any, Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from jose import JWTError, jwt
from sqlalchemy import select

from app.config import settings
from app.database import AsyncSessionLocal
from app.models.interview import Interview

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["websocket"])


class ConnectionManager:
    """interview_id -> 该场面试已连接的 WebSocket 集合"""

    def __init__(self) -> None:
        self._rooms: dict[str, set[WebSocket]] = {}

    async def connect(self, interview_id: str, ws: WebSocket) -> None:
        await ws.accept()
        self._rooms.setdefault(interview_id, set()).add(ws)

    def disconnect(self, interview_id: str, ws: WebSocket) -> None:
        room = self._rooms.get(interview_id)
        if room is not None:
            room.discard(ws)
            if not room:
                self._rooms.pop(interview_id, None)

    async def broadcast(self, interview_id: str, message: dict[str, Any]) -> None:
        room = self._rooms.get(interview_id)
        if not room:
            return
        dead: list[WebSocket] = []
        for ws in list(room):
            try:
                await ws.send_json(message)
            except Exception:  # noqa: BLE001  单连接失败不影响其它连接
                dead.append(ws)
        for ws in dead:
            self.disconnect(interview_id, ws)


manager = ConnectionManager()


def _decode_token(token: str) -> Optional[uuid.UUID]:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        return uuid.UUID(payload.get("sub"))
    except (JWTError, ValueError, TypeError, AttributeError):
        return None


async def _owns_interview(user_id: uuid.UUID, interview_id: str) -> bool:
    try:
        iid = uuid.UUID(interview_id)
    except ValueError:
        return False
    async with AsyncSessionLocal() as session:
        row = await session.execute(select(Interview).where(Interview.id == iid))
        interview = row.scalar_one_or_none()
        return interview is not None and interview.user_id == user_id


@router.websocket("/ws/interviews/{interview_id}")
async def interview_ws(websocket: WebSocket, interview_id: str, token: str = ""):
    user_id = _decode_token(token) if token else None
    if user_id is None:
        await websocket.close(code=4401)
        return
    if not await _owns_interview(user_id, interview_id):
        await websocket.close(code=4403)
        return

    await manager.connect(interview_id, websocket)
    try:
        await websocket.send_json({"type": "connected", "interview_id": interview_id})
        while True:
            # 只用来感知客户端是否断开；客户端基本不发消息
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(interview_id, websocket)
    except Exception:  # noqa: BLE001
        manager.disconnect(interview_id, websocket)
