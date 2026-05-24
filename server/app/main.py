from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api import chat
from app.api import products
from app.core.config import settings

app = FastAPI(title=settings.app_name, version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── 商品图片静态文件服务 ──────────────────────────────────────────────────────────
# data/ecommerce_agent_dataset 挂载到 /images
# 请求 /images/1_美妆护肤/images/p_beauty_001_live.jpg
#   → 实际读取 data/ecommerce_agent_dataset/1_美妆护肤/images/p_beauty_001_live.jpg
_DATASET_DIR = Path(__file__).resolve().parents[2] / "data" / "ecommerce_agent_dataset"
if _DATASET_DIR.exists():
    app.mount("/images", StaticFiles(directory=str(_DATASET_DIR)), name="images")


@app.get("/")
async def root():
    return {"message": "AI电商导购后端服务运行中"}


@app.get("/health")
async def health():
    return {"status": "ok"}


# ── 路由注册 ─────────────────────────────────────────────────────────────────────
app.include_router(chat.router,     prefix="/api", tags=["chat"])
app.include_router(products.router, prefix="/api", tags=["products"])
