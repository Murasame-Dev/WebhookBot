import asyncio
import json
import uvicorn
from fastapi import FastAPI, Request, HTTPException, status, Response
from fastapi.responses import JSONResponse
from nonebot import logger
from sqlalchemy import select

from .storage import Route, AuditLog, SystemConfig, async_session
from .sender import broadcast_webhook_message

app = FastAPI(title="WebhookBot API")

async def is_secure_mode() -> bool:
    async with async_session() as session:
        conf = await session.scalar(select(SystemConfig).where(SystemConfig.key == "secure_mode"))
        return conf is not None and conf.value == "true"

@app.exception_handler(404)
async def handle_404(request: Request, exc):
    if await is_secure_mode():
        return Response(status_code=503)
    return JSONResponse(status_code=404, content={"detail": "Not Found"})

@app.exception_handler(405)
async def handle_405(request: Request, exc):
    if await is_secure_mode():
        return Response(status_code=503)
    return JSONResponse(status_code=405, content={"detail": "Method Not Allowed"})

@app.post("/webhook/{path}")
async def handle_webhook(path: str, request: Request):
    secure = await is_secure_mode()
    
    # 获取传入的 Webhook 路由信息对象并执行检查流水线
    async with async_session() as session:
        route: Route = await session.scalar(select(Route).where(Route.path == path))
        if not route:
            if secure:
                return Response(status_code=503)
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Webhook route not found"
            )

        # 1. 验证 JSON 请求体
        try:
            payload = await request.json()
        except json.JSONDecodeError:
            route.total_calls += 1
            route.failed_calls += 1
            audit = AuditLog(route_code=route.code, payload="[Invalid JSON]", status="400", message="Payload must be valid JSON")
            session.add(audit)
            await session.commit()
            if secure:
                return Response(status_code=502)
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Payload must be valid JSON")
        except Exception:
            route.total_calls += 1
            route.failed_calls += 1
            audit = AuditLog(route_code=route.code, payload="[Error reading payload]", status="400", message="Error retrieving payload as JSON")
            session.add(audit)
            await session.commit()
            if secure:
                return Response(status_code=502)
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Error retrieving payload as JSON")

        # 2. 内容检查：跨域主机名或允许任意主机名访问等逻辑
        if not getattr(route, "dmview", True):
            host = request.url.hostname
            domains = json.loads(route.domains) if getattr(route, "domains", None) else []
            if host not in domains:
                route.total_calls += 1
                route.failed_calls += 1
                audit = AuditLog(route_code=route.code, payload=json.dumps(payload, ensure_ascii=False), status="403", message=f"Domain blocked: {host}")
                session.add(audit)
                await session.commit()
                if secure:
                    return Response(status_code=502)
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access from this domain is blocked")

        # 3. 鉴权机制：检查请求传入的 token 是否与数据库一致
        verify_type = getattr(route, "verify_token", "join")
        if verify_type == "header":
            req_token = request.headers.get("Token")
        else:
            req_token = request.query_params.get("token")
            
        if req_token != route.token:
            route.total_calls += 1
            route.failed_calls += 1
            audit = AuditLog(route_code=route.code, payload=json.dumps(payload, ensure_ascii=False), status="403", message="Token mismatch")
            session.add(audit)
            await session.commit()
            if secure:
                return Response(status_code=502)
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid token")

    # 创建独立的后台异步任务分发群组与用户消息广播（阻止发送期间造成的耗时问题阻塞 API 快速完成）
    asyncio.create_task(broadcast_webhook_message(route.code, payload))

    return {"status": "accepted"}

async def start_webhook_server(host: str, port: int):
    # 手动配置并且引导独立挂载后台的 FastAPI APP 的 uvicorn 实例对象 
    config = uvicorn.Config(app=app, host=host, port=port, log_level="info")    
    server = uvicorn.Server(config)

    # 我们通过强制置空 install_signal_handlers 以确保 Uvicorn 不会抢占 Nonebot 自身绑定对 Ctrl+C 的信号量拦截
    logger.info(f"Starting standalone Webhook API on {host}:{port}")
    await server.serve()
