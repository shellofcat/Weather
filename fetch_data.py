import json, re
from datetime import datetime
from zoneinfo import ZoneInfo
import requests

TZ = ZoneInfo("Australia/Sydney")
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36",
    "Accept": "text/html,application/json,*/*",
}

def compass(deg):
    try:
        d = ["N","NNE","NE","ENE","E","ESE","SE","SSE","S","SSW","SW","WSW","W","WNW","NW","NNW"]
        return d[int((float(deg) % 360 + 11.25) // 22.5) % 16]
    except Exception:
        return "--"

def fnum(v, n=1):
    try:
        return f"{float(v):.{n}f}" if v not in (None, "", "--") else "--"
    except Exception:
        return "--"

def fdeg(v):
    try:
        return int(round(float(v))) % 360 if v not in (None, "", "--") else "--"
    except Exception:
        return "--"

def fetch_text(url):
    for _ in range(3):
        try:
            r = requests.get(url, headers=HEADERS, timeout=10)
            if r.ok:
                return r.text
        except Exception:
            pass
    return ""

def parse_pansw_wind(html, label, pattern):
    out = {"name": label, "speed_kts": "--", "gust_kts": "--", "dir_deg": "--", "dir_cardinal": "--"}
    try:
        m = re.search(pattern + r".{0,500}?10 Min Mean Speed:\s*([0-9.]+)\s*knots.{0,120}?Gust:\s*([0-9.]+)\s*knots.{0,120}?Dir:\s*([0-9.]+)\s*deg", html, re.S | re.I)
        if m:
            deg = fdeg(m.group(3))
            return {
                "name": label,
                "speed_kts": fnum(m.group(1), 1),
                "gust_kts": fnum(m.group(2), 1),
                "dir_deg": deg,
                "dir_cardinal": compass(deg),
            }
    except Exception:
        pass
    return out

def parse_pansw_wave(html, label, pattern):
    out = {"name": label, "hs_m": "--", "hmax_m": "--", "tp_s": "--", "dir_deg": "--", "dir_cardinal": "--"}
    try:
        m = re.search(pattern + r".{0,400}?HS:\s*([0-9.]+)\s*m.{0,80}?Hmax:\s*([0-9.]+)\s*m.{0,80}?Tp:\s*([0-9.]+)\s*s(?:.{0,150}?Dir:\s*([0-9.]+)\s*deg)?", html, re.S | re.I)
        if m:
            deg = fdeg(m.group(4)) if m.group(4) else "--"
            return {
                "name": label,
                "hs_m": fnum(m.group(1), 2),
                "hmax_m": fnum(m.group(2), 2),
                "tp_s": fnum(m.group(3), 1),
                "dir_deg": deg,
                "dir_cardinal": compass(deg),
            }
    except Exception:
        pass
    return out

def parse_pansw_tide(html, pattern):
    try:
        m = re.search(pattern + r".{0,300}?Measured Height:\s*([0-9.]+)\s*m", html, re.S | re.I)
        if m:
            return fnum(m.group(1), 2)
    except Exception:
        pass
    return "--"

def fetch_mhl_sydney_offshore():
    out = {"name": "Sydney Offshore (Long Reef)", "hs_m": "--", "hmax_m": "--", "tp_s": "--", "dir_deg": "--", "dir_cardinal": "--"}
    try:
        html = fetch_text("https://mhl.nsw.gov.au/Station-SYDDOW")
        if not html:
            return out
        # Extract Highcharts data arrays embedded in MHL Station-SYDDOW page
        series = re.findall(r'name:\s*[\'"]([^\'"]+)[\'"].*?data:\s*(\[\[.*?\]\])', html, re.S)
        vals = {}
        for sname, sdata in series:
            nums = re.findall(r'\[\s*\d+\s*,\s*([0-9.]+)\s*\]', sdata)
            if nums:
                vals[sname.lower()] = nums[-1]
        hs = next((v for k, v in vals.items() if "hs" in k), "--")
        hm = next((v for k, v in vals.items() if "hmax" in k), "--")
        tp = next((v for k, v in vals.items() if "period" in k or "tp" in k), "--")
        dr = next((v for k, v in vals.items() if "dir" in k), "--")
        deg = fdeg(dr)
        if hs != "--":
            return {
                "name": "Sydney Offshore (Long Reef)",
                "hs_m": fnum(hs, 2),
                "hmax_m": fnum(hm, 2),
                "tp_s": fnum(tp, 1),
                "dir_deg": deg,
                "dir_cardinal": compass(deg),
            }
    except Exception:
        pass
    return out

def main():
    now = datetime.now(TZ)
    raw_html = fetch_text("https://wavewindtide.portauthoritynsw.com.au/")
    # Strip HTML tags so regex matches clean text cleanly
    clean_txt = re.sub(r"<[^>]+>", " ", raw_html)
    clean_txt = re.sub(r"\s+", " ", clean_txt)

    syd_winds = [
        parse_pansw_wind(clean_txt, "W Wedding Cake", r"Western Wedding Cake"),
        parse_pansw_wind(clean_txt, "Fort Denison", r"Fort Denison \(Sth end"),
        parse_pansw_wind(clean_txt, "Manns Point", r"Manns Point"),
        parse_pansw_wind(clean_txt, "Glebe Island", r"Glebe Island Wind"),
    ]

    bot_winds = [
        parse_pansw_wind(clean_txt, "Molineaux Point", r"Molineaux Point"),
        parse_pansw_wind(clean_txt, "Ampol Wharf", r"Ampol Wharf"),
        parse_pansw_wind(clean_txt, "Airport Runway", r"Sydney Airport \(Main Runway"),
        parse_pansw_wind(clean_txt, "Berry Island (Ref)", r"Berry Island"),
    ]

    syd_swell = fetch_mhl_sydney_offshore()
    bot_swell = parse_pansw_wave(clean_txt, "Botany Offshore", r"Botany Offshore \(Directional\) Wave")

    live_syd = parse_pansw_tide(clean_txt, r"Fort Denison-Primary Tide")
    live_bot = parse_pansw_tide(clean_txt, r"Pilot Jetty Tide")

    payload = {
        "updated_iso": now.isoformat(),
        "updated_display": now.strftime("%-d %b %Y · %-I:%M %p %Z"),
        "timezone": now.tzname() or "AEDT",
        "tides": {
            "sydney_live_m": live_syd,
            "botany_live_m": live_bot,
            "events": [
                {"type": "H", "time": "--", "height_m": "--"},
                {"type": "L", "time": "--", "height_m": "--"},
                {"type": "H", "time": "--", "height_m": "--"},
            ],
        },
        "sydney": {
            "title": "SYDNEY HARBOUR",
            "subtitle": "Port Jackson · 4 Stations",
            "winds": syd_winds,
            "swell": syd_swell,
        },
        "botany": {
            "title": "BOTANY BAY",
            "subtitle": "Port Botany · 4 Stations",
            "winds": bot_winds,
            "swell": bot_swell,
        },
    }

    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)

if __name__ == "__main__":
    main()
