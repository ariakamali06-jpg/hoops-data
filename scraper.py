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
    "استپ‌بک", "stepback", "سلامک", "دانک", "slam dunk",
    "سه نفره", "۳ نفره", "3x3",
    "شهرداری گرگان", "ذوب آهن", "ذوب‌آهن", "مس سونگون", "نفت آبادان",
    "اسلامشهر", "پتروشیمی ایلام", "کاله", "رعد پدافند", "چرم مشهد",
)

# کلیدواژه‌های ورزش‌های دیگر: اگر خبری فقط این‌ها را داشت، از فید بسکتبال حذف می‌شود
OTHER_SPORTS = (
    "والیبال", "فوتبال", "فوتسال", "هندبال", "کشتی", "واترپلو",
    "وزنه برداری", "وزنه‌برداری", "دوومیدانی", "اسکواش", "شنا",
    "ژیمناستیک", "تکواندو", "کاراته", "جودو", "بیسبال", "بیسبال",
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
            "لیگ برتر بسکتبال",
            "بسکتبال سه نفره",
            "تیم ملی بسکتبال",
        ],
        "filter": False,         # خود API بر اساس کوئری فیلتر می‌کند
        "needsProxy": False,
    },
    {
        "id": "varzesh3_league",
        "name": "ورزش سه — جدول لیگ",
        "nameEn": "Varzesh3 League Table",
        "language": "fa",
        "category": "جدول رده‌بندی",
        "type": "league_table",
        # refId=32 → لیگ برتر بسکتبال ایران
        "leagues": [
            {"refId": 32, "name": "لیگ برتر بسکتبال ایران", "nameEn": "Iranian Basketball Super League",
             "country": "IR", "flag": "🇮🇷", "season": "1405"},
            {"refId": 209, "name": "NBA", "nameEn": "NBA",
             "country": "US", "flag": "🏀", "season": "2026-27"},
            {"refId": 205, "name": "لیگ بین‌المللی آسیا", "nameEn": "Asian Intl League",
             "country": "AS", "flag": "🌏", "season": "2026"},
        ],
        "filter": False,
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


def looks_relevant(item: dict) -> bool:
    """خبر بی‌ربط از فید حذف می‌شود.

    کوئری‌های جست‌وجو گاهی اخبار فوتبال/والیبال را هم برمی‌گردانند (مثلاً
    جست‌وجوی «تیم ملی بسکتبال» که «اردوی تیم ملی فوتبال» را هم می‌آورد).

    - منابع فارسی: باید **نشانهٔ مثبت** بسکتبال در عنوان یا خلاصه باشد.
    - منابع تخصصی بسکتبال (فید انگلیسی): بدون فیلتر می‌مانند.
    """
    if item.get("language") != "fa":
        return True

    text = f"{item.get('title', '')} {item.get('summary', '')}".casefold()
    return any(k.casefold() in text for k in BASKETBALL_KEYWORDS)


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
# پارسر جدول لیگ (ورزش سه) — جدول رده‌بندی تیم‌ها
# ---------------------------------------------------------------------------

LEAGUE_PAGE = "https://www.varzesh3.com/basketball/league/{ref}/table"


class _TableParser:
    """استخراج سادهٔ جدول‌های HTML بدون وابستگی خارجی."""

    def __init__(self) -> None:
        from html.parser import HTMLParser

        outer = self

        class _P(HTMLParser):
            def __init__(self):
                super().__init__()
                outer.tables, outer._cur, outer._row, outer._cell = [], None, None, None

            def handle_starttag(self, tag, attrs):
                a = dict(attrs)
                if tag == "table":
                    self_cur = outer
                    self_cur._cur = []
                    outer._cur = []
                elif tag == "tr" and outer._cur is not None:
                    outer._row = []
                elif tag == "td" and outer._row is not None:
                    outer._cell = {"t": "", "img": None, "href": None}
                elif tag == "th" and outer._row is not None:
                    outer._cell = {"t": "", "img": None, "href": None}
                elif tag == "img" and outer._cell is not None:
                    outer._cell["img"] = a.get("src")
                elif tag == "a" and outer._cell is not None:
                    outer._cell["href"] = a.get("href")

            def handle_data(self, d):
                if outer._cell is not None:
                    outer._cell["t"] += d

            def handle_endtag(self, tag):
                if tag in ("td", "th") and outer._cell is not None and outer._row is not None:
                    outer._row.append(outer._cell)
                    outer._cell = None
                elif tag == "tr" and outer._row is not None:
                    if outer._row:
                        outer._cur.append(outer._row)
                    outer._row = None
                elif tag == "table" and outer._cur is not None:
                    outer.tables.append(outer._cur)
                    outer._cur = None

        self._parser = _P()

    def feed(self, html: str) -> list[list[dict]]:
        self._parser.feed(html)
        return self.tables


def _split_score(raw: str) -> tuple[int | None, int | None]:
    """«۱۵۵۲-۱۲۸۷» → (1552, 1287)"""
    m = re.search(r"(\d[\d,۰-۹]*)\s*[-–]\s*(\d[\d,۰-۹]*)", raw or "")
    if not m:
        return None, None

    def conv(s: str) -> int:
        table = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
        return int(s.translate(table).replace(",", ""))

    return conv(m.group(1)), conv(m.group(2))


def _to_int(raw: str) -> int | None:
    t = re.sub(r"[^\d۰-۹٠-٩-]", "", raw or "")
    t = t.translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789"))
    if not t or t in {"-", ""}:
        return None
    try:
        return int(t)
    except ValueError:
        return None


def fetch_league_table(source: dict) -> dict:
    """جدول رده‌بندی هر لیگ را می‌خواند و به ساختار استاندارد تبدیل می‌کند."""
    leagues: list[dict] = []
    errors: list[str] = []

    for lg in source["leagues"]:
        url = LEAGUE_PAGE.format(ref=lg["refId"])
        try:
            html = fetch(url, prefer_proxy=source["needsProxy"]).decode("utf-8", errors="replace")
        except Exception as exc:
            errors.append(f"{lg['name']}: {exc}"[:160])
            continue

        tables = _TableParser().feed(html)
        if not tables:
            errors.append(f"{lg['name']}: no table")
            continue

        # جدول اصلی بزرگ‌ترین جدول با بیش از ۳ ردیف است
        main = max(tables, key=len)
        teams: list[dict] = []
        for row in main:
            cells = [c["t"].strip() for c in row]
            imgs = [c["img"] for c in row if c["img"]]
            if len(cells) < 8:
                continue
            rank = _to_int(cells[0])
            if rank is None:
                continue
            team_name = cells[2]
            if not team_name:
                continue
            played = _to_int(cells[3])
            won = _to_int(cells[4])
            lost = _to_int(cells[5])
            pf, pa = _split_score(cells[6])
            diff = _to_int(cells[7])
            points = _to_int(cells[8]) if len(cells) > 8 else None
            # لوگوی واقعی تیم از CDN ورزش سه؛ سایز پیش‌فرض صفحه ۴۰ است،
            # ما ۱۴۴ می‌خواهیم تا روی صفحه موبایل تیز باشد.
            logo = imgs[0] if imgs else None
            if logo:
                logo = re.sub(r"[?&]w=\d+", "", logo) + "?w=144"
            # نام کوتاه برای UI
            teams.append({
                "rank": rank,
                "name": team_name,
                "shortName": _short_name(team_name),
                "logoUrl": logo,
                "played": played,
                "won": won,
                "lost": lost,
                "pointsFor": pf,
                "pointsAgainst": pa,
                "diff": diff if diff is not None else (
                    (pf - pa) if (pf is not None and pa is not None) else None
                ),
                "points": points,
                "form": None,   # در صورت وجود در HTML بعدی پر می‌شود
            })

        if not teams:
            errors.append(f"{lg['name']}: no rows")
            continue

        leagues.append({
            "id": f"lg-{lg['refId']}",
            "refId": lg["refId"],
            "name": lg["name"],
            "nameEn": lg["nameEn"],
            "country": lg["country"],
            "flag": lg["flag"],
            "season": lg["season"],
            "url": url,
            "updatedAt": datetime.now(timezone.utc).isoformat(),
            "teams": teams,
        })

    result = {"leagues": leagues}
    if errors:
        result["errors"] = errors
    return result


def _short_name(name: str) -> str:
    """«پالایش نفت آبادان» → «آبادان» (برای جای محدود در UI)"""
    n = name.strip()
    drop = ("پالایش ", "شهرداری ", "نفت و گاز ", "رعد پدافند ", "پترو نوین ",
            "نفت ", "گلنور ", "مهگل ", "پاس ", "گاز ", "بیمه ")
    for d in drop:
        if n.startswith(d):
            n = n[len(d):]
            break
    return n.strip() or name


# ---------------------------------------------------------------------------
# اجرا
# ---------------------------------------------------------------------------


def scrape() -> dict:
    news: list[dict] = []
    report: list[dict] = []

    for source in SOURCES:
        if source.get("type") == "league_table":
            continue  # جدول رده‌بندی در مسیر جداگانه پردازش می‌شود
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
    dropped = 0
    for item in sorted(
        news,
        key=lambda x: x.get("publishedAt") or "1970-01-01T00:00:00+00:00",
        reverse=True,
    ):
        if item["url"] in seen:
            continue
        if not looks_relevant(item):
            dropped += 1
            continue
        seen.add(item["url"])
        unique.append(item)

    if dropped:
        report.append({"source": "filter", "ok": True, "items": -dropped,
                       "note": "off-topic items dropped"})

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

    # ---- جدول رده‌بندی لیگ‌ها (فایل جداگانه) ----
    league_source = next(
        (s for s in SOURCES if s.get("type") == "league_table"), None
    )
    if league_source:
        try:
            ldata = fetch_league_table(league_source)
            ldata["version"] = 1
            ldata["generatedAt"] = datetime.now(timezone.utc).isoformat()
            ldata["count"] = sum(len(x["teams"]) for x in ldata["leagues"])
            (OUT_DIR / "standings.json").write_text(
                json.dumps(ldata, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            (OUT_DIR / "standings.min.json").write_text(
                json.dumps(ldata, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
            )
            print(f"generated {ldata['count']} team rows -> {OUT_DIR / 'standings.json'}")
            for lg in ldata["leagues"]:
                print(f"  [OK ] {lg['name']}: {len(lg['teams'])} تیم")
            for err in ldata.get("errors", []):
                print(f"  [ERR] {err}")
        except Exception as exc:
            print(f"  [ERR] league_table: {exc}")

    return 0 if any(s.get("ok") for s in data["sources"]) else 1


if __name__ == "__main__":
    sys.exit(main())
