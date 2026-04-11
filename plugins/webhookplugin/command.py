import json
import uuid
from nonebot import require, get_plugin_config
require("nonebot_plugin_alconna")
from nonebot.permission import SUPERUSER

from arclet.alconna import Alconna, Args, Option, Subcommand, CommandMeta
from nonebot_plugin_alconna import on_alconna, Match, AlconnaMatch, Arparma
from sqlalchemy import select, delete

from .storage import (
    Route, SystemConfig, AuditLog, async_session, 
    save_field_map, delete_field_map, add_blackword, delete_blackword, init_db,
    load_field_maps, load_blackwords
)
from .sender import dict_to_formatted_str

from .config import Config
config = get_plugin_config(Config)

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
            Option("verify_token:", Args["verify_token?", str], compact=True),
            Option("ratelimit:", Args["ratelimit?", str], compact=True)
        ),
        Subcommand("map_word",
            Subcommand("create", Args["raw?", str]["mapped?", str]),
            Subcommand("del", Args["del_raw?", str])
        ),
        Subcommand("blackword",
            Subcommand("add", Args["raw?", str]["mapped?", str]["match_type?", str]),
            Subcommand("del", Args["del_raw?", str])
        ),
        Subcommand("msg", 
            Subcommand("view", Args["code?", str]["msg_id?", int])
        ),
        Subcommand("system", 
            Subcommand("edit", 
                Option("secure:", Args["secure?", str], compact=True),
                Option("nginx_mode:", Args["nginx_mode?", str], compact=True)
            ),
            Subcommand("reload", Args["reload_type", str])
        ),
        meta=CommandMeta(description="Webhook Bot Management")
    ),
    permission=SUPERUSER,
    use_cmd_start=True
)

@webhook_cmd.handle()
async def default_help(arp: Arparma):
    if not arp.subcommands:
        msg = []
        msg.append("欢迎,这里是 WebhookBot 的帮助文档！")
        msg.append("你必须要**输入指令前缀**(若为空则无视)才能触发本插件功能")
        msg.append("指令列表:")
        msg.append("webhook create - 创建一个代号为 [name] 的 Webhook 路由")
        msg.append("  - 选项: [user:id] [group:id] [name]")
        msg.append("  - [user] 和 [group] 可任选其一添加,[name] 不会影响你最终创建的路径")
        msg.append("webhook remove [name] - 删除代号为 [name] 的 Webhook 路由")
        msg.append("webhook list - 显示所有 Webhook 路由的代号")
        msg.append("webhook info [name] - 查询代号为 [name] 的路由")
        msg.append("webhook edit [name] - 修改代号为 [name] 的路由信息")
        msg.append("  - 选项: [name:新代号] [path:新路径] [token:新秘钥] [domain:新域名] [dmview:true/false] [verify_token:join/header] [ratelimit:次数,时间(分)/clear]")
        msg.append("  - 具体参数说明请输入 webhook edit 查看")
        msg.append("webhook msg view [name] [number] - 查询代号为 [name] 的第 [number] 条消息")
        msg.append("webhook map_word create [word] [new_word] - 创建一个将 [word] 属性值替换成 [new_word] 的映射词")
        msg.append("webhook map_word del [word] - 删除名为 [word] 的属性替换词")
        msg.append("webhook blackword add [bkwd] [new_bkwd] [模糊/严格] - 添加一个将 [bkwd] 黑名单词替换成 [new_bkwd] 的映射词")
        msg.append("  - 模糊匹配会直接替换文本所有的 [bkwd],严格匹配只会允许文本完全匹配 [bkwd] 才会替换")
        msg.append("webhook map_word del [bkwd] - 删除名为 [bkwd] 的黑名单替换词")
        msg.append("webhook system edit - 修改系统配置")
        msg.append("  - 选项 [secure:true/false](严格模式) [nginx_mode:true/false](Nginx 支持模式)")
        msg.append("webhook system reload - 重载配置/数据文件")
        msg.append("  - 选项 [map_word/db/blackword/all](映射词/数据库/黑名单词/全部)")
        await webhook_cmd.finish("\n".join(msg))

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
        dmview_str = "打开 (true)" if getattr(route, "dmview", True) else "关闭 (false)"
        verify_token = getattr(route, "verify_token", "join")
        rl_val = getattr(route, "ratelimit", None)
        ratelimit_str = f"每 {rl_val.split(',')[1]} 分钟 {rl_val.split(',')[0]} 次" if rl_val else "未设置或无限制"

        msg = []
        msg.append(f"代号: {route.code}")
        msg.append(f"名字: {getattr(route, 'name', '未设置') or '未设置'}")
        msg.append(f"路径: /webhook/{route.path}")
        msg.append(f"鉴权方式: {'路径拼接(join)' if verify_token == 'join' else '请求头(header)'}")
        msg.append(f"仅允许域名访问: {dmview_str}")
        if domains_str:
            msg.append(f"绑定域名: {domains_str}")
        msg.append(f"速率限制: {ratelimit_str}")
        msg.append(f"总调用次数: {route.total_calls}")
        if route.failed_calls:
            msg.append(f"调用失败次数: {route.failed_calls}")
        msg.append(f"创建日期: {route.created_at.strftime('%Y/%m/%d-%H:%M:%S')}")
        msg.append(f"最后修改日期: {route.updated_at.strftime('%Y年%m月%d日-%H:%M:%S')}")

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
async def edit_webhook(code: Match[str], name: Match[str], path: Match[str], token: Match[str], domain: Match[str], dmview: Match[str], verify_token: Match[str], ratelimit: Match[str]):
    if not code.available:
        msg = []
        msg.append("webhook edit [name] - 修改代号为 [name] 的路由信息")
        msg.append("  - 选项: [name:新代号] [path:新路径] [token:新秘钥] [domain:新域名] [dmview:true/false] [verify_token:join/header] [ratelimit:次数,时间(分)/clear]")
        msg.append("  - 具体参数说明：")
        msg.append("  - name: 修改代号")
        msg.append("  - path: 修改路径")
        msg.append("  - token: 修改秘钥")
        msg.append("  - domain: 修改绑定域名，多个域名请用英文逗号分隔")
        msg.append("  - dmview: 仅允许域名访问, true为打开(仅允许域名访问), false为关闭(域名或IP均可访问)")
        msg.append("  - verify_token: 修改鉴权方式,join为路径拼接(默认), header为请求头")
        msg.append("  - ratelimit: 修改速率限制,格式为 '次数,时间(分)','clear' 为无速率限制")
        msg.append("")
        msg.append("你触发此帮助的情况有两种:")
        msg.append("  - 你没有提供 [name] 参数")
        msg.append("  - 纯粹的想查看帮助文档(判断逻辑如上)")
        await webhook_cmd.finish("\n".join(msg))
    if not any([name.available, path.available, token.available, domain.available, dmview.available, verify_token.available, ratelimit.available]):
        await webhook_cmd.finish("请至少提供 name, path, token, domain, dmview, verify_token 或 ratelimit 参数进行修改。\n示例：/webhook edit 代号 ratelimit:10,1")

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
            changes.append(f"仅允许域名访问 -> {'打开(true)' if route.dmview else '关闭(false)'}")
        if verify_token.available:
            if verify_token.result not in ["join", "header"]:
                await webhook_cmd.finish("verify_token 参数只允许使用 'join' 或 'header'")
            route.verify_token = verify_token.result
            changes.append(f"鉴权方式 -> {'路径拼接(join)' if verify_token.result == 'join' else '请求头(header)'}")

        if ratelimit.available:
            val = ratelimit.result.lower()
            if val == "clear":
                route.ratelimit = None
                changes.append("速率限制 -> 已清除(无限制)")
            else:
                try:
                    c_str, t_str = val.split(",")
                    c, t = int(c_str.strip()), int(t_str.strip())
                    if c <= 0 or t <= 0:
                        await webhook_cmd.finish("❌️ ratelimit 次数和时间必须大于0！")
                    route.ratelimit = f"{c},{t}"
                    changes.append(f"速率限制 -> 同一IP在 {t} 分钟内最多 {c} 次")
                except Exception:
                    await webhook_cmd.finish("❌️ ratelimit 参数格式错误！请使用 '次数,时间(分)'（例如 10,1）或 'clear'")

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

@webhook_cmd.assign("map_word.create")
async def create_value_map(raw: Match[str], mapped: Match[str]):
    if not raw.available or not mapped.available:
        await webhook_cmd.finish("请提供原始值和代词!\n示例：/webhook map_word create raw mapped")

    save_field_map(raw.result, mapped.result)
        
    await webhook_cmd.send(f"✅ 特殊值映射创建成功：{raw.result} -> {mapped.result}")

@webhook_cmd.assign("map_word.del")
async def delete_value_map(del_raw: Match[str]):
    if not del_raw.available:
        await webhook_cmd.finish("请提供要删除的特殊值原始名!\n示例：/webhook map_word del raw")
        
    if delete_field_map(del_raw.result):
        await webhook_cmd.send(f"✅ 特殊值映射删除成功：{del_raw.result}")
    else:
        await webhook_cmd.finish(f"❌ 找不到需要删除的映射词：{del_raw.result}")

@webhook_cmd.assign("blackword.add")
async def add_blackword_map(raw: Match[str], mapped: Match[str], match_type: Match[str]):
    if not raw.available or not mapped.available:
        await webhook_cmd.finish("请提供原始值和映射值!\n示例：/webhook blackword add 原文 被替换文 [严格/模糊]")
        
    m_type = "模糊"
    if match_type.available and match_type.result in ["严格", "模糊"]:
        m_type = match_type.result
    
    add_blackword(raw.result, mapped.result, m_type)
    await webhook_cmd.send(f"✅ 黑名单词添加成功：{raw.result} -> {mapped.result} ({m_type}匹配)")

@webhook_cmd.assign("blackword.del")
async def del_blackword_map(del_raw: Match[str]):
    if not del_raw.available:
        await webhook_cmd.finish("请提供要删除的黑名单词原文!\n示例：/webhook blackword del 原文")
        
    if delete_blackword(del_raw.result):
        await webhook_cmd.send(f"✅ 黑名单词删除成功：{del_raw.result}")
    else:
        await webhook_cmd.finish(f"❌ 找不到该黑名单词：{del_raw.result}")

@webhook_cmd.assign("system.edit")
async def edit_system(secure: Match[str], nginx_mode: Match[str]):
    if not secure.available and not nginx_mode.available:
        await webhook_cmd.finish("❌️ 请至少提供一项系统配置：secure/nginx_mode")
        
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
            updates.append(f"Nginx 代理透传支持 (nginx_mode) -> {val_str}")
            
        await session.commit()
        
    await webhook_cmd.send("✅ 系统设定已更新：\n- " + "\n- ".join(updates))

@webhook_cmd.assign("system.reload")
async def reload_system(arp: Arparma):
    reload_type = arp.query("system.reload.reload_type")
    if not reload_type:
        await webhook_cmd.finish("❌ 请指定重载类型，例如 map_word, blackword, db 或 all\n示例：/webhook system reload all")
        
    target = str(reload_type).lower()
    if target not in ["map_word", "blackword", "db", "all"]:
        await webhook_cmd.finish("❌ 错误的参数。仅支持 map_word, blackword, db 或 all")

    msg_lines = []
    
    # 重新加载 map_word(field_maps.json) 缓存字典
    if target in ["map_word", "all"]:
        from .storage import load_field_maps
        load_field_maps() # 重新从本地磁盘读取映射词写入内存缓存
        msg_lines.append("✅ 映射词 (map_word) 缓存已重载刷新")

    # 重新加载 blackwords 缓存
    if target in ["blackword", "all"]:
        from .storage import load_blackwords
        load_blackwords()
        msg_lines.append("✅ 黑名单词 (blackword) 缓存已重载刷新")
        
    if target in ["db", "all"]:
        # 执行数据库模型初始化和同步测试
        try:
            await init_db()
            msg_lines.append("✅ 数据库 (db) 引擎配置与状态已经重新同步")
        except Exception as e:
            msg_lines.append(f"❌ 数据库 (db) 重载时发生异常: {str(e)}")

    await webhook_cmd.send("\n".join(msg_lines))
