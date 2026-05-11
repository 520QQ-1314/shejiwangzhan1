# -*- coding: utf-8 -*-
"""站酷 ZCool 爬虫：国内直连，无需代理"""
import json
import re
from urllib.parse import quote
from typing import List, Dict
from scrapers.base import BaseScraper


class ZcoolScraper(BaseScraper):
    name = "zcool"
    requires_proxy = False
    BASE = "https://www.zcool.com.cn"

    async def search(self, query: str, page: int = 1) -> List[Dict]:
        url = f"{self.BASE}/search/content?word={quote(query)}&p={page}"
        try:
            r = await self.client.get(
                url,
                headers={
                    "Referer": f"{self.BASE}/",
                    "Accept": "text/html,application/xhtml+xml",
                    "Accept-Language": "zh-CN,zh;q=0.9",
                },
            )
            r.raise_for_status()
            html = r.text
        except Exception as e:
            print(f"[zcool] {e}")
            return []

        # 策略1：解析嵌入式 JSON
        items = self._parse_embedded(html)
        if items:
            return items

        # 策略2：作品卡片正则
        return self._parse_cards(html)

    def _parse_embedded(self, html: str) -> List[Dict]:
        patterns = [
            r'window\.__INITIAL_STATE__\s*=\s*(\{.+?\})\s*;</script>',
            r'window\.pageData\s*=\s*(\{.+?\})\s*;',
        ]
        for pat in patterns:
            m = re.search(pat, html, re.S)
            if not m:
                continue
            try:
                # 站酷的 JSON 经常有 undefined，先简单替换
                raw = m.group(1).replace(":undefined", ":null")
                data = json.loads(raw)
                works = self._dig_works(data)
                if works:
                    return [x for x in (self._parse_work(w) for w in works) if x]
            except Exception:
                continue
        return []

    def _dig_works(self, data):
        if isinstance(data, dict):
            for k in ("workList", "contentList", "list", "items", "data"):
                v = data.get(k)
                if isinstance(v, list) and v:
                    # 验证是不是作品列表
                    if isinstance(v[0], dict) and (
                        "objectId" in v[0] or "workId" in v[0] or
                        "cover" in v[0] or "title" in v[0]
                    ):
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
        wid = str(w.get("objectId") or w.get("workId") or w.get("id") or "")
        title = w.get("title") or w.get("workTitle") or ""
        cover = (w.get("cover") or w.get("coverUrl") or
                 w.get("image") or w.get("imageUrl") or "")
        if not cover:
            return None
        # 站酷 OSS 图片：去 ?x-oss-process= 参数即原图
        big = cover.split("?")[0]
        author = ""
        creator = w.get("creator") or w.get("user") or {}
        if isinstance(creator, dict):
            author = creator.get("username") or creator.get("name") or ""
        link = w.get("pageUrl") or w.get("url") or (
            f"{self.BASE}/work/{wid}.html" if wid else ""
        )
        return self.standardize({
            "id": wid,
            "title": title,
            "image_url": big,
            "thumbnail": cover,
            "source": "zcool",
            "link": link,
            "author": author,
        })

    def _parse_cards(self, html: str) -> List[Dict]:
        results = []
        seen = set()
        # 模式：<a href="https://www.zcool.com.cn/work/xxx.html">
        #        <img data-original="https://img.zcool.cn/community/xxx" />
        pattern = re.compile(
            r'<a[^>]+href="(https?://www\.zcool\.com\.cn/work/[^"]+\.html)"[^>]*>'
            r'.*?<img[^>]+(?:data-original|src)="(https?://img\.zcool\.cn/community/[^"]+)"'
            r'[^>]*?(?:alt="([^"]*)")?',
            re.S | re.I,
        )
        for m in pattern.finditer(html):
            link, img, title = m.group(1), m.group(2), (m.group(3) or "").strip()
            if img in seen:
                continue
            seen.add(img)
            big = img.split("?")[0]
            id_m = re.search(r"/work/([A-Za-z0-9]+)\.html", link)
            results.append(self.standardize({
                "id": id_m.group(1) if id_m else img.rsplit("/", 1)[-1].split(".")[0],
                "title": title,
                "image_url": big,
                "thumbnail": img,
                "source": "zcool",
                "link": link,
            }))
        return results
