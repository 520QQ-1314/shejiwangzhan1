# -*- coding: utf-8 -*-
"""
Dribbble 爬虫（需要 Worker 代理）
结构相对稳定，但 Cloudflare 防护较强，必须带完整浏览器 headers
"""
import re
from urllib.parse import quote
from typing import List, Dict
from scrapers.base import BaseScraper


class DribbbleScraper(BaseScraper):
    name = "dribbble"
    requires_proxy = True

    async def search(self, query: str, page: int = 1) -> List[Dict]:
        url = f"https://dribbble.com/search/shots?q={quote(query)}&page={page}"
        try:
            r = await self.client.get(
                self.proxied(url),
                headers={
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9",
                    "Accept-Language": "en-US,en;q=0.9",
                    "Sec-Fetch-Dest": "document",
                    "Sec-Fetch-Mode": "navigate",
                },
            )
            r.raise_for_status()
            html = r.text

            # 方式 1：解析 li.shot-thumbnail 结构（稳定）
            items = self._parse_li_blocks(html)
            if items:
                return items

            # 方式 2：退而求其次，从 figure 元素提取
            return self._parse_figure_blocks(html)
        except Exception as e:
            print(f"[dribbble] {e}")
            return []

    # ---------- 解析方式 1：li.shot-thumbnail ----------
    def _parse_li_blocks(self, html: str) -> List[Dict]:
        # 先分块：每个 shot 一个 <li>
        blocks = re.findall(
            r'<li[^>]*class="[^"]*shot-thumbnail[^"]*"[^>]*data-thumbnail-id="(\d+)"[^>]*>(.*?)</li>',
            html, re.S,
        )
        return self._blocks_to_items(blocks)

    # ---------- 解析方式 2：figure 块 ----------
    def _parse_figure_blocks(self, html: str) -> List[Dict]:
        # 宽松匹配
        blocks = re.findall(
            r'<figure[^>]*shot-thumbnail-placeholder[^>]*>(.*?)</figure>',
            html, re.S,
        )
        pseudo = [(str(i), b) for i, b in enumerate(blocks)]
        return self._blocks_to_items(pseudo)

    def _blocks_to_items(self, blocks) -> List[Dict]:
        results = []
        for shot_id, block in blocks:
            # 链接
            link_m = re.search(r'href="(/shots/[^"]+)"', block)
            link = f"https://dribbble.com{link_m.group(1)}" if link_m else ""

            # 图片：优先 srcset（高清），降级 src，再降级 data-src
            image_url = ""
            srcset_m = re.search(r'srcset="([^"]+)"', block)
            if srcset_m:
                # srcset 示例: "url1 1x, url2 2x" 或 "url 400w, url 800w"
                urls = re.findall(r'(https?://[^\s,]+)', srcset_m.group(1))
                if urls:
                    image_url = urls[-1]  # 最后通常是最高清的

            if not image_url:
                src_m = re.search(r'<img[^>]+\bsrc="(https?://[^"]+)"', block)
                if src_m:
                    image_url = src_m.group(1)

            if not image_url:
                ds_m = re.search(r'data-src="(https?://[^"]+)"', block)
                if ds_m:
                    image_url = ds_m.group(1)

            if not image_url or "placeholder" in image_url.lower():
                continue

            # 标题
            alt_m = re.search(r'<img[^>]+alt="([^"]*)"', block)
            title = alt_m.group(1) if alt_m else ""

            # 缩略图：取 srcset 中最小的那个
            thumb = image_url
            if srcset_m:
                all_urls = re.findall(r'(https?://[^\s,]+)', srcset_m.group(1))
                if all_urls:
                    thumb = all_urls[0]

            results.append(self.standardize({
                "id": shot_id,
                "title": title,
                "image_url": image_url,
                "thumbnail": thumb,
                "source": "dribbble",
                "link": link,
            }))
        return results
