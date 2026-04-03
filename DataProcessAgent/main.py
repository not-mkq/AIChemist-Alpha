"""main.py - DataProcess Backend Entry Point"""
import asyncio
import logging
import os
import uvicorn
from typing import List
from contextlib import asynccontextmanager
from fastapi import FastAPI, UploadFile, File, Form
from fastapi.responses import JSONResponse
from upload import upload_data
from routers.label_router import router as label_router
from routers.profile_router import router as profile_router
from routers.project_router import router as project_router
from routers.tool_router import router as tool_router
from routers.runtime_router import router as runtime_router
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)
class NoSignalServer(uvicorn.Server):
    def install_signal_handlers(self) -> None: pass
def setup_app(app: FastAPI):
    app.include_router(label_router)
    app.include_router(profile_router)
    app.include_router(project_router)
    app.include_router(tool_router)
    app.include_router(runtime_router)
    @app.post("/upload")
    async def upload_endpoint(project: str=Form(...), upload_type: str=Form(...), batch_prefix: str=Form("Batch"), item_prefix: str=Form("Item"), files: List[UploadFile]=File(...)):
        result = await upload_data(project=project, upload_type=upload_type, batch_prefix=batch_prefix, item_prefix=item_prefix, files=files)
        return result if isinstance(result, JSONResponse) else JSONResponse(result)
    @app.get("/ping")
    def ping(): return {"status": "ok", "transport": "dual"}
@asynccontextmanager
async def lifespan(app: FastAPI):
    uds_path = "/tmp/dataprocess.sock"
    
    # 清理旧的 Socket 文件
    if os.path.exists(uds_path):
        try:
            os.remove(uds_path)
        except Exception as e:
            logger.warning(f"无法清理旧的 UDS Socket: {e}")

    # 创建独立的 UDS App 实例 (不设置 lifespan 避免递归)
    uds_app = FastAPI(title="DataProcess UDS")
    setup_app(uds_app)
    
    config = uvicorn.Config(uds_app, uds=uds_path, log_level="warning")
    server = NoSignalServer(config)
    
    logger.info(f"启动 UDS 监听: {uds_path}")
    uds_task = asyncio.create_task(server.serve())
    
    yield
    
    # 停止 UDS 服务
    server.should_exit = True
    await uds_task
    
    # 最后清理
    if os.path.exists(uds_path):
        try:
            os.remove(uds_path)
        except:
            pass

app = FastAPI(title="DataProcess Backend", lifespan=lifespan)
setup_app(app)

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="DataProcess Backend")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址")
    parser.add_argument("--port", type=int, default=8000, help="监听端口")
    args = parser.parse_args()
    
    uvicorn.run(app, host=args.host, port=args.port)
