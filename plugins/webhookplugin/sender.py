import json
from datetime import datetime
from nonebot import logger
from nonebot_plugin_alconna import Target, UniMessage
from sqlalchemy import select

from .storage import Route, AuditLog, async_session, get_field_maps

async def dict_to_formatted_str(code: str, payload_dict: dict, msg_index: int, dt: datetime = None) -> str:
    # 获取所有的映射
    maps = get_field_maps()
    
    if dt is None:
        dt = datetime.now()
    server_time = dt.strftime("%Y/%m/%d-%H:%M:%S")
    
    lines = [f"代号 {code} 发送了以下消息:"]
    for k, v in payload_dict.items():
        mapped_key = maps.get(k, k)
        lines.append(f"{mapped_key}: {v}\n")
    
    lines.append(f"编号: {msg_index}")
    lines.append(f"接收时间(服务器侧): {server_time}")
    return "\n".join(lines)


async def broadcast_webhook_message(route_code: str, payload_dict: dict):
    # Retrieve Route
    async with async_session() as session:
        route: Route = await session.scalar(select(Route).where(Route.code == route_code))
        if not route:
            logger.error(f"Route {route_code} not found when generating message")
            return
            
        users: list[str] = json.loads(route.users)
        groups: list[str] = json.loads(route.groups)
        
        msg_index = route.total_calls + 1
    
    msg_text = await dict_to_formatted_str(route_code, payload_dict, msg_index)
    um_msg = UniMessage.text(msg_text)

    # Broadcast
    failed_calls = 0
    total_calls = len(users) + len(groups)
    
    for uid in users:
        try:
            await um_msg.send(Target(uid, private=True))
        except Exception as e:
            logger.error(f"Failed to send to user {uid}: {e}")
            failed_calls += 1
            
    for gid in groups:
        try:
            await um_msg.send(Target(gid, private=False))
        except Exception as e:
            logger.error(f"Failed to send to group {gid}: {e}")
            failed_calls += 1

    # Update counts
    async with async_session() as session:
        route = await session.scalar(select(Route).where(Route.code == route_code))
        route.total_calls += 1
        route.failed_calls += failed_calls
        
        # Log Audit
        audit = AuditLog(
            route_code=route_code,
            payload=json.dumps(payload_dict, ensure_ascii=False),
            status="success" if failed_calls == 0 else ("partial" if failed_calls < total_calls else "failed"),
            message=f"{failed_calls}/{total_calls} fails"
        )
        session.add(audit)
        await session.commit()
