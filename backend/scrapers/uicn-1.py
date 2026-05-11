# -*- coding: utf-8 -*-
"""UI 中国 爬虫：国内直连"""
import json
import re
from urllib.parse import quote
from typing import List, Dict
from scrapers.base import BaseScraper


class UICNScraper(BaseScraper):
    name = "uicn"
    requires_proxy = False
    BASE = "https://www.ui.cn"

    async def search(self, query: str, page: int = 1) -> List[Dict]:
        # UI 中国搜索路径有变化，多 URL 兜底
        urls = [
            f"{self.BASE}/search.html?type=works&searchWord={quote(query)}&page={page}",
            f"{self.BASE}/works/search?q={quote(query)}&page={page}",
        ]
        for url in urls:
            try:
                r = await self.client.get(
                    url,
                    headers={
                        "Referer": f"{self.BASE}/",
                        "Accept": "text/html",
                        "Accept-Language": "zh-CN,zh;q=0.9",
                    },
                )
                if r.status_code != 200:
                    continue
                html = r.text

                items = self._parse_embedded(html)
                if items:
                    return items
                items = self._parse_cards(html)
                if items:
                    return items
            except Exception as e:
                print(f"[ui.cn] {url}: {e}")
                continue
        return []

    def _parse_embedded(self, html: str) -> List[Dict]:
        m = re.search(r'window\.__INITIAL_STATE__\s*=\s*(\{.+?\})\s*;', html, re.S)
        if not m:
            return []
        try:
            data = json.loads(m.group(1).replace(":undefined", ":null"))
        except Exception:
            return []
        works = self._dig_works(data)
        if not works:
            return []
        return [x for x in (self._parse_work(w) for w in works) if x]

    def _dig_works(self, data):
        if isinstance(data, dict):
            for k in ("works", "list", "items", "results", "data"):
                v = data.get(k)
                if isinstance(v, list) and v and isinstance(v[0], dict):
                    if any(key in v[0] for key in ("cover", "image", "thumb", "title")):
                        return v
            for v in data.values():
                r = self._dig_works(v)
                if r:
                    return r
        elif isinstance(data, list):
            for x in data[:30]:
                r = self._dig_works(x)
                if r:
                    return r
        return None

    def _parse_work(self, w: dict):
        if not isinstance(w, dict):
            return None
        wid = str(w.get("id") or w.get("workId") or "")
        cover = w.get("cover") or w.get("thumb") or w.get("image") or ""
        if not cover:
            return None
        if cover.startswith("//"):
            cover = "https:" + cover
        title = w.get("title") or w.get("name") or ""
        author = ""
        u = w.get("user") or w.get("author") or {}
        if isinstance(u, dict):
            author = u.get("nickname") or u.get("name") or ""
        return self.standardize({
            "id": wid,
            "title": title,
            "image_url": cover,
            "thumbnail": cover,
            "source": "uicn",
            "link": w.get("url") or (f"{self.BASE}/detail/{wid}.html" if wid else ""),
            "author": author,
        })

    def _parse_cards(self, html: str) -> List[Dict]:
        results = []
        seen = set()
        # 通用：抓取所有外链作品图
        pattern = re.compile(
            r'<a[^>]+href="(/(?:detail|works/show|works)[^"]*)"[^>]*>'
            r'.*?<img[^>]+(?:data-original|data-src|src)="((?:https?:)?//[^"]+\.(?:jpg|jpeg|png|webp)[^"]*)"'
            r'[^>]*?(?:alt="([^"]*)")?',
            re.S | re.I,
        )
        for m in pattern.finditer(html):
            link_path, img, title = m.group(1), m.group(2), (m.group(3) or "").strip()
            if img.startswith("//"):
                img = "https:" + img
            if img in seen:
                continue
            seen.add(img)
            id_m = re.search(r"(\d+)", link_path)
            results.append(self.standardize({
                "id": id_m.group(1) if id_m else img.rsplit("/", 1)[-1].split(".")[0],
                "title": title,
                "image_url": img,
                "thumbnail": img,
                "source": "uicn",
                "link": f"{self.BASE}{link_path}",
            }))
        return results
