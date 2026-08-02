"""请求体 Schema(响应统一用 services/serialize.py 输出 dict)。

2026-07-26 由单文件 schemas.py 拆为按域子模块;本包 __init__ 全量回导,
``from app import schemas`` / ``from app.schemas import X`` 的既有用法不变,
OpenAPI 模型名不变(前端 api-types.ts 无漂移)。新增 schema 写进对应域文件。
"""
# ruff: noqa: F401,F403
from app.schemas.common import *
from app.schemas.users import *
from app.schemas.games import *
from app.schemas.uploads import *
from app.schemas.memory import *
from app.schemas.agent_events import *
from app.schemas.agent_events import _AgentLogEventBaseOut
from app.schemas.tasks import *
