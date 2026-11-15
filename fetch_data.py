import json, os, math
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import requests

TZ = ZoneInfo("Australia/Sydney")
WW_KEY = os.environ.get("WILLYWEATHER_API_KEY", "").strip()
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36",
    "Accept": "application/json",
}

BOM_STATIONS = {
    "wedding_cake": ("W Wedding Cake", "http://www.bom.gov.au/fwo/IDN60901/IDN60901.95766.json"),
    "fort_denison": ("Fort Denison", "http://www.bom.gov.au/fwo/IDN60901/IDN60901.95765.json"),
    "north_head": ("North Head", "http://www.bom.gov.au/fwo/IDN60901/IDN60901.95768.json"),
    "obs_hill": ("Observatory Hill", "http://www.bom.gov.au/fwo/IDN60901/IDN60901.94768.json"),
    "kurnell": ("Kurnell (Botany)", "http://www.bom.gov.au/fwo/IDN60901/IDN60901.95756.json"),
    "syd_airport": ("Airport Runway", "http://www.bom.gov.au/fwo/IDN60901/IDN60901.94767.json"),
    "wattamolla": ("Wattamolla", "http://www.bom.gov.au/fwo/IDN60901/IDN60901.95752.json"),
    "bellambi": ("Bellambi Point", "http://www.bom.gov.au/fwo/IDN60901/IDN60901.94749.json"),
}

CARDINAL_TO_DEG = {
    "N": 0, "NNE": 22.5, "NE": 45, "ENE": 67.5,
    "E": 90, "ESE": 112.5, "SE": 135, "SSE": 157.5,
    "S": 180, "SSW": 202.5, "SW": 225, "WSW": 247.5,
    "W": 270, "WNW": 292.5, "NW": 315, "NNW": 337.5,
}

def compass(deg):
    try:
        d = ["N","NNE","NE","ENE","E","ESE","SE","SSE","S","SSW","SW","WSW","W","WNW","NW","NNW"]
        return d[int((float(deg) % 360 + 11.25) // 22.5) % 16]
    except Exception:
        return "--"

def fnum(v, n=1):
    try:
        return f"{float(v):.{n}f}" if v not in (None, "", "--", "-") else "--"
    except Exception:
        return "--"

def fetch_bom(label, url):
    out = {"name": label, "speed_kts": "--", "gust_kts": "--", "dir_deg": "--", "dir_cardinal": "--"}
    for _ in range(3):
        try:
            r = requests.get(url, headers=HEADERS, timeout=10)
            if not r.ok:
                continue
            rows = r.json().get("observations", {}).get("data", [])
            if not rows:
                return out
            latest = rows[0]
            spd = latest.get("wind_spd_kt")
            gst = latest.get("gust_kt")
            card = str(latest.get("wind_dir") or "--").strip().upper()
            deg = CARDINAL_TO_DEG.get(card, "--")
            if deg != "--":
                deg = int(round(deg))
            return {
                "name": label,
                "speed_kts": fnum(spd, 1),
                "gust_kts": fnum(gst, 1) if gst not in (None, "-", "") else fnum(spd, 1),
                "dir_deg": deg,
                "dir_cardinal": card if card in CARDINAL_TO_DEG else "--",
            }
        except Exception:
            pass
    return out

def ww_search_id(query_text):
    if not WW_KEY:
        return None
    try:
        url = f"https://api.willyweather.com.au/v2/{WW_KEY}/search.json?query={requests.utils.quote(query_text)}&limit=5"
        r = requests.get(url, headers=HEADERS, timeout=10)
        if r.ok:
            results = r.json()
            if isinstance(results, list):
                for item in results:
                    if item.get("state") == "NSW":
                        return item.get("id")
                if results:
                    return results[0].get("id")
    except Exception:
        pass
    return None

def fetch_ww_swell(label, query_name):
    out = {"name": label, "hs_m": "--", "hmax_m": "--", "tp_s": "--", "dir_deg": "--", "dir_cardinal": "--"}
    loc_id = ww_search_id(query_name)
    if not loc_id:
        return out
    try:
        url = (
            f"https://api.willyweather.com.au/v2/{WW_KEY}/locations/{loc_id}/weather.json"
            f"?forecasts=swell&days=1&units=height:m"
        )
        r = requests.get(url, headers=HEADERS, timeout=10)
        if not r.ok:
            return out
        days = r.json().get("forecasts", {}).get("swell", {}).get("days", [])
        if not days:
            return out
        entries = days[0].get("entries", [])
        if not entries:
            return out

        now_naive = datetime.now(TZ).replace(tzinfo=None)
        best = min(
            entries,
            key=lambda e: abs((datetime.strptime(e["dateTime"], "%Y-%m-%d %H:%M:%S") - now_naive).total_seconds())
        )

        hs = best.get("height")
        tp = best.get("period")
