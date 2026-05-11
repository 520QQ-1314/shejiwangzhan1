# -*- coding: utf-8 -*-
"""
批量下载收藏夹 → ZIP
特性：
  - 异步并发（Semaphore 控制）
  - 失败自动跳过不阻塞
  - 按源分文件夹
  - 自动推断扩展名
  - 带进度反馈（内存态任务表）
  - 临时文件存储，完成后 FileResponse + 后台清理
"""
import asyncio
import io
import json
import os
import re
import tempfile
import time
import uuid
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import httpx


# ============================================================
#  任务管理（内存态，进程重启丢失）
# ============================================================
class DownloadTask:
    def __init__(self, total: int):
        self.id: str = uuid.uuid4().hex[:12]
        self.status: str = "pending"   # pending | running | done | error
        self.total: int = total
        self.done: int = 0
        self.failed: int = 0
        self.file_path: Optional[str] = None
        self.error: str = ""
        self.created_at: float = time.time()

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "status": self.status,
            "total": self.total,
            "done": self.done,
            "failed": self.failed,
            "progress": round(self.done / self.total * 100, 1) if self.total else 0,
            "error": self.error,
            "ready": self.status == "done",
        }


class DownloadManager:
    """简单的内存任务表，支持并发多个打包任务"""
    def __init__(self):
        self._tasks: Dict[str, DownloadTask] = {}

    def create(self, total: int) -> DownloadTask:
        t = DownloadTask(total)
        self._tasks[t.id] = t
        # 清理过期任务（> 1 小时）
        self._cleanup()
        return t

    def get(self, task_id: str) -> Optional[DownloadTask]:
        return self._tasks.get(task_id)

    def _cleanup(self):
        now = time.time()
        expired = [k for k, v in self._tasks.items() if now - v.created_at > 3600]
        for k in expired:
            v = self._tasks.pop(k, None)
            if v and v.file_path and os.path.exists(v.file_path):
                try:
                    os.unlink(v.file_path)
                except Exception:
                    pass


# 全局单例
manager = DownloadManager()


# ============================================================
#  下载工具函数
# ============================================================
def _safe_filename(s: str, max_len: int = 40) -> str:
    """清洗文件名：去非法字符、限长"""
    s = re.sub(r"[<>:\"/\\|?*\n\r\t]", "", s or "")
    s = re.sub(r"\s+", "_", s.strip())
    return s[:max_len]


def _guess_ext(url: str, content: bytes) -> str:
    """从 URL 或 magic bytes 猜扩展名"""
    # 先看 URL
    url_lower = url.lower().split("?")[0]
    for ext in (".jpg", ".jpeg", ".png", ".webp", ".gif", ".svg", ".bmp"):
        if url_lower.endswith(ext):
            return ".jpg" if ext == ".jpeg" else ext

    # 看 magic bytes
    if not content or len(content) < 8:
        return ".jpg"
    if content[:3] == b"\xff\xd8\xff":
        return ".jpg"
    if content[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if content[:6] in (b"GIF87a", b"GIF89a"):
        return ".gif"
    if content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return ".webp"
    if content[:2] == b"BM":
        return ".bmp"
    return ".jpg"


async def _fetch_image(client: httpx.AsyncClient, url: str) -> bytes:
    """单图下载，带合理的 headers"""
    # 按域名定制 Referer（部分 CDN 做了防盗链）
    referer_map = {
        "pinimg.com":          "https://www.pinterest.com/",
        "behance.net":         "https://www.behance.net/",
        "unsplash.com":        "https://unsplash.com/",
        "pexels.com":          "https://www.pexels.com/",
        "pixabay.com":         "https://pixabay.com/",
        "dribbble.com":        "https://dribbble.com/",
        "zcool.cn":            "https://www.zcool.com.cn/",
        "ui.cn":               "https://www.ui.cn/",
        "huaban.com":          "https://huaban.com/",
    }
    referer = ""
    for dom, ref in referer_map.items():
        if dom in url:
            referer = ref
            break

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
    }
    if referer:
        headers["Referer"] = referer

    r = await client.get(url, headers=headers, timeout=30, follow_redirects=True)
    r.raise_for_status()
    return r.content


# ============================================================
#  核心：打包任务
# ============================================================
async def run_zip_task(task: DownloadTask, favorites: List[dict],
                       max_concurrency: int = 5) -> None:
    """
    后台运行打包任务。更新 task 状态。
    """
    task.status = "running"

    # 临时文件
    tmp = tempfile.NamedTemporaryFile(
        prefix="designhub_", suffix=".zip", delete=False,
    )
    tmp_path = tmp.name
    tmp.close()

    sem = asyncio.Semaphore(max_concurrency)
    failed_items: List[dict] = []

    async def download_one(idx: int, item: dict, client: httpx.AsyncClient):
        async with sem:
            url = item.get("image_url")
            if not url:
                task.failed += 1
                return None
            try:
                content = await _fetch_image(client, url)
                return idx, item, content
            except Exception as e:
                task.failed += 1
                failed_items.append({
                    "index": idx,
                    "url": url,
                    "error": str(e)[:100],
                })
                return None
            finally:
                task.done += 1

    try:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            tasks = [download_one(i, it, client) for i, it in enumerate(favorites)]
            results = await asyncio.gather(*tasks, return_exceptions=True)

        # 写入 ZIP（STORED 模式：图片本身已压缩，无需再压缩）
        success_count = 0
        with zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_STORED) as zf:
            for r in results:
                if not r or isinstance(r, Exception):
                    continue
                idx, item, content = r
                source = item.get("source", "unknown")
                title = _safe_filename(item.get("title", ""))
                ext = _guess_ext(item.get("image_url", ""), content)
                name_parts = [f"{idx+1:04d}"]
                if title:
                    name_parts.append(title)
                fname = f"{source}/{'_'.join(name_parts)}{ext}"
                zf.writestr(fname, content)
                success_count += 1

            # 附带元数据
            manifest = {
                "exported_at": datetime.now().isoformat(timespec="seconds"),
                "total": len(favorites),
                "success": success_count,
                "failed": len(failed_items),
                "failed_items": failed_items,
                "sources": sorted(set(
                    it.get("source", "unknown") for it in favorites
                )),
            }
            zf.writestr(
                "manifest.json",
                json.dumps(manifest, ensure_ascii=False, indent=2),
            )

            # 可浏览的 HTML 索引
            zf.writestr("index.html", _build_index_html(favorites))

        task.file_path = tmp_path
        task.status = "done"
    except Exception as e:
        task.status = "error"
        task.error = str(e)[:200]
        if os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except Exception:
                pass


def _build_index_html(favorites: List[dict]) -> str:
    """生成一个可离线浏览的简易索引页"""
    rows = []
    for i, it in enumerate(favorites):
        title = (it.get("title") or "").replace("<", "&lt;")[:80]
        source = it.get("source", "unknown")
        link = it.get("link") or ""
        rows.append(
            f'<tr><td>{i+1}</td><td>{source}</td><td>{title}</td>'
            f'<td><a href="{link}" target="_blank">原站</a></td></tr>'
        )
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>DesignHub 收藏夹 · 索引</title>
<style>
body{{font-family:sans-serif;max-width:900px;margin:40px auto;padding:20px}}
h1{{color:#e60023}}
table{{width:100%;border-collapse:collapse}}
th,td{{padding:8px 12px;border-bottom:1px solid #eee;text-align:left}}
tr:hover{{background:#fafafa}}
a{{color:#e60023}}
</style></head><body>
<h1>🎨 DesignHub 收藏夹</h1>
<p>共 {len(favorites)} 张图 · 导出于 {datetime.now().strftime("%Y-%m-%d %H:%M")}</p>
<table><thead><tr><th>#</th><th>来源</th><th>标题</th><th>链接</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table>
</body></html>"""
