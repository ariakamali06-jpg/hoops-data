#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ESPN Importer for Hoops Basketball
==================================
Imports genuine, official match schedules, standings, and boxscores from ESPN API
for NBA and WNBA, and combines them with verified FIBA Iran datasets.
"""

import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

DATA_DIR = Path("E:/hoops-data/data")
PUBLISH_DIR = Path("E:/hoops-publish")
PROXY_URL = os.environ.get("HOOPS_PROXY", "http://127.0.0.1:20811")

if PROXY_URL:
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({"http": PROXY_URL, "https": PROXY_URL})
    )
else:
    opener = urllib.request.build_opener()

def fetch_json(url, retries=3):
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=headers)
            with opener.open(req, timeout=20) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            if attempt == retries - 1:
                print(f"[WARN] Failed to fetch {url}: {e}")
                return None
            time.sleep(1.5)

def gregorian_to_jalali(gy, gm, gd):
    g_d_m = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    if gy > 1600:
        jy = 979
        gy -= 1600
    else:
        jy = 0
        gy -= 621
    gy2 = gy + 1 if gm > 2 else gy
    days = (365 * gy) + ((gy2 + 3) // 4) - ((gy2 + 99) // 100) + ((gy2 + 399) // 400) - 80 + gd + g_d_m[gm - 1]
    jy += 33 * (days // 12053)
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365
    if days < 186:
        jm = 1 + (days // 31)
        jd = 1 + (days % 31)
    else:
        jm = 7 + ((days - 186) // 30)
        jd = 1 + ((days - 186) % 30)
    return f"{jy:04d}/{jm:02d}/{jd:02d}"

NBA_TEAMS_FA = {
    "Atlanta Hawks": "آتلانتا هاوکس",
    "Boston Celtics": "بوستون سلتیکس",
    "Brooklyn Nets": "بروکلین نتس",
    "Charlotte Hornets": "شارلوت هورنتس",
    "Chicago Bulls": "شیکاگو بولز",
    "Cleveland Cavaliers": "کلیولند کاوالیرز",
    "Dallas Mavericks": "دالاس ماوریکس",
    "Denver Nuggets": "دنور ناگتس",
    "Detroit Pistons": "دیترویت پیستونز",
    "Golden State Warriors": "گلدن استیت واریرز",
    "Houston Rockets": "هیوستون راکتس",
    "Indiana Pacers": "ایندیانا پیسرز",
    "LA Clippers": "لس آنجلس کلیپرز",
    "Los Angeles Clippers": "لس آنجلس کلیپرز",
    "Los Angeles Lakers": "لس آنجلس لیکرز",
    "Memphis Grizzlies": "ممفیس گریزلیز",
    "Miami Heat": "میامی هیت",
    "Milwaukee Bucks": "میلواکی باکس",
    "Minnesota Timberwolves": "مینه سوتا تیمبرولوز",
    "New Orleans Pelicans": "نیواورلینز پلیکانز",
    "New York Knicks": "نیویورک نیکس",
    "Oklahoma City Thunder": "اوکلاهاما سیتی تاندر",
    "Orlando Magic": "اورلاندو مجیک",
    "Philadelphia 76ers": "فیلادلفیا سونی سیکسرز",
    "Phoenix Suns": "فینیکس سانز",
    "Portland Trail Blazers": "پورتلند تریل بلیزرز",
    "Sacramento Kings": "ساکرامنتو کینگز",
    "San Antonio Spurs": "سن آنتونیو اسپرز",
    "Toronto Raptors": "تورنتو رپترز",
    "Utah Jazz": "یوتا جاز",
    "Washington Wizards": "واشینگتن ویزاردز",
}

WNBA_TEAMS_FA = {
    "Atlanta Dream": "آتلانتا دریم",
    "Golden State Valkyries": "گلدن استیت والکریز",
    "New York Liberty": "نیویورک لیبرتی",
    "Las Vegas Aces": "لاس وگاس ایسز",
    "Indiana Fever": "ایندیانا فیور",
    "Minnesota Lynx": "مینه سوتا لینکس",
    "Connecticut Sun": "کنتیکت سان",
    "Seattle Storm": "سیاتل استورم",
    "Phoenix Mercury": "فینیکس مرکوری",
    "Dallas Wings": "دالاس وینگز",
    "Chicago Sky": "شیکاگو اسکای",
    "Los Angeles Sparks": "لس آنجلس اسپارکس",
    "Washington Mystics": "واشینگتن میستیکس",
    "Toronto Tempo": "تورنتو تمپو",
    "Portland Fire": "پورتلند فایر",
}

def parse_player(ath, starter):
    stats = ath.get("stats", [])
    if ath.get("didNotPlay") or not stats or len(stats) < 14:
        return None
    try:
        min_val = float(stats[0]) if stats[0].replace(".", "", 1).isdigit() else 0.0
    except:
        min_val = 0.0
    pts = int(stats[1]) if stats[1].lstrip("-").isdigit() else 0

    fg_parts = stats[2].split("-") if "-" in stats[2] else ["0", "0"]
    fgm = int(fg_parts[0]) if fg_parts[0].isdigit() else 0
    fga = int(fg_parts[1]) if len(fg_parts) > 1 and fg_parts[1].isdigit() else 0
    fgPct = round(fgm / fga * 100, 1) if fga > 0 else 0.0

    tp_parts = stats[3].split("-") if "-" in stats[3] else ["0", "0"]
    tpm = int(tp_parts[0]) if tp_parts[0].isdigit() else 0
    tpa = int(tp_parts[1]) if len(tp_parts) > 1 and tp_parts[1].isdigit() else 0
    tpPct = round(tpm / tpa * 100, 1) if tpa > 0 else 0.0

    twm = max(0, fgm - tpm)
    twa = max(0, fga - tpa)
    twPct = round(twm / twa * 100, 1) if twa > 0 else 0.0

    ft_parts = stats[4].split("-") if "-" in stats[4] else ["0", "0"]
    ftm = int(ft_parts[0]) if ft_parts[0].isdigit() else 0
    fta = int(ft_parts[1]) if len(ft_parts) > 1 and ft_parts[1].isdigit() else 0
    ftPct = round(ftm / fta * 100, 1) if fta > 0 else 0.0

    reb = int(stats[5]) if stats[5].lstrip("-").isdigit() else 0
    ast = int(stats[6]) if stats[6].lstrip("-").isdigit() else 0
    tov = int(stats[7]) if stats[7].lstrip("-").isdigit() else 0
    stl = int(stats[8]) if stats[8].lstrip("-").isdigit() else 0
    blk = int(stats[9]) if stats[9].lstrip("-").isdigit() else 0
    rebO = int(stats[10]) if stats[10].lstrip("-").isdigit() else 0
    rebD = int(stats[11]) if stats[11].lstrip("-").isdigit() else 0
    pf = int(stats[12]) if stats[12].lstrip("-").isdigit() else 0
    plusMinus = int(stats[13].lstrip("+")) if stats[13].lstrip("+-").isdigit() else 0

    eff = float(pts + reb + ast + stl + blk - (fga - fgm) - (fta - ftm) - tov)

    athlete_info = ath.get("athlete", {})
    names = athlete_info.get("displayName", "").split(" ", 1)
    firstName = names[0] if len(names) > 0 else ""
    lastName = names[1] if len(names) > 1 else ""

    return {
        "id": athlete_info.get("id", ""),
        "name": athlete_info.get("displayName", ""),
        "firstName": firstName,
        "lastName": lastName,
        "shirt": athlete_info.get("jersey", ""),
        "position": athlete_info.get("position", {}).get("abbreviation", ""),
        "photo": athlete_info.get("headshot", {}).get("href", ""),
        "starter": 1 if starter else 0,
        "min": min_val,
        "pts": pts,
        "fgm": fgm,
        "fga": fga,
        "fgPct": fgPct,
        "tpm": tpm,
        "tpa": tpa,
        "tpPct": tpPct,
        "twm": twm,
        "twa": twa,
        "twPct": twPct,
        "ftm": ftm,
        "fta": fta,
        "ftPct": ftPct,
        "rebO": rebO,
        "rebD": rebD,
        "reb": reb,
        "ast": ast,
        "stl": stl,
        "blk": blk,
        "tov": tov,
        "pf": pf,
        "plusMinus": plusMinus,
        "ptsInPaint": 0,
        "ptsFastBreak": 0,
        "ptsSecondChance": 0,
        "eff": eff
    }

def fetch_espn_game_boxscore(league_code, event_id):
    sport_path = "basketball/wnba" if league_code == "wnba" else "basketball/nba"
    url = f"https://site.api.espn.com/apis/site/v2/sports/{sport_path}/summary?event={event_id}"
    sdata = fetch_json(url)
    if not sdata or "header" not in sdata:
        return None

    header = sdata["header"]
    comp = header.get("competitions", [{}])[0]
    status_desc = comp.get("status", {}).get("type", {}).get("description", "")
    if status_desc.lower() not in ("final", "completed"):
        return None

    comps = comp.get("competitors", [])
    if len(comps) < 2:
        return None

    home_comp = next((c for c in comps if c.get("homeAway") == "home"), comps[0])
    away_comp = next((c for c in comps if c.get("homeAway") == "away"), comps[1])

    home_name = home_comp.get("team", {}).get("displayName", "")
    away_name = away_comp.get("team", {}).get("displayName", "")

    team_fa_map = WNBA_TEAMS_FA if league_code == "wnba" else NBA_TEAMS_FA
    home_local = team_fa_map.get(home_name, home_name)
    away_local = team_fa_map.get(away_name, away_name)

    home_score = int(home_comp.get("score", 0))
    away_score = int(away_comp.get("score", 0))

    home_quarters = [int(ls.get("displayValue", 0)) for ls in home_comp.get("linescores", []) if ls.get("displayValue", "").isdigit()]
    away_quarters = [int(ls.get("displayValue", 0)) for ls in away_comp.get("linescores", []) if ls.get("displayValue", "").isdigit()]

    box_players_data = sdata.get("boxscore", {}).get("players", [])
    home_players = []
    away_players = []

    for p_team in box_players_data:
        t_id = p_team.get("team", {}).get("id")
        is_home = (t_id == home_comp.get("team", {}).get("id"))
        target_list = home_players if is_home else away_players

        for stat_sec in p_team.get("statistics", []):
            athletes = stat_sec.get("athletes", [])
            for idx, ath in enumerate(athletes):
                is_starter = (idx < 5)
                parsed = parse_player(ath, is_starter)
                if parsed:
                    target_list.append(parsed)

    box_teams_data = sdata.get("boxscore", {}).get("teams", [])
    def extract_totals(team_id):
        t_obj = next((t for t in box_teams_data if t.get("team", {}).get("id") == team_id), {})
        stats = {s.get("name"): s.get("displayValue") for s in t_obj.get("statistics", [])}
        fg_p = (stats.get("fieldGoalsMade-fieldGoalsAttempted") or "0-0").split("-")
        tp_p = (stats.get("threePointFieldGoalsMade-threePointFieldGoalsAttempted") or "0-0").split("-")
        ft_p = (stats.get("freeThrowsMade-freeThrowsAttempted") or "0-0").split("-")
        return {
            "fgm": int(fg_p[0]) if fg_p[0].isdigit() else 0,
            "fga": int(fg_p[1]) if len(fg_p) > 1 and fg_p[1].isdigit() else 0,
            "tpm": int(tp_p[0]) if tp_p[0].isdigit() else 0,
            "tpa": int(tp_p[1]) if len(tp_p) > 1 and tp_p[1].isdigit() else 0,
            "ftm": int(ft_p[0]) if ft_p[0].isdigit() else 0,
            "fta": int(ft_p[1]) if len(ft_p) > 1 and ft_p[1].isdigit() else 0,
            "rebO": int(stats.get("offensiveRebounds", 0)) if str(stats.get("offensiveRebounds", "")).isdigit() else 0,
            "rebD": int(stats.get("defensiveRebounds", 0)) if str(stats.get("defensiveRebounds", "")).isdigit() else 0,
            "reb": int(stats.get("totalRebounds", 0)) if str(stats.get("totalRebounds", "")).isdigit() else 0,
            "ast": int(stats.get("assists", 0)) if str(stats.get("assists", "")).isdigit() else 0,
            "stl": int(stats.get("steals", 0)) if str(stats.get("steals", "")).isdigit() else 0,
            "blk": int(stats.get("blocks", 0)) if str(stats.get("blocks", "")).isdigit() else 0,
            "tov": int(stats.get("turnovers", 0)) if str(stats.get("turnovers", "")).isdigit() else 0,
            "pf": int(stats.get("fouls", 0)) if str(stats.get("fouls", "")).isdigit() else 0,
            "benchPts": 0, "paintPts": 0, "turnoverPts": 0, "fastBreakPts": 0, "secondChancePts": 0
        }

    home_totals = extract_totals(home_comp.get("team", {}).get("id"))
    away_totals = extract_totals(away_comp.get("team", {}).get("id"))

    game_date = comp.get("date", "")[:10]

    return {
        "id": f"espn_{league_code}_{event_id}",
        "date": game_date,
        "tipoff": comp.get("date", ""),
        "league": league_code,
        "home": {
            "name": home_name,
            "nameLocal": home_local,
            "code": home_comp.get("team", {}).get("abbreviation", ""),
            "logo": home_comp.get("team", {}).get("logo", ""),
            "coach": "",
            "score": home_score,
            "quarters": home_quarters,
            "totals": home_totals,
            "players": home_players
        },
        "away": {
            "name": away_name,
            "nameLocal": away_local,
            "code": away_comp.get("team", {}).get("abbreviation", ""),
            "logo": away_comp.get("team", {}).get("logo", ""),
            "coach": "",
            "score": away_score,
            "quarters": away_quarters,
            "totals": away_totals,
            "players": away_players
        }
    }

def convert_espn_to_app_match(ev, league_ref, league_name, league_name_en, league_flag):
    comp = ev.get("competitions", [{}])[0]
    comps = comp.get("competitors", [])
    if len(comps) < 2:
        return None

    home_comp = next((c for c in comps if c.get("homeAway") == "home"), comps[0])
    away_comp = next((c for c in comps if c.get("homeAway") == "away"), comps[1])

    home_name = home_comp.get("team", {}).get("displayName", "")
    away_name = away_comp.get("team", {}).get("displayName", "")

    team_fa_map = WNBA_TEAMS_FA if league_ref == 3001 else NBA_TEAMS_FA
    home_local = team_fa_map.get(home_name, home_name)
    away_local = team_fa_map.get(away_name, away_name)

    status_type = comp.get("status", {}).get("type", {})
    status_desc = status_type.get("description", "")
    is_completed = status_desc.lower() in ("final", "completed")
    is_live = status_desc.lower() in ("in progress", "live", "halftime")

    status_code = 7 if is_completed else (2 if is_live else 1)
    status_fa = "تمام‌شده" if is_completed else ("در حال بازی" if is_live else "برنامه‌ریزی‌شده")
    status_short = "تمام" if is_completed else ("زنده" if is_live else "برنامه")

    dt_str = ev.get("date", "")
    iso_date = dt_str[:10]
    time_str = dt_str[11:16] if len(dt_str) >= 16 else "00:00"

    try:
        y, m, d = int(iso_date[:4]), int(iso_date[5:7]), int(iso_date[8:10])
        jalali_date = gregorian_to_jalali(y, m, d)
    except:
        jalali_date = iso_date

    h_score = int(home_comp.get("score", 0)) if is_completed or is_live else None
    a_score = int(away_comp.get("score", 0)) if is_completed or is_live else None

    winner = None
    if is_completed and h_score is not None and a_score is not None:
        winner = "host" if h_score > a_score else ("guest" if a_score > h_score else "draw")

    quarters = []
    h_lines = home_comp.get("linescores", [])
    a_lines = away_comp.get("linescores", [])
    for idx in range(max(len(h_lines), len(a_lines))):
        hq = int(h_lines[idx].get("displayValue", 0)) if idx < len(h_lines) and h_lines[idx].get("displayValue", "").isdigit() else 0
        aq = int(a_lines[idx].get("displayValue", 0)) if idx < len(a_lines) and a_lines[idx].get("displayValue", "").isdigit() else 0
        quarters.append({
            "quarter": idx + 1,
            "host": hq,
            "guest": aq
        })

    ev_id = int(ev.get("id", 0)) if str(ev.get("id", "")).isdigit() else hash(ev.get("id")) & 0x7FFFFFFF

    return {
        "id": ev_id,
        "leagueId": f"lg-{league_ref}",
        "leagueRef": league_ref,
        "leagueName": league_name,
        "leagueNameEn": league_name_en,
        "leagueFlag": league_flag,
        "date": jalali_date,
        "dateIso": iso_date,
        "time": time_str,
        "status": status_code,
        "statusFa": status_fa,
        "statusShort": status_short,
        "isLive": is_live,
        "host": {
            "id": int(home_comp.get("team", {}).get("id", 0)) if str(home_comp.get("team", {}).get("id", "")).isdigit() else 0,
            "name": home_local,
            "shortName": home_local,
            "logoUrl": home_comp.get("team", {}).get("logo", "")
        },
        "guest": {
            "id": int(away_comp.get("team", {}).get("id", 0)) if str(away_comp.get("team", {}).get("id", "")).isdigit() else 0,
            "name": away_local,
            "shortName": away_local,
            "logoUrl": away_comp.get("team", {}).get("logo", "")
        },
        "hostScore": h_score,
        "guestScore": a_score,
        "quarters": quarters,
        "winner": winner,
        "url": None
    }

def main():
    print("=== Starting Official ESPN & FIBA Importer ===")

    # 1. Load the 237 verified FIBA matches from hoops-publish
    fiba_path = PUBLISH_DIR / "boxscores.json"
    if not fiba_path.exists():
        print(f"[ERR] {fiba_path} not found!")
        return 1

    fiba_data = json.loads(fiba_path.read_text(encoding="utf-8"))
    verified_games = list(fiba_data.get("games", []))
    print(f"[OK] Loaded {len(verified_games)} verified FIBA games from {fiba_path}")

    # 2. Fetch WNBA games from ESPN
    print("\nFetching WNBA games from ESPN...")
    wnba_scoreboard = fetch_json("https://site.api.espn.com/apis/site/v2/sports/basketball/wnba/scoreboard")
    wnba_dates = []
    if wnba_scoreboard and "leagues" in wnba_scoreboard:
        cal = wnba_scoreboard["leagues"][0].get("calendar", [])
        wnba_dates = [c.split("T")[0].replace("-", "") for c in cal if "2026-09" in c or "2026-10" in c]

    espn_games = []
    wnba_app_matches = []
    seen_events = set()

    for d in wnba_dates[-12:]:
        sb = fetch_json(f"https://site.api.espn.com/apis/site/v2/sports/basketball/wnba/scoreboard?dates={d}")
        if not sb:
            continue
        for ev in sb.get("events", []):
            ev_id = ev.get("id")
            if ev_id in seen_events:
                continue
            seen_events.add(ev_id)

            app_m = convert_espn_to_app_match(ev, 3001, "WNBA بانوان", "WNBA", "🏀")
            if app_m:
                wnba_app_matches.append(app_m)

            comp = ev.get("competitions", [{}])[0]
            status_desc = comp.get("status", {}).get("type", {}).get("description", "")
            if status_desc.lower() in ("final", "completed"):
                print(f"  Fetching WNBA boxscore: {ev.get('name')} ({ev.get('date')[:10]})...")
                box = fetch_espn_game_boxscore("wnba", ev_id)
                if box:
                    espn_games.append(box)

    print(f"[OK] Collected {len([g for g in espn_games if g['league'] == 'wnba'])} WNBA boxscores, {len(wnba_app_matches)} app matches")

    # 3. Fetch NBA games from ESPN
    print("\nFetching NBA games from ESPN...")
    nba_dates_past = [f"202610{d:02d}" for d in range(11, 18)]
    nba_dates_future = [f"202610{d:02d}" for d in range(20, 24)]
    nba_dates = nba_dates_past + nba_dates_future

    nba_app_matches = []
    for d in nba_dates:
        sb = fetch_json(f"https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates={d}")
        if not sb:
            continue
        for ev in sb.get("events", []):
            ev_id = ev.get("id")
            if ev_id in seen_events:
                continue
            seen_events.add(ev_id)

            app_m = convert_espn_to_app_match(ev, 209, "NBA", "NBA", "🏀")
            if app_m:
                nba_app_matches.append(app_m)

            comp = ev.get("competitions", [{}])[0]
            status_desc = comp.get("status", {}).get("type", {}).get("description", "")
            if status_desc.lower() in ("final", "completed"):
                print(f"  Fetching NBA boxscore: {ev.get('name')} ({ev.get('date')[:10]})...")
                box = fetch_espn_game_boxscore("nba", ev_id)
                if box:
                    espn_games.append(box)

    print(f"[OK] Collected {len([g for g in espn_games if g['league'] == 'nba'])} NBA boxscores, {len(nba_app_matches)} app matches")

    # 4. Merge all boxscore games
    all_games = espn_games + verified_games
    all_games.sort(key=lambda g: g.get("date", ""), reverse=True)

    by_league = {}
    for g in all_games:
        l = g.get("league", "other")
        by_league[l] = by_league.get(l, 0) + 1

    combined_db = {
        "schema": 2,
        "source": "FIBA LiveStats Official + ESPN Public API",
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "count": len(all_games),
        "byLeague": by_league,
        "games": all_games
    }

    out_file = DATA_DIR / "boxscores.json"
    out_file.write_text(json.dumps(combined_db, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[SUCCESS] Written {len(all_games)} genuine games to {out_file}: {by_league}")

    # Build index
    index_games = []
    for g in all_games:
        index_games.append({
            "id": g["id"],
            "date": g["date"],
            "tipoff": g.get("tipoff", ""),
            "league": g["league"],
            "home": {
                "name": g["home"]["name"],
                "nameLocal": g["home"].get("nameLocal", g["home"]["name"]),
                "code": g["home"]["code"],
                "logo": g["home"]["logo"],
                "score": g["home"]["score"]
            },
            "away": {
                "name": g["away"]["name"],
                "nameLocal": g["away"].get("nameLocal", g["away"]["name"]),
                "code": g["away"]["code"],
                "logo": g["away"]["logo"],
                "score": g["away"]["score"]
            }
        })

    index_db = {
        "schema": 2,
        "source": "FIBA LiveStats Official + ESPN Public API",
        "generated": combined_db["generated"],
        "count": len(index_games),
        "byLeague": by_league,
        "games": index_games
    }
    index_file = DATA_DIR / "boxscores.index.json"
    index_file.write_text(json.dumps(index_db, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[SUCCESS] Written index to {index_file}")

    # 5. Build official WNBA Standings from ESPN
    print("\nFetching WNBA Standings from ESPN...")
    wnba_standings = fetch_json("https://site.api.espn.com/apis/v2/sports/basketball/wnba/standings")
    wnba_groups = []
    if wnba_standings:
        for conf in wnba_standings.get("children", []):
            conf_name_en = conf.get("name", "")
            conf_name_fa = "کنفرانس شرق" if "East" in conf_name_en else "کنفرانس غرب"
            teams_list = []
            for rank, entry in enumerate(conf.get("standings", {}).get("entries", []), 1):
                t = entry.get("team", {})
                t_name = t.get("displayName", "")
                t_fa = WNBA_TEAMS_FA.get(t_name, t_name)
                stats = {s.get("name"): s.get("value") for s in entry.get("stats", [])}
                wins = int(stats.get("wins", 0))
                losses = int(stats.get("losses", 0))
                played = wins + losses
                points = wins * 2 + losses
                teams_list.append({
                    "rank": rank,
                    "teamId": int(t.get("id", 0)) if str(t.get("id", "")).isdigit() else rank,
                    "name": t_fa,
                    "shortName": t_fa,
                    "nameEn": t_name,
                    "logoUrl": t.get("logos", [{}])[0].get("href", ""),
                    "played": played,
                    "won": wins,
                    "lost": losses,
                    "diff": 0,
                    "points": points
                })
            wnba_groups.append({
                "name": conf_name_fa,
                "nameEn": conf_name_en,
                "teams": teams_list
            })

    wnba_league = {
        "refId": 3001,
        "name": "WNBA بانوان",
        "nameEn": "WNBA",
        "country": "US",
        "flag": "🏀",
        "priority": 3,
        "teamCount": sum(len(g["teams"]) for g in wnba_groups),
        "groups": wnba_groups
    }

    # 6. Update app.json
    app_json_path = DATA_DIR / "app.json"
    if app_json_path.exists():
        app_json = json.loads(app_json_path.read_text(encoding="utf-8"))
        # Remove old fake NBA matches (refId 209) and old WNBA matches
        cleaned_matches = [m for m in app_json.get("matches", []) if m.get("leagueRef") not in (209, 3001)]

        # Add real NBA and WNBA matches
        new_matches = cleaned_matches + nba_app_matches + wnba_app_matches

        # Update leagues list
        leagues = [lg for lg in app_json.get("leagues", []) if lg.get("refId") != 3001]
        # Insert WNBA after NBA
        leagues.append(wnba_league)
        leagues.sort(key=lambda l: l.get("priority", 99))

        app_json["generatedAt"] = combined_db["generated"]
        app_json["matchCount"] = len(new_matches)
        app_json["leagues"] = leagues
        app_json["matches"] = new_matches

        app_json_path.write_text(json.dumps(app_json, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        print(f"[SUCCESS] Updated {app_json_path} with {len(new_matches)} matches and WNBA league")

if __name__ == "__main__":
    main()
