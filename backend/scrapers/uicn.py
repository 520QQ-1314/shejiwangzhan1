# -*- coding: utf-8 -*-
"""
UI中国 (ui.cn) 爬虫（国内直连，无需代理）
"""
import re
from urllib.parse import quote
from typing import List, Dict
from scrapers.base import BaseScraper


class UicnScraper(BaseScraper):
    name = "uicn"
    requires_proxy = False

    async def search(self, query: str, page: int = 1) -> List[Dict]:
        url = f"https://www.ui.cn/search.html?keyword={quote(query)}&page={page}"
        try:
            r = await self.client.get(
                url,
                headers={
                    "Referer": "https://www.ui.cn/",
                    "Accept": "text/html,application/xhtml+xml",
                },
            )
            r.raise_for_status()
            r.encoding = "utf-8"
            return self._parse(r.text)
        except Exception as e:
            print(f"[uicn] {e}")
            return []

    def _parse(self, html: str) -> List[Dict]:
        results = []
        # UI中国 作品卡片通常是 <li> 或 <div> 包裹
        # 直接从所有包含 detail 链接的 a 标签入手
        pattern = re.compile(
            r'<a[^>]+href="(/detail/\d+\.html)"[^>]*>.*?'
            r'<img[^>]+(?:data-original|data-src|src)="([^"]+)"[^>]*(?:alt="([^"]*)")?',
            re.S,
        )
        seen_links = set()
        for m in pattern.finditer(html):
            link_path, img_url, alt = m.group(1), m.group(2), m.group(3) or ""
            if link_path in seen_links:
                continue
            seen_links.add(link_path)

            # 排除占位图
            if not img_url or "placeholder" in img_url.lower() or "loading" in img_url.lower():
                continue

            # 补全协议
            if img_url.startswith("//"):
                img_url = "https:" + img_url
            elif img_url.startswith("/"):
                img_url = "https://www.ui.cn" + img_url

            # 原图（UI中国的 CDN 通常支持去掉后缀参数）
            orig = re.sub(r'_(\d+)x(\d+)\.(jpg|png|webp)$', r'.\3', img_url)

            id_m = re.search(r'/detail/(\d+)', link_path)
            detail_id = id_m.group(1) if id_m else ""

            results.append(self.standardize({
                "id": detail_id,
                "title": alt.strip(),
                "image_url": orig,
                "thumbnail": img_url,
                "source": "uicn",
                "link": f"https://www.ui.cn{link_path}",
            }))

        return results[:30]
