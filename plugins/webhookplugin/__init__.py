from nonebot import get_plugin_config, require, get_driver
from nonebot.plugin import PluginMetadata

require("nonebot_plugin_alconna")

from .config import Config

__plugin_meta__ = PluginMetadata(
    name="WebhookPlugin",
    description="Webhook 事件发送机器人,用于接收符合 json 规范的文本进行发送",
    usage="/webhook create user:用户1 group:群聊1 代号",
    config=Config,
)

config = get_plugin_config(Config)

from . import db
from . import api
from . import command
from . import sender
import asyncio

driver = get_driver()

@driver.on_startup
async def startup():
    await db.init_db()
    # 启动独立的 FastAPI 实例
    host = config.webhook_host
    port = config.webhook_port
    asyncio.create_task(api.start_webhook_server(host, port))



