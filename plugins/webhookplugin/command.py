import json
import uuid
from nonebot import require
require("nonebot_plugin_alconna")
from nonebot.permission import SUPERUSER

from arclet.alconna import Alconna, Args, Option, Subcommand, CommandMeta
from nonebot_plugin_alconna import on_alconna, Match, AlconnaMatch, Arparma
from sqlalchemy import select, delete

from .storage import Route, SystemConfig, AuditLog, async_session, save_field_map, init_db
from .sender import dict_to_formatted_str

# Nonebot Alconna 匹配路由注册器入口定义
webhook_cmd = on_alconna(
    Alconna(
        "webhook",
        Subcommand("create", 
            Option("user:", Args["user?", str], compact=True),
            Option("group:", Args["group?", str], compact=True),
            Args["code?", str]
        ),
        Subcommand("remove", Args["code?", str]),
        Subcommand("info", Args["code?", str]),
        Subcommand("list"),
        Subcommand("edit", 
            Args["code?", str],
            Option("name:", Args["name?", str], compact=True),
            Option("path:", Args["path?", str], compact=True),
            Option("token:", Args["token?", str], compact=True),
            Option("domain:", Args["domain?", str], compact=True),
            Option("dmview:", Args["dmview?", str], compact=True),
            Option("verify_token:", Args["verify_token?", str], compact=True)
        ),
        Subcommand("value",
            Subcommand("create", Args["raw?", str]["mapped?", str])
        ),
        Subcommand("msg", 
            Subcommand("view", Args["code?", str]["msg_id?", int])
        ),
        Subcommand("system", 
            Subcommand("edit", 
                Option("secure:", Args["secure?", str], compact=True),
                Option("nginx_mode:", Args["nginx_mode?", str], compact=True),
                Option("ratelimit:", Args["ratelimit?", str], compact=True)
            ),
            Subcommand("reload", Args["type?", str])
        ),
        meta=CommandMeta(description="Webhook Bot Management")
    ),
    permission=SUPERUSER,
    use_cmd_start=True
)

@webhook_cmd.handle()
async def default_help(arp: Arparma):
    if not arp.subcommands:
        help_msg = (
            "欢迎使用 WebhookBot!\n"
            "指令列表:\n"
            "/webhook create user:id,id group:id,id 代号 - 创建路由\n"
            "/webhook remove 代号 - 删除路由\n"
            "/webhook list - 显示所有实例代号\n"
            "/webhook info 代号 - 查询路由\n"
            "/webhook edit 代号 name:新名字 path:新路径 token:新秘钥 domain:新域名 dmview:true/false verify_token:join/header - 修改配置\n"
            "/webhook msg view 代号 1 - 查询代号实例的历史消息\n"
            "/webhook value create 原字段 映射词 - 创建消息映射字典\n"
            "/webhook system edit secure:true/false nginx_mode:true/false ratelimit:次数,时间(分)/clear - 配置系统模式\n"
            "/webhook system reload value/db/all - 重载映射词/数据库/全部"
        )
        await webhook_cmd.finish(help_msg)

@webhook_cmd.assign("create")
async def create_webhook(
    code: Match[str],
    user: Match[str],
    group: Match[str]
):
    if not code.available:
        await webhook_cmd.finish("请提供代号!")

    users = user.result.split(",") if user.available else []
    groups = group.result.split(",") if group.available else []
    
    if not users and not groups:
        await webhook_cmd.finish("❌️ 请至少提供一个用户或者群聊ID")

    path_uuid = str(uuid.uuid4().hex)
    token = str(uuid.uuid4().hex)[:16]

    async with async_session() as session:
        # 查询生成前判定重名代码
        exists = await session.scalar(select(Route).where(Route.code == code.result))
        if exists:
            await webhook_cmd.finish(f"代号 {code.result} 已存在!")
            return
        new_route = Route(
            code=code.result,
            path=path_uuid,
            token=token,
            users=json.dumps(users),
            groups=json.dumps(groups)
        )
        session.add(new_route)
        await session.commit()
        
    reply = f"✅ 成功为代号 {code.result} 创建 Webhook 路由!\n" \
            f"路径: {path_uuid}\n鉴权秘钥: {token}\n" \
            f"请将其拼接到 /webhook/{path_uuid}?token={token} 发送 POST 请求。"
    await webhook_cmd.send(reply)

@webhook_cmd.assign("remove")
async def remove_webhook(code: Match[str]):
    if not code.available:
        await webhook_cmd.finish("请提供代号!")

    async with async_session() as session:
        route = await session.scalar(select(Route).where(Route.code == code.result))
        if not route:
            await webhook_cmd.finish(f"❌️ 找不到代号为 {code.result} 的路由。")
            return
        await session.delete(route)
        await session.commit()
        
    await webhook_cmd.send(f"✅ 已删除代号 {code.result} 的 Webhook 路由!")

@webhook_cmd.assign("info")
async def info_webhook(code: Match[str]):
    if not code.available:
        await webhook_cmd.finish("请提供代号!")

    async with async_session() as session:
        route = await session.scalar(select(Route).where(Route.code == code.result))
        if not route:
            await webhook_cmd.finish(f"❌️ 找不到代号为 {code.result} 的路由。")
            return
        domains_list = json.loads(route.domains) if getattr(route, "domains", None) else []
        domains_str = ",".join(domains_list) if domains_list else "未配置"
        dmview_str = "允许 (true)" if getattr(route, "dmview", True) else "禁止 (false)"
        verify_token = getattr(route, "verify_token", "join")

        msg = []
        msg += f"代号: {route.code}"
        msg += f"名字: {getattr(route, 'name', '未设置') or '未设置'}"
        msg += f"路径: /webhook/{route.path}"
        msg += f"鉴权方式: {'路径拼接(join)' if verify_token == 'join' else '请求头(header)'}"
        msg += f"仅允许域名访问: {dmview_str}"
        if domains_str:
            msg += f"绑定域名: {domains_str}"
        msg += f"总调用次数: {route.total_calls}"
        if route.failed_calls:
            msg += f"调用失败次数: {route.failed_calls}"
        msg += f"创建日期: {route.created_at.strftime('%Y/%m/%d-%H:%M:%S')}"
        msg += f"最后修改日期: {route.updated_at.strftime('%Y年%m月%d日-%H:%M:%S')}"

        await webhook_cmd.send("\n".join(msg))

@webhook_cmd.assign("list")
async def list_webhooks():
    async with async_session() as session:
        routes = await session.scalars(select(Route.code))
        codes = routes.all()
        if not codes:
            await webhook_cmd.finish("当前没有任何实例。")
            return
        await webhook_cmd.send("当前存在的实例:\n" + "\n".join(codes))

@webhook_cmd.assign("edit")
async def edit_webhook(code: Match[str], name: Match[str], path: Match[str], token: Match[str], domain: Match[str], dmview: Match[str], verify_token: Match[str]):
    if not code.available:
        await webhook_cmd.finish("请提供代号!")
    if not any([name.available, path.available, token.available, domain.available, dmview.available, verify_token.available]):
        await webhook_cmd.finish("请至少提供 name, path, token, domain, dmview 或 verify_token 参数进行修改。\n示例：/webhook edit 代号 name:新名字 verify_token:header")

    async with async_session() as session:
        route = await session.scalar(select(Route).where(Route.code == code.result))
        if not route:
            await webhook_cmd.finish(f"找不到代号为 {code.result} 的路由。")
            return
        
        # 解释修改了什么东西
        changes = []
        if name.available:
            route.name = name.result
            changes.append(f"名字 -> {name.result}")
        if path.available:
            route.path = path.result
            changes.append(f"路径 -> {path.result}")
        if token.available:
            route.token = token.result
            changes.append(f"秘钥 -> {token.result}")
        if domain.available:
            # 切割并过滤空白
            parsed_domains = [d.strip() for d in domain.result.split(",") if d.strip()]
            route.domains = json.dumps(parsed_domains)
            changes.append(f"绑定域名 -> {parsed_domains}")
        if dmview.available:
            route.dmview = dmview.result.lower() == "true"
            changes.append(f"非绑定域名访问 -> {'允许(true)' if route.dmview else '禁止(false)'}")
        if verify_token.available:
            if verify_token.result not in ["join", "header"]:
                await webhook_cmd.finish("verify_token 参数只允许使用 'join' 或 'header'")
            route.verify_token = verify_token.result
            changes.append(f"鉴权方式 -> {'路径拼接(join)' if verify_token.result == 'join' else '请求头(header)'}")
            
        await session.commit()
        
    changes_str = "\n".join([f"- {c}" for c in changes])
    await webhook_cmd.send(f"✅ 已成功修改代号 {code.result} 的信息:\n{changes_str}")

@webhook_cmd.assign("msg.view")
async def msg_view(code: Match[str], msg_id: Match[int]):
    if not code.available or not msg_id.available:
        await webhook_cmd.finish("请提供代号和编号!\n示例：/webhook msg view 代号 1")
    
    target_code = code.result
    target_id = msg_id.result
    
    if target_id < 1:
        await webhook_cmd.finish("编号必须大于等于 1。")

    async with async_session() as session:
        # 考虑到仅推送成功的或者即使推送失败但是在 sender 内确实处理过的信息才会+1
        # api内如果403拦截了（拦截域名或者token非法）由于没进入sender所以不应该算作正常的编号系列内（或者是独立的一套？）
        # 在之前逻辑中，route.total_calls 只有在 broadcast 后才会+1
        # 所以对应的记录是 status IN ('success', 'partial', 'failed')
        stmt = select(AuditLog).where(
            AuditLog.route_code == target_code,
            AuditLog.status.in_(["success", "partial", "failed"])
        ).order_by(AuditLog.id).offset(target_id - 1).limit(1)
        
        log = await session.scalar(stmt)
        if not log:
            await webhook_cmd.finish(f"未找到代号 {target_code} 的第 {target_id} 条历史访问记录。")
            return
            
        try:
            payload = json.loads(log.payload)
        except Exception:
            payload = {"Raw Payload": log.payload}
            
        msg_text = await dict_to_formatted_str(target_code, payload, target_id, log.called_at, log.client_ip)
        
    await webhook_cmd.send(msg_text)

@webhook_cmd.assign("value.create")
async def create_value_map(raw: Match[str], mapped: Match[str]):
    if not raw.available or not mapped.available:
        await webhook_cmd.finish("请提供原始值和代词!\n示例：/webhook value create raw mapped")

    save_field_map(raw.result, mapped.result)
        
    await webhook_cmd.send(f"✅ 特殊值映射创建成功：{raw.result} -> {mapped.result}")

@webhook_cmd.assign("system.edit")
async def edit_system(secure: Match[str], nginx_mode: Match[str], ratelimit: Match[str]):
    if not secure.available and not nginx_mode.available and not ratelimit.available:
        await webhook_cmd.finish("❌️ 请至少提供一项系统配置：secure/nginx_mode/ratelimit")
        
    updates = []
    async with async_session() as session:
        if secure.available:
            val_str = "true" if secure.result.lower() == "true" else "false"
            conf = await session.scalar(select(SystemConfig).where(SystemConfig.key == "secure_mode"))
            if conf:
                conf.value = val_str
            else:
                session.add(SystemConfig(key="secure_mode", value=val_str))
            updates.append(f"严格模式 (secure) -> {val_str}")
            
        if nginx_mode.available:
            val_str = "true" if nginx_mode.result.lower() == "true" else "false"
            conf = await session.scalar(select(SystemConfig).where(SystemConfig.key == "nginx_mode"))
            if conf:
                conf.value = val_str
            else:
                session.add(SystemConfig(key="nginx_mode", value=val_str))
            updates.append(f"Nginx代理透传支持 (nginx_mode) -> {val_str}")
            
        if ratelimit.available:
            val = ratelimit.result.lower()
            if val == "clear":
                val_str = "clear"
                updates.append("速率限制 (ratelimit) -> 已清除(无限制)")
            else:
                try:
                    c, t = val.split(",")
                    c = int(c)
                    t = int(t)
                    if c <= 0 or t <= 0:
                        raise ValueError
                    val_str = f"{c},{t}"
                    updates.append(f"速率限制 (ratelimit) -> 当一IP在 {t} 分钟内最多 {c} 次")
                except Exception:
                    await webhook_cmd.finish("❌️ ratelimit 参数格式错误！请使用 '次数,时间(分)'（例如 10,1 代表每分钟10次）或 'clear' 清除限制。")
            
            conf = await session.scalar(select(SystemConfig).where(SystemConfig.key == "ratelimit"))
            if conf:
                conf.value = val_str
            else:
                session.add(SystemConfig(key="ratelimit", value=val_str))
            
        await session.commit()
        
    await webhook_cmd.send("✅ 系统设定已更新：\n- " + "\n- ".join(updates))

@webhook_cmd.assign("system.reload")
async def reload_system(type: Match[str]):
    if not type.available:
        await webhook_cmd.finish("❌ 请指定重载类型，例如 value, db 或 all\n示例：/webhook system reload all")
        
    target = type.result.lower()
    if target not in ["value", "db", "all"]:
        await webhook_cmd.finish("❌ 错误的参数。仅支持 value, db 或 all")

    msg_lines = []
    
    # 目前 value(field_maps.json) 是每次读取时直接访问磁盘的，本身即为"热重载"的。
    # 这里为了满足用户的重载认知流程和未来可能扩展的缓存机制，显式进行反馈提醒。
    if target in ["value", "all"]:
        from .storage import get_field_maps
        get_field_maps() # 预读一次验证是否能读通
        msg_lines.append("✅ 映射词 (value) 已重载刷新")
        
    if target in ["db", "all"]:
        # 执行数据库模型初始化和同步测试
        try:
            await init_db()
            msg_lines.append("✅ 数据库 (db) 引擎配置与状态已经重新同步")
        except Exception as e:
            msg_lines.append(f"❌ 数据库 (db) 重载时发生异常: {str(e)}")

    await webhook_cmd.send("\n".join(msg_lines))
