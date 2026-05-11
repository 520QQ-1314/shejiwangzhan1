# -*- coding: utf-8 -*-
"""
站酷 ZCool 爬虫（国内直连，无需代理）
解析搜索结果页 HTML
"""
import re
from urllib.parse import quote
from typing import List, Dict
from scrapers.base import BaseScraper


class ZcoolScraper(BaseScraper):
    name = "zcool"
    requires_proxy = False

    async def search(self, query: str, page: int = 1) -> List[Dict]:
        url = (
            "https://www.zcool.com.cn/search/content"
            f"?word={quote(query)}&type=0&recommendLevel=1&requestPage={page}"
        )
        try:
            r = await self.client.get(
                url,
                headers={
                    "Referer": "https://www.zcool.com.cn/",
                    "Accept": "text/html,application/xhtml+xml",
                },
            )
            r.raise_for_status()
            r.encoding = "utf-8"
            return self._parse(r.text)
        except Exception as e:
            print(f"[zcool] {e}")
            return []

    def _parse(self, html: str) -> List[Dict]:
        results = []
        # 站酷每个作品卡片：<div class="card-box">...</div>
        blocks = re.findall(
            r'<div[^>]*class="[^"]*card-box[^"]*"[^>]*>(.*?)</div>\s*</div>\s*</div>',
            html, re.S,
        )

        for block in blocks:
            # 作品链接
            link_m = re.search(r'href="(https?://www\.zcool\.com\.cn/work/[^"]+)"', block)
            if not link_m:
                # 有时候链接省略协议
                link_m = re.search(r'href="(//www\.zcool\.com\.cn/work/[^"]+)"', block)
            if not link_m:
                continue
            link = link_m.group(1)
            if link.startswith("//"):
                link = "https:" + link

            # 图片（data-src 或 src，原图在 img.zcool.cn/community/）
            img_m = re.search(
                r'<img[^>]+(?:data-src|src)="(https?://img\.zcool\.cn/community/[^"]+)"',
                block,
            )
            if not img_m:
                continue
            raw = img_m.group(1)

            # 高清原图：去掉 @xxx 后缀
            orig = re.sub(r'@[^.]*(\.(jpg|jpeg|png|webp|gif))', r'\1', raw, flags=re.I)
            # 缩略图：加 @260w 后缀（如果已有 @ 则保留原始值）
            thumb = raw if "@" in raw else raw.replace(".jpg", "@260w.jpg")

            # 标题
            title_m = re.search(r'<img[^>]+alt="([^"]*)"', block)
            title = (title_m.group(1) if title_m else "").strip()
            if not title:
                # 从另一处找
                t2 = re.search(r'class="[^"]*title-content[^"]*"[^>]*>([^<]+)', block)
                title = t2.group(1).strip() if t2 else ""

            # 作者
            author_m = re.search(
                r'class="[^"]*user-name[^"]*"[^>]*>\s*([^<]+?)\s*</',
                block,
            )
            author = author_m.group(1).strip() if author_m else ""

            # ID 从链接提取
            id_m = re.search(r'/work/([^.]+)\.html', link)
            work_id = id_m.group(1) if id_m else ""

            results.append(self.standardize({
                "id": work_id,
                "title": title,
                "image_url": orig,
                "thumbnail": thumb,
                "source": "zcool",
                "link": link,
                "author": author,
            }))

        return results[:30]
