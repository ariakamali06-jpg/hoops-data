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
        "name": "ورزش سه — لیگ و نتایج",
        "nameEn": "Varzesh3 Leagues & Results",
        "language": "fa",
        "category": "نتایج و جدول",
        "type": "league_api",
        # refId → شناسه لیگ در API ورزش سه
        # مسیرها و seasonId از /v2.0/basketball/leagues/{id} خوانده می‌شوند،
        # پس اگر ورزش سه فصل جدیدی بسازد نیازی به تغییر این فایل نیست.
        "leagues": [
            {"refId": 32, "name": "لیگ برتر بسکتبال ایران", "nameEn": "Iranian Basketball Super League",
             "country": "IR", "flag": "🇮🇷", "priority": 1},
            {"refId": 209, "name": "NBA", "nameEn": "NBA",
             "country": "US", "flag": "🏀", "priority": 2},
            {"refId": 205, "name": "لیگ باشگاه‌های غرب آسیا", "nameEn": "West Asia Clubs League",
             "country": "AS", "flag": "🌏", "priority": 3},
        ],
        "matchPages": 3,    # چند صفحه نتایج برای هر لیگ خوانده شود
        "fixturePages": 2,  # چند صفحه بازی‌های آینده
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


"""ماژول داده‌ی لیگ: جدول رده‌بندی، نتایج و بازی‌های آینده از API رسمی ورزش سه.

منبع: https://web-api.varzesh3.com/v2.0/basketball/leagues/{refId}
هر لیگ، seasonId و مسیرهای زیر را در تب‌های خودش اعلام می‌کند:
  مرحله گروهی → /seasons/{id}/multi-standing
  بازی ها     → /seasons/{id}/matches
نتایج گذشته: /seasons/{id}/results?skip=N
بازی آینده : /seasons/{id}/fixtures?skip=N
"""

import json
import re
from datetime import datetime, timezone

LEAGUE_API = "https://web-api.varzesh3.com/v2.0/basketball/leagues/{ref}"

# وضعیت بازی — از پاسخ واقعی API استخراج شد.
# کلید: status (int)، مقدار: (برچسب فارسی، برچسب کوتاه، آیا زنده است)
STATUS = {
    1:  ("برنامه‌ریزی‌شده", "برنامه", False),
    2:  ("شروع نشده", "شروع نشده", False),
    3:  ("کوارتر اول", "ک۱", True),
    4:  ("بین دو کوارتر", "بین‌کوارتر", True),
    5:  ("کوارتر دوم", "ک۲", True),
    6:  ("بین دو کوارتر", "بین‌کوارتر", True),
    7:  ("تمام‌شده", "تمام", False),
    8:  ("لغو شده", "لغو", False),
    9:  ("توقف", "توقف", True),
    10: ("تعویق", "تعویق", False),
    11: ("نیمه‌وقت", "نیمه‌وقت", True),
}

# بازی‌هایی که با وضعیت «توقف/لغو/تعویق» در فصل‌های گذشته رها شده‌اند،
# هرگز به‌روزرسانی نمی‌شوند و در فید زنده گیر می‌کنند. این‌ها حذف می‌شوند.
DEAD_STATUSES = {8, 9, 10}

# بازیِ «زنده» فقط وقتی معتبر است که امتیازش خالی نباشد؛
# برخی رکوردهای قدیمیِ نیمه‌کاره امتیاز ناقص دارند.
MIN_LIVE_SCORE = 1


def _is_stale(m: dict) -> bool:
    """بازی رهاشده/بی‌اعتبار است؟"""
    if m.get("status") in DEAD_STATUSES:
        return True
    # زنده‌ی بدون امتیاز معتبر نیست (مثل رکوردهای نیمه‌کاره‌ی قدیمی)
    if m.get("isLive") and (m.get("hostScore") is None or m.get("guestScore") is None):
        return True
    return False


def _api_get(url: str, prefer_proxy: bool = False) -> dict:
    return json.loads(fetch(url, prefer_proxy=prefer_proxy))


def _follow_paging(url: str, max_pages: int, prefer_proxy: bool) -> list[dict]:
    """صفحات API را دنبال می‌کند و همه‌ی roundها را جمع می‌کند."""
    collected: list[dict] = []
    seen: set[str] = set()
    for _ in range(max_pages):
        if not url or url in seen:
            break
        seen.add(url)
        try:
            data = _api_get(url, prefer_proxy)
        except Exception:
            break
        collected.extend(data.get("items", []))
        if not data.get("hasMore"):
            break
        url = next((l.get("href") for l in data.get("_links", []) if l.get("rel") == "next"), None)
    return collected


def _logo(team: dict | None) -> str | None:
    """لوگوی تیم را با سایز ۱۴۴ می‌گیرد تا روی صفحه موبایل تیز باشد."""
    if not team:
        return None
    if team.get("logo"):
        return re.sub(r"[?&]w=\d+", "", team["logo"]) + "?w=144"
    return None


def _short_name(name: str) -> str:
    """«پالایش نفت آبادان» → «نفت آبادان» برای جای محدود در رابط کاربری."""
    n = (name or "").strip()
    for prefix in ("پالایش ", "شهرداری ", "نفت و گاز ", "رعد پدافند ", "پترو نوین ",
                   "مهگل ", "پاس ", "بیمه "):
        if n.startswith(prefix):
            shortened = n[len(prefix):].strip()
            # «نفت آبادان» خوب است، «گرگان» هم خوب است
            return shortened or n
    return n


def _shamsi_to_iso(date: str | None) -> str | None:
    """«۱۴۰۵/۰۳/۰۵» → تقریب میلادی.

    تبدیل دقیق تقویم شمسی نیست؛ فقط برای مرتب‌سازی و نمایش تقریبی
    لازم است. اپلیکیشن تاریخ شمسی را از خود رشته‌ی `date` نگه می‌دارد.
    """
    if not date:
        return None
    m = re.match(r"\s*(\d{3,4})/(\d{1,2})/(\d{1,2})", str(date))
    if not m:
        return None
    year, month, day = (int(x) for x in m.groups())
    try:
        gy, gm = year + 621, month + 6
        if gm > 12:
            gm, gy = gm - 12, gy + 1
        return datetime(gy, gm, day, tzinfo=timezone.utc).date().isoformat()
    except ValueError:
        return None


def _parse_match(raw: dict, date: str | None, league: dict) -> dict:
    host = raw.get("host") or {}
    guest = raw.get("guest") or {}
    points = raw.get("matchPoints") or {}
    label, short, is_live = STATUS.get(raw.get("status"), ("نامشخص", "؟", False))

    quarters = []
    for i in (1, 2, 3, 4):
        h = (raw.get(f"quarterPoints{i}") or {}).get("host")
        g = (raw.get(f"quarterPoints{i}") or {}).get("guest")
        if h is not None or g is not None:
            quarters.append({"quarter": i, "host": h, "guest": g})

    # winner: ۰ نامشخص، ۱ میزبان، ۲ مهمان (طبق خروجی واقعی API)
    winner_raw = raw.get("winner")
    winner = "host" if winner_raw == 1 else ("guest" if winner_raw == 2 else None)

    score_h, score_g = points.get("host"), points.get("guest")
    link = raw.get("link")
    return {
        "id": raw.get("id"),
        "leagueId": f"lg-{league['refId']}",
        "leagueRef": league["refId"],
        "leagueName": league["name"],
        "leagueNameEn": league["nameEn"],
        "leagueFlag": league["flag"],
        "date": date,
        "dateIso": _shamsi_to_iso(date),
        "time": raw.get("time"),
        "status": raw.get("status"),
        "statusFa": label,
        "statusShort": short,
        "isLive": bool(raw.get("isLive")) or is_live,
        "host": {
            "id": host.get("id"),
            "name": host.get("name"),
            "shortName": _short_name(host.get("name") or ""),
            "logoUrl": _logo(host),
        },
        "guest": {
            "id": guest.get("id"),
            "name": guest.get("name"),
            "shortName": _short_name(guest.get("name") or ""),
            "logoUrl": _logo(guest),
        },
        "hostScore": score_h,
        "guestScore": score_g,
        "quarters": quarters,
        "winner": winner,
        "url": ("https://www.varzesh3.com" + link) if link else None,
    }


def _parse_standing_group(g: dict, stage_title: str) -> dict:
    """یک گروه/جدول را به ساختار استاندارد تبدیل می‌کند."""
    teams = []
    for idx, t in enumerate(g.get("teams") or []):
        name = t.get("name") or ""
        teams.append({
            "rank": idx + 1,               # ترتیب خودِ جدول = رتبه رسمی
            "manualRank": t.get("manualRank") or 0,
            "teamId": t.get("id"),
            "name": name,
            "shortName": _short_name(name),
            "logoUrl": _logo(t),
            "played": t.get("played"),
            "won": t.get("wins"),
            "lost": t.get("losses"),
            "pointsFor": t.get("goalFor"),
            "pointsAgainst": t.get("goalAgainst"),
            "diff": t.get("goalDifference"),
            "points": t.get("points"),
            "pointsDeducted": t.get("pointsDeducted") or 0,
            "winRate": t.get("winRate"),
            "form": t.get("form"),
        })
    return {"name": g.get("title") or stage_title, "teams": teams}


def _parse_standings(data: dict, league: dict, season_id: str) -> dict:
    """پاسخ multi-standing را به ساختار استاندارد تبدیل می‌کند.

    ساختار واقعی: {"standings": [{"id", "title", "teams": [...]}, ...]}
    هر عضو `standings` یک مرحله/گروه است (مثلاً گروه A، گروه B).
    """
    groups = []
    for g in data.get("standings") or []:
        parsed = _parse_standing_group(g, g.get("title") or league["name"])
        if parsed["teams"]:
            groups.append(parsed)

    all_teams = [t for g in groups for t in g["teams"]]
    return {
        "id": f"lg-{league['refId']}",
        "refId": league["refId"],
        "seasonId": season_id,
        "name": league["name"],
        "nameEn": league["nameEn"],
        "country": league["country"],
        "flag": league["flag"],
        "priority": league.get("priority", 99),
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "groups": groups,
        "teamCount": len(all_teams),
        "teams": all_teams,
    }


def fetch_league_data(source: dict) -> dict:
    """جدول رده‌بندی + نتایج + بازی‌های آینده‌ی همه‌ی لیگ‌ها را برمی‌گرداند."""
    leagues: list[dict] = []
    matches: list[dict] = []
    errors: list[str] = []

    for lg in source["leagues"]:
        try:
            meta = _api_get(LEAGUE_API.format(ref=lg["refId"]), source["needsProxy"])
        except Exception as exc:
            errors.append(f"{lg['name']} meta: {str(exc)[:110]}")
            continue

        # مسیرهای API از تب‌های خود لیگ خوانده می‌شوند تا با فصل جدید
        # خودکار هماهنگ بمانیم (نیازی به ویرایش دستی نیست).
        standing_url = match_url = None
        for tab in meta.get("tabs") or []:
            link = next((l.get("href") for l in tab.get("_links", []) if l.get("rel") == "get"), None)
            if not link:
                continue
            if "/multi-standing" in link:
                standing_url = link
            elif "/matches" in link:
                match_url = link

        season_id = ""
        if match_url:
            m = re.search(r"/seasons/(\d+)/", match_url)
            season_id = m.group(1) if m else ""
        base = match_url.rsplit("/", 1)[0] if match_url else ""

        if standing_url:
            try:
                leagues.append(_parse_standings(
                    _api_get(standing_url, source["needsProxy"]), lg, season_id))
            except Exception as exc:
                errors.append(f"{lg['name']} standing: {str(exc)[:110]}")
        else:
            errors.append(f"{lg['name']}: no standing endpoint")

        if base:
            # نتایج گذشته + بازی‌های آینده
            for path, pages in (("results", source["matchPages"]),
                                ("fixtures", source["fixturePages"])):
                url = f"{base}/{path}?skip=0"
                for rnd in _follow_paging(url, pages, source["needsProxy"]):
                    for dt in rnd.get("dates") or []:
                        for m in dt.get("matches") or []:
                            matches.append(_parse_match(m, dt.get("date"), lg))
        else:
            errors.append(f"{lg['name']}: no matches endpoint")

    # حذف تکراری بر اساس شناسه بازی، و حذف رکوردهای رهاشده
    seen: set = set()
    unique: list[dict] = []
    stale = 0
    for m in matches:
        mid = m.get("id")
        if mid is None or mid in seen:
            continue
        seen.add(mid)
        if _is_stale(m):
            stale += 1
            continue
        unique.append(m)

    def sort_key(m: dict) -> tuple:
        """زنده‌ها اول، سپس بر اساس تاریخ شمسی (نزولی) و ساعت."""
        nums = re.findall(r"\d+", m.get("date") or "")
        y, mo, d = (int(x) for x in nums[:3]) if len(nums) >= 3 else (0, 0, 0)
        return (0 if m.get("isLive") else 1, -y, -mo, -d, m.get("time") or "")

    unique.sort(key=sort_key)

    data = {
        "leagues": sorted(leagues, key=lambda x: x.get("priority", 99)),
        "matches": unique,
        "matchCount": len(unique),
        "teamCount": sum(lg.get("teamCount", 0) for lg in leagues),
        "liveCount": sum(1 for m in unique if m.get("isLive")),
        "staleDropped": stale,
    }
    if errors:
        data["errors"] = errors
    return data


def scrape() -> dict:
    """خبرها را از همه‌ی منابع خبری جمع می‌کند."""
    news: list[dict] = []
    report: list[dict] = []

    for source in SOURCES:
        if source.get("type") == "league_api":
            continue  # داده لیگ در مسیر جداگانه (league.json) پردازش می‌شود
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

    # ---- لیگ: جدول رده‌بندی + نتایج + بازی‌های آینده (فایل جداگانه) ----
    league_source = next((s for s in SOURCES if s.get("type") == "league_api"), None)
    if league_source:
        try:
            ldata = fetch_league_data(league_source)
            ldata["version"] = 2
            ldata["generatedAt"] = datetime.now(timezone.utc).isoformat()

            for fname, indent in (("league.json", 2), ("league.min.json", None)):
                path = OUT_DIR / fname
                if indent:
                    path.write_text(json.dumps(ldata, ensure_ascii=False, indent=indent),
                                    encoding="utf-8")
                else:
                    path.write_text(
                        json.dumps(ldata, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

            # نگه‌داشتن نام قدیمی برای سازگاری
            for fname in ("standings.json", "standings.min.json"):
                (OUT_DIR / fname).write_text(
                    json.dumps(ldata, ensure_ascii=False,
                               indent=2 if fname.endswith("standings.json") else None,
                               separators=None if fname.endswith("standings.json") else (",", ":")),
                    encoding="utf-8")

            size_kb = (OUT_DIR / "league.min.json").stat().st_size / 1024
            print(f"\ngenerated {ldata['matchCount']} matches / "
                  f"{ldata['teamCount']} teams ({size_kb:.0f} KB) -> {OUT_DIR / 'league.min.json'}")
            for lg in ldata["leagues"]:
                print(f"  [OK ] {lg['flag']} {lg['name']}: "
                      f"{lg['teamCount']} تیم در {len(lg['groups'])} گروه")
            live = [m for m in ldata["matches"] if m.get("isLive")]
            if live:
                print(f"  [LIVE] {len(live)} بازی زنده")
            for err in ldata.get("errors", []):
                print(f"  [ERR] {err}")
        except Exception as exc:
            print(f"  [ERR] league_api: {exc}")

    return 0 if any(s.get("ok") for s in data["sources"]) else 1


if __name__ == "__main__":
    sys.exit(main())
