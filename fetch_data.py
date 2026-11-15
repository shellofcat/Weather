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

def ww_find_location(lat, lon):
    if not WW_KEY:
        return None
    try:
        url = f"https://api.willyweather.com.au/v2/{WW_KEY}/search.json?lat={lat}&lng={lon}&range=20&units=distance:km"
        r = requests.get(url, headers=HEADERS, timeout=10)
        if r.ok:
            data = r.json()
            if isinstance(data, dict) and data.get("location"):
                return data["location"].get("id")
            if isinstance(data, list) and data:
                return data[0].get("id")
    except Exception:
        pass
    return None

def fetch_ww_swell(label, lat, lon):
    out = {"name": label, "hs_m": "--", "hmax_m": "--", "tp_s": "--", "dir_deg": "--", "dir_cardinal": "--"}
    loc_id = ww_find_location(lat, lon)
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
        best = entries[0]
        min_diff = 999999
        for e in entries:
            dt = datetime.strptime(e["dateTime"], "%Y-%m-%d %H:%M:%S")
            diff = abs((dt - now_naive).total_seconds())
            if diff < min_diff:
                min_diff = diff
                best = e

        hs = best.get("height")
        tp = best.get("period")
        dr = best.get("direction")
        card = best.get("directionText") or compass(dr)
        deg = int(round(float(dr))) % 360 if dr is not None else "--"
        hmax = float(hs) * 1.67 if hs is not None else None

        return {
            "name": label,
            "hs_m": fnum(hs, 2),
            "hmax_m": fnum(hmax, 2),
            "tp_s": fnum(tp, 1),
            "dir_deg": deg,
            "dir_cardinal": str(card).upper() if card else compass(deg),
        }
    except Exception:
        return out

def fetch_ww_tides():
    default_out = {
        "sydney_live_m": "--",
        "botany_live_m": "--",
        "events": [
            {"type": "H", "time": "--", "height_m": "--"},
            {"type": "L", "time": "--", "height_m": "--"},
            {"type": "H", "time": "--", "height_m": "--"},
        ],
    }
    # Fort Denison coordinates
    loc_id = ww_find_location(-33.8547, 151.2253)
    if not loc_id:
        return default_out
    try:
        url = (
            f"https://api.willyweather.com.au/v2/{WW_KEY}/locations/{loc_id}/weather.json"
            f"?forecasts=tides&days=2&units=height:m"
        )
        r = requests.get(url, headers=HEADERS, timeout=10)
        if not r.ok:
            return default_out
        days = r.json().get("forecasts", {}).get("tides", {}).get("days", [])
        all_entries = []
        for d in days:
            for e in d.get("entries", []):
                dt = datetime.strptime(e["dateTime"], "%Y-%m-%d %H:%M:%S")
                all_entries.append({
                    "dt": dt,
                    "type": "H" if e.get("type") == "high" else "L",
                    "height": float(e["height"]),
                })

        now_naive = datetime.now(TZ).replace(tzinfo=None)
        upcoming = [e for e in all_entries if e["dt"] >= now_naive - timedelta(minutes=15)]

        # Cosine-interpolate current live tide height between surrounding high & low
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
            {
                "type": e["type"],
                "time": e["dt"].strftime("%-I:%M%p").lower(),
                "height_m": f"{e['height']:.2f}",
            }
            for e in upcoming[:3]
        ]

        return {
            "sydney_live_m": live_str,
            "botany_live_m": live_str,
            "events": events if events else default_out["events"],
        }
    except Exception:
        return default_out

def main():
    now = datetime.now(TZ)

    syd_winds = [
        fetch_bom(*BOM_STATIONS["wedding_cake"]),
        fetch_bom(*BOM_STATIONS["fort_denison"]),
        fetch_bom(*BOM_STATIONS["north_head"]),
        fetch_bom(*BOM_STATIONS["obs_hill"]),
    ]

    bot_winds = [
        fetch_bom(*BOM_STATIONS["kurnell"]),
        fetch_bom(*BOM_STATIONS["syd_airport"]),
        fetch_bom(*BOM_STATIONS["wattamolla"]),
        fetch_bom(*BOM_STATIONS["bellambi"]),
    ]

    syd_swell = fetch_ww_swell("Sydney Offshore (Long Reef)", -33.745, 151.345)
    bot_swell = fetch_ww_swell("Botany Offshore", -34.015, 151.255)
    tides = fetch_ww_tides()

    payload = {
        "updated_iso": now.isoformat(),
        "updated_display": now.strftime("%-d %b %Y · %-I:%M %p %Z"),
        "timezone": now.tzname() or "AEDT",
        "tides": tides,
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
