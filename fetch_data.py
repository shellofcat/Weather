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
    "obs_hill": ("Obs Hill", "http://www.bom.gov.au/fwo/IDN60901/IDN60901.94768.json"),
    "kurnell": ("Kurnell", "http://www.bom.gov.au/fwo/IDN60901/IDN60901.95756.json"),
    "syd_airport": ("Airport", "http://www.bom.gov.au/fwo/IDN60901/IDN60901.94767.json"),
    "wattamolla": ("Wattamolla", "http://www.bom.gov.au/fwo/IDN60901/IDN60901.95752.json"),
    "bellambi": ("Bellambi", "http://www.bom.gov.au/fwo/IDN60901/IDN60901.94749.json"),
}

# Direct WillyWeather Location IDs (bypasses search.json completely)
WW_LOCS = {
    "fort_denison": [16931, 5247],   # Fort Denison / Sydney Harbour
    "syd_offshore": [5231, 5247],    # Long Reef / Dee Why / Sydney
    "bot_offshore": [5237, 5241],    # Kurnell / Botany Bay
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

def fetch_swell(label, loc_ids, lat, lon):
    if WW_KEY:
        for loc_id in loc_ids:
            try:
                url = f"https://api.willyweather.com.au/v2/{WW_KEY}/locations/{loc_id}/weather.json?forecasts=swell&days=1&units=height:m"
                r = requests.get(url, headers=HEADERS, timeout=8)
                if r.ok:
                    days = r.json().get("forecasts", {}).get("swell", {}).get("days", [])
                    if days and days[0].get("entries"):
                        now_naive = datetime.now(TZ).replace(tzinfo=None)
                        best = min(
                            days[0]["entries"],
                            key=lambda e: abs((datetime.strptime(e["dateTime"], "%Y-%m-%d %H:%M:%S") - now_naive).total_seconds())
                        )
                        hs = best.get("height")
                        if hs is not None:
                            deg = int(round(float(best.get("direction", 0)))) % 360
                            return {
                                "name": label,
                                "hs_m": fnum(hs, 2),
                                "hmax_m": fnum(float(hs) * 1.67, 2),
                                "tp_s": fnum(best.get("period"), 1),
                                "dir_deg": deg,
                                "dir_cardinal": str(best.get("directionText") or compass(deg)).upper(),
                            }
            except Exception:
                pass

    # Guaranteed Open-Meteo Marine fallback
    try:
        url = (
            f"https://marine-api.open-meteo.com/v1/marine?latitude={lat}&longitude={lon}"
            f"&current=wave_height,wave_direction,wave_period&timezone=Australia%2FSydney"
        )
        r = requests.get(url, headers=HEADERS, timeout=10)
        if r.ok:
            cur = r.json().get("current", {})
            hs = cur.get("wave_height")
            if hs is not None:
                dr = cur.get("wave_direction")
                deg = int(round(float(dr))) % 360 if dr is not None else "--"
                return {
                    "name": label,
                    "hs_m": fnum(hs, 2),
                    "hmax_m": fnum(float(hs) * 1.67, 2),
                    "tp_s": fnum(cur.get("wave_period"), 1),
                    "dir_deg": deg,
                    "dir_cardinal": compass(deg),
                }
    except Exception:
        pass

    return {"name": label, "hs_m": "--", "hmax_m": "--", "tp_s": "--", "dir_deg": "--", "dir_cardinal": "--"}

def fetch_tides():
    now_naive = datetime.now(TZ).replace(tzinfo=None)

    if WW_KEY:
        for loc_id in WW_LOCS["fort_denison"]:
            try:
                url = f"https://api.willyweather.com.au/v2/{WW_KEY}/locations/{loc_id}/weather.json?forecasts=tides&days=2&units=height:m"
                r = requests.get(url, headers=HEADERS, timeout=8)
                if r.ok:
                    days = r.json().get("forecasts", {}).get("tides", {}).get("days", [])
                    all_entries = []
                    for d in days:
                        for e in d.get("entries", []):
                            all_entries.append({
                                "dt": datetime.strptime(e["dateTime"], "%Y-%m-%d %H:%M:%S"),
                                "type": "H" if e.get("type") == "high" else "L",
                                "height": float(e["height"]),
                            })
                    if all_entries:
                        upcoming = [e for e in all_entries if e["dt"] >= now_naive - timedelta(minutes=15)]
                        live_str = "--"
                        past = [e for e in all_entries if e["dt"] <= now_naive]
                        future = [e for e in all_entries if e["dt"] > now_naive]
                        if past and future:
                            t0, h0 = past[-1]["dt"], past[-1]["height"]
                            t1, h1 = future[0]["dt"], future[0]["height"]
                            span = (t1 - t0).total_seconds()
                            if span > 0:
                                frac = (now_naive - t0).total_seconds() / span
                                cur_h = h0 + (h1 - h0) * (1 - math.cos(math.pi * frac)) / 2
                                live_str = f"{cur_h:.2f}"
                        events = [
                            {"type": e["type"], "time": e["dt"].strftime("%-I:%M%p").lower(), "height_m": f"{e['height']:.2f}"}
                            for e in upcoming[:2]
                        ]
                        if events:
                            return {"sydney_live_m": live_str, "botany_live_m": live_str, "events": events}
            except Exception:
                pass

    # Guaranteed Open-Meteo Sea Level (Chart Datum +0.93m) fallback
    try:
        url = (
            "https://marine-api.open-meteo.com/v1/marine?latitude=-33.8547&longitude=151.2253"
            "&hourly=sea_level_height_msl&current=sea_level_height_msl&forecast_days=2&timezone=Australia%2FSydney"
        )
        r = requests.get(url, headers=HEADERS, timeout=10)
        if r.ok:
            data = r.json()
            cur_msl = data.get("current", {}).get("sea_level_height_msl")
            live_cd = fnum(float(cur_msl) + 0.93, 2) if cur_msl is not None else "--"
            times = data.get("hourly", {}).get("time", [])
            heights = data.get("hourly", {}).get("sea_level_height_msl", [])
            events = []
            for i in range(1, len(heights) - 1):
                if None in (heights[i - 1], heights[i], heights[i + 1]):
                    continue
                t_dt = datetime.fromisoformat(times[i])
                if t_dt < now_naive - timedelta(minutes=30):
                    continue
                if heights[i] >= heights[i - 1] and heights[i] > heights[i + 1]:
                    events.append({"type": "H", "time": t_dt.strftime("%-I:%M%p").lower(), "height_m": fnum(heights[i] + 0.93, 2)})
                elif heights[i] <= heights[i - 1] and heights[i] < heights[i + 1]:
                    events.append({"type": "L", "time": t_dt.strftime("%-I:%M%p").lower(), "height_m": fnum(heights[i] + 0.93, 2)})
                if len(events) >= 2:
                    break
            return {"sydney_live_m": live_cd, "botany_live_m": live_cd, "events": events}
    except Exception:
        pass

    return {
        "sydney_live_m": "--",
        "botany_live_m": "--",
        "events": [{"type": "H", "time": "--", "height_m": "--"}, {"type": "L", "time": "--", "height_m": "--"}],
    }

def main():
    now = datetime.now(TZ)
    payload = {
        "updated_iso": now.isoformat(),
        "updated_display": now.strftime("%-I:%M %p %Z"),
        "timezone": now.tzname() or "AEDT",
        "tides": fetch_tides(),
        "sydney": {
            "title": "SYDNEY HARBOUR",
            "winds": [
                fetch_bom(*BOM_STATIONS["wedding_cake"]),
                fetch_bom(*BOM_STATIONS["fort_denison"]),
                fetch_bom(*BOM_STATIONS["north_head"]),
                fetch_bom(*BOM_STATIONS["obs_hill"]),
            ],
            "swell": fetch_swell("Sydney Offshore (Long Reef)", WW_LOCS["syd_offshore"], -33.745, 151.345),
        },
        "botany": {
            "title": "BOTANY BAY",
            "winds": [
                fetch_bom(*BOM_STATIONS["kurnell"]),
                fetch_bom(*BOM_STATIONS["syd_airport"]),
                fetch_bom(*BOM_STATIONS["wattamolla"]),
                fetch_bom(*BOM_STATIONS["bellambi"]),
            ],
            "swell": fetch_swell("Botany Offshore", WW_LOCS["bot_offshore"], -34.015, 151.255),
        },
    }
    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)

if __name__ == "__main__":
    main()
