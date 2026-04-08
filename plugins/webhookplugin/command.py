import json
import uuid
from nonebot import require
require("nonebot_plugin_alconna")
from nonebot.permission import SUPERUSER

from arclet.alconna import Alconna, Args, Option, Subcommand, CommandMeta
from nonebot_plugin_alconna import on_alconna, Match, AlconnaMatch, Arparma
from sqlalchemy import select, delete

from .db import Route, FieldMap, SystemConfig, async_session

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
        Subcommand("edit", 
            Args["code?", str],
            Option("path:", Args["path?", str], compact=True),
            Option("token:", Args["token?", str], compact=True),
            Option("domain:", Args["domain?", str], compact=True),
            Option("dmview:", Args["dmview?", str], compact=True)
        ),
        Subcommand("value",
            Subcommand("create", Args["raw?", str]["mapped?", str])
        ),
        Subcommand("system", Subcommand("edit", Option("secure:", Args["secure?", str], compact=True))),
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
            "/webhook info 代号 - 查询路由\n"
            "/webhook edit 代号 path:新路径 token:新秘钥 domain:新域名 dmview:true/false - 修改配置\n"
            "/webhook value create 原字段 映射词 - 创建消息映射字典\n"
            "/webhook system edit secure:true/false - 严格模式全局开关"
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
        
        info_str = (
            f"代号: {route.code}\n"
            f"路径: /webhook/{route.path}\n"
            f"非绑定域名访问: {dmview_str}\n"
            f"绑定域名: {domains_str}\n"
            f"总调用次数: {route.total_calls}\n"
            f"调用失败次数: {route.failed_calls}\n"
            f"创建日期: {route.created_at.strftime('%Y/%m/%d-%H:%M:%S')}\n"
            f"最后修改日期: {route.updated_at.strftime('%Y/%m/%d-%H:%M:%S')}"
        )
        await webhook_cmd.send(info_str)

@webhook_cmd.assign("edit")
async def edit_webhook(code: Match[str], path: Match[str], token: Match[str], domain: Match[str], dmview: Match[str]):
    if not code.available:
        await webhook_cmd.finish("请提供代号!")
    if not any([path.available, token.available, domain.available, dmview.available]):
        await webhook_cmd.finish("请至少提供 path, token, domain 或 dmview 参数进行修改。\n示例：/webhook edit 代号 path:xxx token:xxx")

    async with async_session() as session:
        route = await session.scalar(select(Route).where(Route.code == code.result))
        if not route:
            await webhook_cmd.finish(f"找不到代号为 {code.result} 的路由。")
            return
        if path.available:
            route.path = path.result
        if token.available:
            route.token = token.result
        if domain.available:
            # 切割并过滤空白
            parsed_domains = [d.strip() for d in domain.result.split(",") if d.strip()]
            route.domains = json.dumps(parsed_domains)
        if dmview.available:
            route.dmview = dmview.result.lower() == "true"
            
        await session.commit()
        
    await webhook_cmd.send(f"✅ 已成功修改代号 {code.result} 的信息。")

@webhook_cmd.assign("value.create")
async def create_value_map(raw: Match[str], mapped: Match[str]):
    if not raw.available or not mapped.available:
        await webhook_cmd.finish("请提供原始值和代词!\n示例：/webhook value create raw mapped")

    async with async_session() as session:
        existing = await session.scalar(select(FieldMap).where(FieldMap.raw_field == raw.result))
        if existing:
            existing.mapped_field = mapped.result
        else:
            new_map = FieldMap(raw_field=raw.result, mapped_field=mapped.result)
            session.add(new_map)
        await session.commit()
        
    await webhook_cmd.send(f"✅ 特殊值映射创建成功：{raw.result} -> {mapped.result}")

@webhook_cmd.assign("system.edit")
async def edit_system(secure: Match[str]):
    if not secure.available:
        await webhook_cmd.finish("❌️ 参数不足，比如 secure:true")
        
    val_str = "true" if secure.result.lower() == "true" else "false"
    async with async_session() as session:
        conf = await session.scalar(select(SystemConfig).where(SystemConfig.key == "secure_mode"))
        if conf:
            conf.value = val_str
        else:
            session.add(SystemConfig(key="secure_mode", value=val_str))
        await session.commit()
        
    await webhook_cmd.send(f"✅ 严格模式已设置为 {val_str}")
