# -*- coding: utf-8 -*-
"""DesignHub 主入口 v1.1"""
import asyncio
import os
import random
import re
import socket
import sys
import tempfile
import threading
import time
import webbrowser
import zipfile
from pathlib import Path
from typing import List, Optional

BACKEND_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BACKEND_DIR))


def resource_path(rel: str) -> Path:
    if hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / rel
    return BACKEND_DIR.parent / rel


import httpx
import uvicorn
from fastapi import FastAPI, Query, Body, HTTPException
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
from scrapers.dribbble import DribbbleScraper
from scrapers.zcool import ZcoolScraper
from scrapers.uicn import UICNScraper
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
    "pinterest": PinterestScraper(),
    "behance":   BehanceScraper(),
    "dribbble":  DribbbleScraper(),
    "unsplash":  UnsplashScraper(),
    "pexels":    PexelsScraper(),
    "pixabay":   PixabayScraper(),
    "zcool":     ZcoolScraper(),
    "uicn":      UICNScraper(),
}

SOURCE_REFERERS = {
    "pinterest": "https://www.pinterest.com/",
    "behance":   "https://www.behance.net/",
    "dribbble":  "https://dribbble.com/",
    "zcool":     "https://www.zcool.com.cn/",
    "uicn":      "https://www.ui.cn/",
    "unsplash":  "https://unsplash.com/",
    "pexels":    "https://www.pexels.com/",
    "pixabay":   "https://pixabay.com/",
}

FRONTEND_DIR = resource_path("frontend")
if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


# === 请求模型 ===
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


# === 工具函数 ===
def safe_filename(name: str, max_len: int = 50) -> str:
    """清理文件名非法字符（兼容 Windows / Linux / macOS）"""
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '', name or '')
    name = re.sub(r'\s+', ' ', name).strip().rstrip('.')
    return (name or "untitled")[:max_len]


def guess_ext(url: str) -> str:
    path = url.split('?')[0].split('#')[0].lower()
    for ext in ('jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp'):
        if path.endswith('.' + ext):
            return ext
    return 'jpg'


# === 路由 ===
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


@app.get("/api/search")
async def search(
    q: str = Query(..., min_length=1, max_length=100),
    sources: str = Query("all"),
    page: int = Query(1, ge=1, le=20),
    fresh: bool = Query(False),
):
    q = q.strip()
    if not fresh:
        cached = cache.get_search(q, sources, page, ttl=CONFIG.get("cache_ttl", 3600))
        if cached is not None:
            return {"results": cached, "cached": True, "count": len(cached)}

    if sources == "all":
        src_list = list(SCRAPERS.keys())
    else:
        src_list = [s for s in sources.split(",") if s.strip() in SCRAPERS]

    # 没配代理就剔除依赖代理的源
    if not (CONFIG.get("use_proxy") and CONFIG.get("worker_base")):
        src_list = [s for s in src_list if not SCRAPERS[s].requires_proxy]

    if not src_list:
        return {"results": [], "cached": False, "count": 0,
                "message": "无可用源。请在设置中配置 Cloudflare Worker 或 API Key"}

    sem = asyncio.Semaphore(CONFIG.get("max_concurrent", 6))

    async def fetch(name):
        async with sem:
            try:
                return await SCRAPERS[name].search(q, page)
            except Exception as e:
                print(f"[!] {name}: {e}")
                return []

    done = await asyncio.gather(*[fetch(n) for n in src_list], return_exceptions=True)
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


@app.post("/api/favorite")
async def add_favorite(req: FavoriteRequest):
    cache.add_favorite(req.image_id, req.data)
    return {"ok": True}


@app.delete("/api/favorite/{image_id:path}")
async def del_favorite(image_id: str):
    cache.remove_favorite(image_id)
    return {"ok": True}


@app.get("/api/favorites")
async def list_favorites():
    return {"items": cache.list_favorites()}


# === 🌟 新增：批量打包下载 ===
@app.get("/api/favorites/download")
async def download_favorites(ids: str = Query("", description="逗号分隔的 id，留空导出全部")):
    """
    打包收藏夹为 ZIP。
    - 异步并发下载，限流 5
    - 自动用对应源的 Referer，避免 Pinterest/Behance 403
    - ZIP 内附带 README.md 索引
    """
    all_favs = cache.list_favorites()
    if not all_favs:
        raise HTTPException(404, "收藏夹为空")

    if ids.strip():
        id_set = {x.strip() for x in ids.split(",") if x.strip()}
        favorites = [f for f in all_favs if str(f.get("id") or f.get("image_url")) in id_set]
    else:
        favorites = all_favs

    if not favorites:
        raise HTTPException(404, "未找到指定收藏")

    # 临时文件方式：稳定性 > 内存方式
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".zip", prefix="dh_")
    os.close(tmp_fd)

    sem = asyncio.Semaphore(5)

    async def fetch_one(idx: int, item: dict):
        async with sem:
            url = item.get("image_url")
            if not url:
                return None
            source = item.get("source", "unknown")
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
                "Referer": SOURCE_REFERERS.get(source, ""),
            }
            try:
                async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as cli:
                    r = await cli.get(url, headers=headers)
                if r.status_code == 200 and len(r.content) > 1024:
                    return (idx, item, r.content)
                print(f"[zip] {source} {r.status_code} {url[:80]}")
            except Exception as e:
                print(f"[zip] err {url[:80]}: {e}")
            return None

    print(f"[+] 开始打包 {len(favorites)} 张...")
    t0 = time.time()
    results = await asyncio.gather(
        *[fetch_one(i, it) for i, it in enumerate(favorites)],
        return_exceptions=True,
    )

    ok, fail = 0, 0
    index_lines = [
        f"# DesignHub 收藏夹 ({time.strftime('%Y-%m-%d %H:%M:%S')})\n",
        f"\n总计：{len(favorites)} 张\n\n---\n\n",
    ]
    with zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for r in results:
            if not r or isinstance(r, Exception):
                fail += 1
                continue
            idx, item, content = r
            ext = guess_ext(item.get("image_url", ""))
            source = item.get("source", "unknown")
            title = safe_filename(item.get("title") or "untitled")
            filename = f"{idx + 1:03d}_{source}_{title}.{ext}"
            try:
                zf.writestr(filename, content)
                ok += 1
                index_lines.append(
                    f"### {idx + 1}. {item.get('title') or '无标题'}\n"
                    f"- 来源：**{source}**\n"
                    f"- 作者：{item.get('author') or '未知'}\n"
                    f"- 原链接：{item.get('link') or '无'}\n"
                    f"- 文件：`{filename}`\n\n"
                )
            except Exception as e:
                fail += 1
                print(f"[zip] write {filename}: {e}")

        index_lines.append(f"\n---\n\n成功 {ok}，失败 {fail}\n")
        zf.writestr("README.md", "".join(index_lines))

    print(f"[+] 打包完成 {ok}/{len(favorites)} 张，耗时 {time.time() - t0:.1f}s")

    def cleanup():
        try:
            os.unlink(tmp_path)
        except Exception:
            pass

    return FileResponse(
        tmp_path,
        media_type="application/zip",
        filename=f"designhub_favorites_{int(time.time())}.zip",
        background=BackgroundTask(cleanup),
    )


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


@app.on_event("startup")
async def on_startup():
    print(f"[+] DesignHub v1.1 已启动")
    print(f"[+] 已注册源：{list(SCRAPERS.keys())}")
    print(f"[+] 配置文件：{Path.home() / '.designhub' / 'config.json'}")
    if CONFIG.get("use_proxy") and CONFIG.get("worker_base"):
        print(f"[+] 代理：{CONFIG['worker_base']}")
    else:
        print("[!] 未配置 Worker，Pinterest/Behance/Dribbble 暂不可用")
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
