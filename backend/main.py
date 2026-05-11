# -*- coding: utf-8 -*-
"""DesignHub 主入口 v1.1"""
import asyncio
import os
import random
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path
from typing import List, Optional

BACKEND_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BACKEND_DIR))


def resource_path(rel: str) -> Path:
    if hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / rel
    return BACKEND_DIR.parent / rel


import uvicorn
from fastapi import FastAPI, Query, Body, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.background import BackgroundTask

from config import CONFIG, save_config
from scrapers.pinterest import PinterestScraper
from scrapers.behance import BehanceScraper
from scrapers.unsplash import UnsplashScraper
from scrapers.pexels import PexelsScraper
from scrapers.pixabay import PixabayScraper
# ===== v1.1 新增 =====
from scrapers.dribbble import DribbbleScraper
from scrapers.zcool import ZcoolScraper
from scrapers.uicn import UicnScraper
from scrapers.huaban import HuabanScraper
from utils.downloader import manager as dl_manager, run_zip_task
# =====================
from ai.tagger import AutoTagger
from ai.recommender import Recommender
from db.cache import Cache


app = FastAPI(title="DesignHub", version="1.1.0",
              docs_url="/api/docs", redoc_url=None)
app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_methods=["*"], allow_headers=["*"])

cache = Cache()
tagger = AutoTagger(use_clip=CONFIG.get("enable_clip", False))
recommender = Recommender(cache)

SCRAPERS = {
    # 国外源（需要代理）
    "pinterest": PinterestScraper(),
    "behance":   BehanceScraper(),
    "dribbble":  DribbbleScraper(),
    # 国外源（可直连）
    "unsplash":  UnsplashScraper(),
    "pexels":    PexelsScraper(),
    "pixabay":   PixabayScraper(),
    # 国内源（直连）
    "zcool":     ZcoolScraper(),
    "uicn":      UicnScraper(),
    "huaban":    HuabanScraper(),
}

FRONTEND_DIR = resource_path("frontend")
if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


# ============================================================
#   请求模型
# ============================================================
class TrackRequest(BaseModel):
    image_id: str
    action: str = "view"
    tags: List[str] = []


class FavoriteRequest(BaseModel):
    image_id: str
    data: dict = {}


class ConfigRequest(BaseModel):
    worker_base: Optional[str] = None
    use_proxy: Optional[bool] = None
    unsplash_key: Optional[str] = None
    pexels_key: Optional[str] = None
    pixabay_key: Optional[str] = None
    enable_clip: Optional[bool] = None


class DownloadStartRequest(BaseModel):
    # 空：下载全部收藏；指定 ids：只下载选中项
    ids: Optional[List[str]] = None


# ============================================================
#   页面与健康
# ============================================================
@app.get("/")
async def home():
    idx = FRONTEND_DIR / "index.html"
    if idx.exists():
        return FileResponse(str(idx))
    return JSONResponse({"error": "frontend not found"}, status_code=404)


@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "version": "1.1.0",
        "sources": list(SCRAPERS.keys()),
        "use_proxy": CONFIG.get("use_proxy"),
        "has_worker": bool(CONFIG.get("worker_base")),
        "clip_ready": tagger.clip_ready,
    }


# ============================================================
#   搜索
# ============================================================
@app.get("/api/search")
async def search(
    q: str = Query(..., min_length=1, max_length=100),
    sources: str = Query("all"),
    page: int = Query(1, ge=1, le=20),
    fresh: bool = Query(False),
):
    q = q.strip()
    if not fresh:
        cached = cache.get_search(q, sources, page,
                                  ttl=CONFIG.get("cache_ttl", 3600))
        if cached is not None:
            return {"results": cached, "cached": True, "count": len(cached)}

    if sources == "all":
        src_list = list(SCRAPERS.keys())
    else:
        src_list = [s for s in sources.split(",") if s.strip() in SCRAPERS]

    # 无 Worker 时，过滤掉需要代理的源
    if not (CONFIG.get("use_proxy") and CONFIG.get("worker_base")):
        src_list = [s for s in src_list if not SCRAPERS[s].requires_proxy]

    if not src_list:
        return {"results": [], "cached": False, "count": 0,
                "message": "无可用源。请在设置中配置 Worker 代理或 API Key"}

    sem = asyncio.Semaphore(CONFIG.get("max_concurrent", 6))

    async def fetch(name):
        async with sem:
            try:
                return await SCRAPERS[name].search(q, page)
            except Exception as e:
                print(f"[!] {name}: {e}")
                return []

    done = await asyncio.gather(*[fetch(n) for n in src_list],
                                return_exceptions=True)
    results = []
    for d in done:
        if isinstance(d, list):
            results.extend(d)

    seen, unique = set(), []
    for r in results:
        url = r.get("image_url")
        if url and url not in seen:
            seen.add(url)
            unique.append(r)
    random.shuffle(unique)

    # 自动打标签（前 30 项）
    if unique:
        try:
            tagged = await asyncio.gather(
                *[tagger.tag(it) for it in unique[:30]],
                return_exceptions=True,
            )
            for it, tags in zip(unique[:30], tagged):
                if isinstance(tags, list):
                    it["tags"] = tags
        except Exception as e:
            print(f"[!] auto-tag: {e}")

    cache.set_search(q, sources, page, unique)
    return {"results": unique, "cached": False, "count": len(unique)}


# ============================================================
#   行为追踪 & 推荐
# ============================================================
@app.post("/api/track")
async def track(req: TrackRequest):
    await recommender.record(req.image_id, req.action, req.tags)
    return {"ok": True}


@app.get("/api/recommend")
async def recommend(limit: int = Query(30, ge=10, le=100)):
    return await recommender.recommend(SCRAPERS, limit=limit)


@app.post("/api/auto_tag")
async def auto_tag(image_url: str = Body(..., embed=True)):
    tags = await tagger.tag_image(image_url) if tagger.clip_ready else []
    return {"tags": tags, "clip_used": tagger.clip_ready}


# ============================================================
#   收藏夹
# ============================================================
@app.post("/api/favorite")
async def add_favorite(req: FavoriteRequest):
    cache.add_favorite(req.image_id, req.data)
    return {"ok": True}


@app.delete("/api/favorite/{image_id}")
async def del_favorite(image_id: str):
    cache.remove_favorite(image_id)
    return {"ok": True}


@app.get("/api/favorites")
async def list_favorites():
    return {"items": cache.list_favorites()}


# ============================================================
#   v1.1 新增：批量下载 ZIP
# ============================================================
@app.post("/api/download/start")
async def download_start(req: DownloadStartRequest, bg: BackgroundTasks):
    """启动打包任务，立即返回 task_id"""
    favorites = cache.list_favorites(limit=500)
    if req.ids:
        id_set = set(req.ids)
        favorites = [
            it for it in favorites
            if str(it.get("id", it.get("image_url", ""))) in id_set
        ]
    if not favorites:
        raise HTTPException(400, "收藏夹为空或未匹配到项目")

    task = dl_manager.create(total=len(favorites))
    # 后台运行打包
    bg.add_task(run_zip_task, task, favorites)
    return {
        "task_id": task.id,
        "total": task.total,
        "message": "已启动打包任务，请轮询 /api/download/status/{task_id}",
    }


@app.get("/api/download/status/{task_id}")
async def download_status(task_id: str):
    task = dl_manager.get(task_id)
    if not task:
        raise HTTPException(404, "任务不存在或已过期")
    return task.to_dict()


@app.get("/api/download/file/{task_id}")
async def download_file(task_id: str):
    task = dl_manager.get(task_id)
    if not task:
        raise HTTPException(404, "任务不存在")
    if task.status != "done":
        raise HTTPException(400, f"任务状态：{task.status}，尚未就绪")
    if not task.file_path or not os.path.exists(task.file_path):
        raise HTTPException(500, "ZIP 文件已被清理")

    filename = f"designhub_favorites_{int(time.time())}.zip"

    # 下载完成后清理临时文件
    def _cleanup():
        try:
            if task.file_path and os.path.exists(task.file_path):
                os.unlink(task.file_path)
        except Exception:
            pass

    return FileResponse(
        task.file_path,
        media_type="application/zip",
        filename=filename,
        background=BackgroundTask(_cleanup),
    )


# ============================================================
#   配置
# ============================================================
@app.get("/api/config")
async def get_config():
    return {
        "use_proxy":        CONFIG.get("use_proxy"),
        "worker_base":      CONFIG.get("worker_base"),
        "has_unsplash_key": bool(CONFIG.get("unsplash_key")),
        "has_pexels_key":   bool(CONFIG.get("pexels_key")),
        "has_pixabay_key":  bool(CONFIG.get("pixabay_key")),
        "enable_clip":      CONFIG.get("enable_clip"),
    }


@app.post("/api/config")
async def update_config(req: ConfigRequest):
    for k, v in req.model_dump(exclude_unset=True).items():
        if v is not None:
            CONFIG[k] = v
    save_config(CONFIG)
    return {"ok": True}


# ============================================================
#   生命周期
# ============================================================
@app.on_event("startup")
async def on_startup():
    print("=" * 50)
    print("  🎨 DesignHub v1.1 已启动")
    print(f"  📁 配置文件：{Path.home() / '.designhub' / 'config.json'}")
    print(f"  🔌 已加载 {len(SCRAPERS)} 个源: {', '.join(SCRAPERS.keys())}")
    if CONFIG.get("use_proxy") and CONFIG.get("worker_base"):
        print(f"  🌐 代理：{CONFIG['worker_base']}")
    else:
        print("  ⚠️  未配置 Worker，Pinterest/Behance/Dribbble 暂不可用")
    print("=" * 50)
    cache.cleanup()


@app.on_event("shutdown")
async def on_shutdown():
    for sc in SCRAPERS.values():
        await sc.close()


def find_free_port(start=5000, end=5020):
    for p in range(start, end):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", p))
                return p
            except OSError:
                continue
    return start


def open_browser_delayed(port):
    def _open():
        time.sleep(1.8)
        try:
            webbrowser.open(f"http://127.0.0.1:{port}")
        except Exception:
            pass
    threading.Thread(target=_open, daemon=True).start()


def main():
    port = find_free_port()
    open_browser_delayed(port)
    uvicorn.run(app, host="127.0.0.1", port=port,
                log_level="info", access_log=False)


if __name__ == "__main__":
    main()
