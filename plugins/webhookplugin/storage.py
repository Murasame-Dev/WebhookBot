import json
from pathlib import Path
from datetime import datetime
from nonebot import get_plugin_config
from sqlalchemy import Integer, String, DateTime, Text
from sqlalchemy.orm import Mapped, mapped_column, DeclarativeBase
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from .config import Config

config = get_plugin_config(Config)
data_path = Path(config.webhook_data_path)
data_path.mkdir(parents=True, exist_ok=True)

# 处理获取绝对路径还是相对路径。sqlite+aiosqlite要求路径格式要是正确形式
# Windows下绝对路径：sqlite+aiosqlite:///C:/path/to/db.sqlite
db_filepath = data_path.absolute() / "webhook.db"
json_filepath = data_path.absolute() / "field_maps.json"

db_url = f"sqlite+aiosqlite:///{str(db_filepath).replace('\\', '/')}"

class Base(DeclarativeBase):
    pass

class Route(Base):
    __tablename__ = "webhook_routes"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=True) # 实例名字
    path: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    token: Mapped[str] = mapped_column(String(255))
    verify_token: Mapped[str] = mapped_column(String(50), default="join") # join(路径拼接) 或 header(请求头)
    users: Mapped[str] = mapped_column(Text(), default="[]")  # 保存为 JSON 数组字符串格式的私聊用户 ID 列表
    groups: Mapped[str] = mapped_column(Text(), default="[]") # 保存为 JSON 数组字符串格式的群聊 ID 列表
    domains: Mapped[str] = mapped_column(Text(), default="[]") # 保存为 JSON 数组字符串格式的绑定域名白名单
    dmview: Mapped[bool] = mapped_column(default=True) # 是否允许非绑定域名的主机头或纯 IP 进行访问
    ratelimit: Mapped[str] = mapped_column(String(50), nullable=True) # 实例独立的速率限制。值为 "次数,分钟" 或 null
    total_calls: Mapped[int] = mapped_column(Integer(), default=0)
    failed_calls: Mapped[int] = mapped_column(Integer(), default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class AuditLog(Base):
    __tablename__ = "webhook_audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    route_code: Mapped[str] = mapped_column(String(255), index=True)
    payload: Mapped[str] = mapped_column(Text())
    status: Mapped[str] = mapped_column(String(50))
    message: Mapped[str] = mapped_column(Text(), nullable=True)
    client_ip: Mapped[str] = mapped_column(String(50), nullable=True) # 请求者的 IP 地址
    called_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class SystemConfig(Base):
    __tablename__ = "webhook_system_config"
    
    key: Mapped[str] = mapped_column(String(255), primary_key=True)
    value: Mapped[str] = mapped_column(Text())

engine = create_async_engine(
    db_url,
    connect_args={"check_same_thread": False},
    echo=False
)
async_session = async_sessionmaker(engine, expire_on_commit=False)

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # 用轻量的方式给可能已经存在的旧表添加新列，异常说明列已经存在
        try:
            from sqlalchemy import text
            await conn.execute(text("ALTER TABLE webhook_routes ADD COLUMN ratelimit VARCHAR(50);"))
        except Exception:
            pass
        
    # 初始化 json 数据文件
    if not json_filepath.exists():
        with open(json_filepath, "w", encoding="utf-8") as f:
            json.dump({"map_word": {}, "blackword": []}, f, ensure_ascii=False, indent=4)
            
    # 初始化读取映射词和黑名单词缓存
    load_json_cache()

_JSON_CACHE = None

def load_json_cache():
    global _JSON_CACHE
    if not json_filepath.exists():
        _JSON_CACHE = {"map_word": {}, "blackword": []}
        return
    with open(json_filepath, "r", encoding="utf-8") as f:
        try:
            _JSON_CACHE = json.load(f)
        except json.JSONDecodeError:
            _JSON_CACHE = {"map_word": {}, "blackword": []}

def load_field_maps():
    load_json_cache()

def load_blackwords():
    load_json_cache()

def get_field_maps() -> dict:
    global _JSON_CACHE
    if _JSON_CACHE is None:
        load_json_cache()
    return _JSON_CACHE["map_word"]

def get_blackwords() -> list:
    global _JSON_CACHE
    if _JSON_CACHE is None:
        load_json_cache()
    return _JSON_CACHE["blackword"]

def save_field_map(raw_field: str, mapped_field: str):
    global _JSON_CACHE
    if _JSON_CACHE is None:
        load_json_cache()
    _JSON_CACHE["map_word"][raw_field] = mapped_field
    with open(json_filepath, "w", encoding="utf-8") as f:
        json.dump(_JSON_CACHE, f, ensure_ascii=False, indent=4)

def delete_field_map(raw_field: str) -> bool:
    global _JSON_CACHE
    if _JSON_CACHE is None:
        load_json_cache()
    
    if raw_field in _JSON_CACHE["map_word"]:
        del _JSON_CACHE["map_word"][raw_field]
        with open(json_filepath, "w", encoding="utf-8") as f:
            json.dump(_JSON_CACHE, f, ensure_ascii=False, indent=4)
        return True
    return False

def add_blackword(word: str, mapped: str, match_type: str = "模糊"):
    global _JSON_CACHE
    if _JSON_CACHE is None:
        load_json_cache()
        
    words = _JSON_CACHE["blackword"]
    words = [w for w in words if w.get("word") != word]
    words.append({"word": word, "mapped": mapped, "match_type": match_type})
    _JSON_CACHE["blackword"] = words
    
    with open(json_filepath, "w", encoding="utf-8") as f:
        json.dump(_JSON_CACHE, f, ensure_ascii=False, indent=4)

def delete_blackword(word: str) -> bool:
    global _JSON_CACHE
    if _JSON_CACHE is None:
        load_json_cache()
        
    words = _JSON_CACHE["blackword"]
    filtered = [w for w in words if w.get("word") != word]
    if len(filtered) < len(words):
        _JSON_CACHE["blackword"] = filtered
        with open(json_filepath, "w", encoding="utf-8") as f:
            json.dump(_JSON_CACHE, f, ensure_ascii=False, indent=4)
        return True
    return False

