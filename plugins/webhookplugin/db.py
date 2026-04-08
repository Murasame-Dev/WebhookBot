from datetime import datetime
from sqlalchemy import Integer, String, DateTime, Text
from sqlalchemy.orm import Mapped, mapped_column, DeclarativeBase
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

class Base(DeclarativeBase):
    pass

class Route(Base):
    __tablename__ = "webhook_routes"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    path: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    token: Mapped[str] = mapped_column(String(255))
    users: Mapped[str] = mapped_column(Text(), default="[]")  # 保存为 JSON 数组字符串格式的私聊用户 ID 列表
    groups: Mapped[str] = mapped_column(Text(), default="[]") # 保存为 JSON 数组字符串格式的群聊 ID 列表
    domains: Mapped[str] = mapped_column(Text(), default="[]") # 保存为 JSON 数组字符串格式的绑定域名白名单
    dmview: Mapped[bool] = mapped_column(default=True) # 是否允许非绑定域名的主机头或纯 IP 进行访问
    total_calls: Mapped[int] = mapped_column(Integer(), default=0)
    failed_calls: Mapped[int] = mapped_column(Integer(), default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class FieldMap(Base):
    __tablename__ = "webhook_field_maps"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    raw_field: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    mapped_field: Mapped[str] = mapped_column(String(255))

class AuditLog(Base):
    __tablename__ = "webhook_audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    route_code: Mapped[str] = mapped_column(String(255), index=True)
    payload: Mapped[str] = mapped_column(Text())
    status: Mapped[str] = mapped_column(String(50))
    message: Mapped[str] = mapped_column(Text(), nullable=True)
    called_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class SystemConfig(Base):
    __tablename__ = "webhook_system_config"
    
    key: Mapped[str] = mapped_column(String(255), primary_key=True)
    value: Mapped[str] = mapped_column(Text())

engine = create_async_engine(
    "sqlite+aiosqlite:///webhook.db",
    connect_args={"check_same_thread": False},
    echo=False
)
async_session = async_sessionmaker(engine, expire_on_commit=False)

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

