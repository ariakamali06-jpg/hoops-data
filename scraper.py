#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Hoops Data Scraper
==================
اسکرپر خبری اپلیکیشن بسکتبال Hoops.

این اسکرپر فقط از منابع RSS/فید رسمی و قانونی استفاده می‌کند، داده را
تمیز و یکدست می‌کند و در قالب یک فایل JSON استاندارد می‌نویسد.
اپلیکیشن اندروید فقط همین JSON را می‌خواند و هرگز مستقیم سایت‌ها را
اسکرپ نمی‌کند.

خروجی:  data/news.json

روش اجرا:
    python scraper.py
"""

from __future__ import annotations

import json
import hashlib
import os
import re
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.error import URLError, HTTPError
from urllib.parse import unquote
from urllib.request import Request, urlopen

# ---------------------------------------------------------------------------
# تنظیمات
# ---------------------------------------------------------------------------

OUT_DIR = Path(__file__).parent / "data"
USER_AGENT = (
    "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Mobile Safari/537.36"
)

# اگر اتصال مستقیم جواب نداد، از تونل محلی استفاده می‌شود.
# خالی بگذارید تا فقط اتصال مستقیم استفاده شود:  HOOPS_PROXY=
DEFAULT_PROXY = "http://127.0.0.1:20811"

# کلیدواژه‌های فارسی/انگلیسی برای پیدا کردن خبر بسکتبال در فیدهای عمومی
BASKETBALL_KEYWORDS = (
    "بسکتبال", "ان‌بی‌ای", "ان بی ای", "یورولیگ", "لیگ برتر بسکتبال",
    "مربی تیم ملی بسکتبال", "بازیکن بسکتبال", "فدراسیون بسکتبال",
    "nba", "euroleague", "euro cup", "basketball",
)

SOURCES = [
    {
        "id": "isna",
        "name": "ایسنا",
        "nameEn": "ISNA",
        "language": "fa",
        "category": "خبرگزاری",
        "url": "https://www.isna.ir/rss",
        "type": "rss",
        "filter": True,          # فید عمومی است → باید فیلتر بسکتبال بزنیم
        "needsProxy": False,
    },
    {
        "id": "varzesh3",
        "name": "ورزش سه",
        "nameEn": "Varzesh3",
        "language": "fa",
        "category": "ورزشی",
        "type": "search_api",
        # جست‌وجوی تخصصی بسکتبال؛ هر کوئری ۲۴ خبر می‌دهد و صفحه‌بندی دارد
        "endpoint": "https://search-api.varzesh3.com/v1.0/news",
        "queries": [
            "بسکتبال",
            "لیگ برتر بسکتبال ایران",
            "تیم ملی بسکتبال",
            "NBA بسکتبال",
            "یورولیگ بسکتبال",
        ],
        "filter": False,         # خود API بر اساس کوئری فیلتر می‌کند
        "needsProxy": False,
    },
    {
        "id": "bbc",
        "name": "بی‌بی‌سی ورزشی",
        "nameEn": "BBC Sport",
        "language": "en",
        "category": "Basketball",
        "url": "https://feeds.bbci.co.uk/sport/basketball/rss.xml",
        "type": "rss",
        "filter": False,         # فید تخصصی بسکتبال است
        "needsProxy": True,
    },
]

# ---------------------------------------------------------------------------
# شبکه
# ---------------------------------------------------------------------------


def _proxy_url() -> str | None:
    value = os.environ.get("HOOPS_PROXY", DEFAULT_PROXY).strip()
    return value or None


def _open(req: Request, proxy: str | None, timeout: int = 25) -> bytes:
    if proxy:
        import urllib.request

        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": proxy, "https": proxy})
        )
        with opener.open(req, timeout=timeout) as resp:
            return resp.read()

    with urlopen(req, timeout=timeout) as resp:  # noqa: S310 - منابع HTTPS ثابت
        return resp.read()


def fetch(url: str, prefer_proxy: bool = False) -> bytes:
    """دریافت محتوا؛ اول مسیر پیش‌فرض، بعد مسیر جایگزین در صورت شکست."""
    req = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    proxy = _proxy_url()
    attempts = []
    if prefer_proxy and proxy:
        attempts = [proxy, None]
    else:
        attempts = [None, proxy]

    last_error: Exception | None = None
    for attempt in attempts:
        try:
            return _open(req, attempt)
        except (URLError, HTTPError, TimeoutError, OSError) as exc:
            last_error = exc
            continue
    raise RuntimeError(f"fetch failed for {url}: {last_error}")


# ---------------------------------------------------------------------------
# پردازش
# ---------------------------------------------------------------------------

_NS_STRIP = re.compile(r"\{[^}]+\}")


def _tag(el) -> str:
    return _NS_STRIP.sub("", el.tag)


def _text(parent, name: str, default: str = "") -> str:
    for child in parent:
        if _tag(child) == name:
            return (child.text or "").strip()
        # فضای نام media:thumbnail / content:encoded
        if _tag(child).endswith(name):
            return (child.text or "").strip()
    return default


def _attr(parent, name: str, attr: str, default: str = "") -> str:
    for child in parent:
        if _tag(child) == name or _tag(child).endswith(name):
            return child.attrib.get(attr, default)
    return default


def _image(item) -> str | None:
    """عکس خبر را از enclosure یا media:thumbnail پیدا می‌کند."""
    for child in item:
        tag = _tag(child)
        if tag == "enclosure":
            url = child.attrib.get("url", "")
            if url and child.attrib.get("type", "").startswith("image"):
                return url
        if tag in ("thumbnail", "content"):
            url = child.attrib.get("url", "")
            if url and child.attrib.get("medium", "image") == "image":
                return url
            if url and tag == "thumbnail":
                return url
    return None


def _iso_date(raw: str) -> str | None:
    if not raw:
        return None
    try:
        return parsedate_to_datetime(raw).astimezone(timezone.utc).isoformat()
    except (ValueError, TypeError):
        pass
    try:
        return datetime.fromisoformat(raw).astimezone(timezone.utc).isoformat()
    except ValueError:
        return None


def _clean(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _is_basketball(text: str) -> bool:
    low = text.casefold()
    return any(k.casefold() in low for k in BASKETBALL_KEYWORDS)


def _make_id(source_id: str, link: str) -> str:
    digest = hashlib.sha1(f"{source_id}|{link}".encode("utf-8")).hexdigest()
    return f"{source_id}-{digest[:12]}"


def parse_feed(payload: bytes, source: dict) -> list[dict]:
    try:
        root = ET.fromstring(payload)
    except ET.ParseError:
        return []

    channel = root.find("channel")
    if channel is None:  # RSS 1.0 / RDF
        channel = root

    items = [el for el in channel if _tag(el) == "item"]
    out: list[dict] = []

    for item in items:
        title = _clean(_text(item, "title"))
        link = _text(item, "link")
        summary = _clean(_text(item, "description"))
        category = _clean(_text(item, "category")) or source["category"]
        image = _image(item)
        published = _iso_date(_text(item, "pubDate"))

        if not title or not link:
            continue

        haystack = f"{title} {summary}"
        if source["filter"] and not _is_basketball(haystack):
            continue

        # برای فیدهای عمومی، متن را با کلمه «بسکتبال» علامت می‌زنیم تا
        # رابط کاربری بتواند برچسب درست بگذارد.
        lang = source["language"]
        out.append({
            "id": _make_id(source["id"], link),
            "title": title,
            "summary": summary[:400],
            "url": link,
            "imageUrl": image,
            "source": source["id"],
            "sourceName": source["name"],
            "sourceNameEn": source["nameEn"],
            "language": lang,
            "category": category,
            "publishedAt": published,
        })

    return out


# ---------------------------------------------------------------------------
# پارسر API جست‌وجوی ورزش سه (خبر فارسی بسکتبال)
# ---------------------------------------------------------------------------

MAX_PAGES = 2  # حداکثر دو صفحه به ازای هر کوئری تا حجم درخواست معقول بماند


def fetch_search_news(source: dict) -> list[dict]:
    """خبر فارسی بسکتبال را از API جست‌وجوی ورزش سه می‌گیرد (با صفحه‌بندی)."""
    from urllib.parse import quote

    out: list[dict] = []
    seen: set[int] = set()

    for query in source["queries"]:
        url = f"{source['endpoint']}?q={quote(query)}&take=24"

        for _ in range(MAX_PAGES):
            try:
                payload = fetch(url, prefer_proxy=source["needsProxy"])
                data = json.loads(payload)
            except Exception:
                break

            items = data.get("items", [])
            if not items:
                break

            for it in items:
                news_id = it.get("id")
                link = it.get("link") or ""
                title = (it.get("title") or "").strip()
                if not news_id or not title or news_id in seen:
                    continue
                seen.add(news_id)

                out.append({
                    "id": f"{source['id']}-{news_id}",
                    "title": title,
                    "summary": (it.get("shortDescription") or "").strip()[:400],
                    "url": link,
                    "imageUrl": it.get("picture"),
                    "source": source["id"],
                    "sourceName": source["name"],
                    "sourceNameEn": source["nameEn"],
                    "language": source["language"],
                    "category": source["category"],
                    "publishedAt": it.get("publishedOn"),
                    "views": it.get("viewCountHumanReadable"),
                    "comments": it.get("commentCount"),
                })

            if not data.get("hasMore"):
                break
            nxt = next(
                (l.get("href") for l in data.get("_links", []) if l.get("rel") == "next"),
                None,
            )
            if not nxt:
                break
            url = nxt

    return out


# ---------------------------------------------------------------------------
# اجرا
# ---------------------------------------------------------------------------


def scrape() -> dict:
    news: list[dict] = []
    report: list[dict] = []

    for source in SOURCES:
        try:
            if source.get("type") == "search_api":
                items = fetch_search_news(source)
            else:
                payload = fetch(source["url"], prefer_proxy=source["needsProxy"])
                items = parse_feed(payload, source)
            news.extend(items)
            report.append({"source": source["id"], "ok": True, "items": len(items)})
        except Exception as exc:  # منبع خراب نباید کل اجرا را بکشد
            report.append({"source": source["id"], "ok": False, "error": str(exc)[:200]})

    # مرتب‌سازی: جدیدترین اول، حذف تکراری بر اساس لینک
    seen: set[str] = set()
    unique: list[dict] = []
    for item in sorted(
        news,
        key=lambda x: x.get("publishedAt") or "1970-01-01T00:00:00+00:00",
        reverse=True,
    ):
        if item["url"] in seen:
            continue
        seen.add(item["url"])
        unique.append(item)

    return {
        "version": 1,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "count": len(unique),
        "sources": report,
        "news": unique,
    }


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    data = scrape()

    target = OUT_DIR / "news.json"
    target.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # یک نسخهٔ «فقط آخرین» برای اپلیکیشن که سریع‌تر لود می‌شود
    (OUT_DIR / "news.min.json").write_text(
        json.dumps(data, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )

    print(f"generated {data['count']} items -> {target}")
    for src in data["sources"]:
        status = "OK " if src.get("ok") else "ERR"
        detail = src.get("items", src.get("error", ""))
        print(f"  [{status}] {src['source']}: {detail}")
    return 0 if any(s.get("ok") for s in data["sources"]) else 1


if __name__ == "__main__":
    sys.exit(main())
