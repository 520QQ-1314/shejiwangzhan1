# -*- coding: utf-8 -*-
"""
花瓣网 Huaban 爬虫（国内直连，使用官方 AJAX API）
注意：花瓣的图片 CDN 有 referer 检查，前端显示时需加 referrerpolicy="no-referrer"
"""
from urllib.parse import quote
from typing import List, Dict
from scrapers.base import BaseScraper


class HuabanScraper(BaseScraper):
    name = "huaban"
    requires_proxy = False

    BASE = "https://huaban.com"
    CDN = "https://gd-hbimg.huaban.com"

    async def search(self, query: str, page: int = 1) -> List[Dict]:
        # 花瓣的搜索 API
        url = f"{self.BASE}/v3/search/file"
        params = {"text": query, "page": page, "per_page": 30, "sort": "all"}
        try:
            r = await self.client.get(
                url,
                params=params,
                headers={
                    "Accept": "application/json",
                    "X-Request": "JSON",
                    "Referer": f"{self.BASE}/search?q={quote(query)}",
                },
            )
            r.raise_for_status()
            data = r.json()
            # 花瓣返回结构可能是 {"pins": [...]} 或 {"data": {"pins": [...]}}
            pins = data.get("pins") or data.get("data", {}).get("pins") or []
            return [x for x in (self._parse(p) for p in pins) if x]
        except Exception as e:
            print(f"[huaban] {e}")
            # 降级：尝试老版 API
            return await self._fallback_search(query, page)

    async def _fallback_search(self, query, page):
        """老版 API 备用"""
        try:
            url = f"{self.BASE}/search/?q={quote(query)}&page={page}"
            r = await self.client.get(
                url,
                headers={
                    "Accept": "application/json",
                    "X-Request": "JSON",
                    "X-Requested-With": "XMLHttpRequest",
                },
            )
            r.raise_for_status()
            data = r.json()
            pins = data.get("pins") or []
            return [x for x in (self._parse(p) for p in pins) if x]
        except Exception as e:
            print(f"[huaban fallback] {e}")
            return []

    def _parse(self, p) -> Dict:
        if not isinstance(p, dict):
            return None
        file_info = p.get("file") or {}
        key = file_info.get("key") or p.get("file_id")
        if not key:
            return None

        ext = "jpg"
        ftype = file_info.get("type", "")
        if "png" in ftype:
            ext = "png"
        elif "gif" in ftype:
            ext = "gif"
        elif "webp" in ftype:
            ext = "webp"

        orig = f"{self.CDN}/{key}_fw1200"      # 约 1200 宽
        thumb = f"{self.CDN}/{key}_fw240"      # 240 宽缩略

        w = file_info.get("width", 0) or p.get("width", 0)
        h = file_info.get("height", 0) or p.get("height", 0)

        pin_id = p.get("pin_id") or p.get("id", "")
        link = f"{self.BASE}/pins/{pin_id}" if pin_id else ""

        return self.standardize({
            "id": str(pin_id),
            "title": (p.get("raw_text") or "")[:100],
            "description": p.get("text_meta", {}).get("tags_info", ""),
            "image_url": orig,
            "thumbnail": thumb,
            "width": w,
            "height": h,
            "source": "huaban",
            "link": link,
            "author": (p.get("user") or {}).get("username", ""),
        })
