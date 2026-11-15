#!/usr/bin/env python3
"""
fetch_data.py
Lightweight direct-API marine conditions fetcher for Sydney Harbour & Botany Bay.
No headless browsers. 10s timeout, 3 retries, per-sensor fault isolation.
"""

import json
import os
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

SYDNEY_TZ = ZoneInfo("Australia/Sydney")
TIMEOUT_SECONDS = 10

PANSW_BASE = "https://webservices.portauthoritynsw.com.au/api"
ENDPOINTS = {
    "wind": f"{PANSW_BASE}/EnvironmentWind",
    "wave": f"{PANSW_BASE}/EnvironmentWave",
    "tide": f"{PANSW_BASE}/EnvironmentTide",
    "weather_syd": f"{PANSW_BASE}/EnvironmentWeatherSummary/SYD",
    "weather_bot": f"{PANSW_BASE}/EnvironmentWeatherSummary/BOT",
}

# MHL Sydney Offshore Deepwater Waverider (Long Reef ~90m depth, station SYDDOW)
MHL_SYDDOW_URLS = [
    "https://www.mhl.nsw.gov.au/Station-SYDDOW",
    "https://www.mhl.nsw.gov.au/Data-Wave",
]


def create_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=3,
        read=3,
        connect=3,
        backoff_factor=1.0,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET"]),
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update({
        "User-Agent": "SydneyMarineWidget/1.0 (+https://github.com/sammyb2113-sys/Wind)",
        "Accept": "application/json, text/plain, */*",
    })
    return session


def fetch_json(session: requests.Session, url: str):
    try:
        resp = session.get(url, timeout=TIMEOUT_SECONDS)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        print(f"[WARN] Failed JSON fetch {url}: {exc}")
        return None


def deg_to_compass(deg_val) -> str:
    try:
        deg = float(deg_val) % 360
        dirs = [
            "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
            "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"
        ]
        return dirs[int((deg + 11.25) // 22.5) % 16]
    except (ValueError, TypeError):
        return "--"


def fmt_num(val, decimals=1) -> str:
    if val is None or val == "" or val == "--":
        return "--"
    try:
        num = float(val)
        return f"{num:.{decimals}f}"
    except (ValueError, TypeError):
        return "--"


def fmt_deg(val) -> int | str:
    if val is None or val == "" or val == "--":
        return "--"
    try:
        return int(round(float(val))) % 360
    except (ValueError, TypeError):
        return "--"


def get_first_key(item: dict, keys: list, default=None):
    if not isinstance(item, dict):
        return default
    # Case-insensitive lookup fallback
    lower_map = {k.lower(): v for k, v in item.items()}
    for k in keys:
        if k in item and item[k] is not None:
            return item[k]
        if k.lower() in lower_map and lower_map[k.lower()] is not None:
            return lower_map[k.lower()]
    return default


def normalize_list(payload) -> list:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("data", "Data", "Items", "items", "Result", "results", "Wind", "Wave", "Tide"):
            if isinstance(payload.get(key), list):
                return payload[key]
        return [payload]
    return []


def extract_wind_station(records: list, label: str, match_terms: list) -> dict:
    fallback = {
        "name": label,
        "speed_kts": "--",
        "gust_kts": "--",
        "dir_deg": "--",
        "dir_cardinal": "--",
        "updated": "--",
    }
    try:
        matched = None
        for rec in records:
            station_str = " ".join(
                str(get_first_key(rec, ["Location", "Name", "StationName", "SiteName", "Code", "Title", "Description"], ""))
                for _ in (1,)
            ).lower()
            if any(term.lower() in station_str for term in match_terms):
                matched = rec
                break

        if not matched:
            return fallback

        spd = get_first_key(matched, [
            "WindSpeed", "AverageWindSpeed", "Speed", "AvgSpeed", "WindSpeedKnots", "SpeedKnots", "Value"
        ])
        gst = get_first_key(matched, [
            "WindGust", "GustSpeed", "Gust", "MaxWindSpeed", "WindGustKnots", "GustKnots"
        ])
        deg = get_first_key(matched, [
            "WindDirection", "Direction", "DirDegrees", "WindDirectionDegrees", "Bearing"
        ])
        card = get_first_key(matched, [
            "WindDirectionCardinal", "CardinalDirection", "CompassDirection", "DirectionCardinal"
        ])
        ts = get_first_key(matched, ["DateTime", "Timestamp", "LastUpdate", "DataDate", "ReadingTime"])

        deg_clean = fmt_deg(deg)
        card_clean = str(card).strip().upper() if card and str(card).strip().isalpha() else deg_to_compass(deg_clean)

        return {
            "name": label,
            "speed_kts": fmt_num(spd, 1),
            "gust_kts": fmt_num(gst, 1),
            "dir_deg": deg_clean,
            "dir_cardinal": card_clean if card_clean != "--" else deg_to_compass(deg_clean),
            "updated": str(ts) if ts else "--",
        }
    except Exception as exc:
        print(f"[WARN] Wind sensor error ({label}): {exc}")
        return fallback


def fetch_mhl_syddow_fallback(session: requests.Session) -> dict | None:
    """
    Scrapes embedded JSON series or latest metrics from MHL's SYDDOW page if PANSW
    only exposes the sheltered Sydney Entrance / Heads buoy.
    """
    for url in MHL_SYDDOW_URLS:
        try:
            resp = session.get(url, timeout=TIMEOUT_SECONDS)
            if not resp.ok:
                continue
            html = resp.text

            # Look for Hs, Hmax, Tp1, Direction in embedded Highcharts/JSON data on MHL page
            hs_match = re.search(r'(?:Hs|Significant Wave Height)[^0-9]*([0-9]+\.[0-9]+)', html, re.I)
            hmax_match = re.search(r'(?:Hmax|Maximum Wave Height)[^0-9]*([0-9]+\.[0-9]+)', html, re.I)
            tp_match = re.search(r'(?:TP1|Peak Period|Wave Period)[^0-9]*([0-9]+\.[0-9]+)', html, re.I)
            dir_match = re.search(r'(?:Wave Direction|Mean Direction)[^0-9]*([0-9]{1,3}(?:\.[0-9]+)?)', html, re.I)

            if hs_match:
                deg_val = fmt_deg(dir_match.group(1)) if dir_match else "--"
                return {
                    "name": "Sydney Offshore (MHL Long Reef)",
                    "hs_m": fmt_num(hs_match.group(1), 2),
                    "hmax_m": fmt_num(hmax_match.group(1), 2) if hmax_match else "--",
                    "tp_s": fmt_num(tp_match.group(1), 1) if tp_match else "--",
                    "dir_deg": deg_val,
                    "dir_cardinal": deg_to_compass(deg_val),
                    "source": "MHL SYDDOW",
                }
        except Exception as exc:
            print(f"[WARN] MHL SYDDOW fallback attempt failed ({url}): {exc}")
    return None


def extract_offshore_swell(wave_records: list, session: requests.Session, target: str) -> dict:
    """
    target: 'sydney' or 'botany'
    Explicitly rejects sheltered 'Entrance' or 'Heads' buoys when searching for Sydney Offshore.
    """
    label = "Sydney Offshore (Long Reef)" if target == "sydney" else "Botany Offshore"
    fallback = {
        "name": label,
        "hs_m": "--",
        "hmax_m": "--",
        "tp_s": "--",
        "dir_deg": "--",
        "dir_cardinal": "--",
        "source": "--",
    }

    try:
        matched = None
        for rec in wave_records:
            loc = str(get_first_key(rec, [
                "Location", "Name", "StationName", "SiteName", "Code", "Title", "Description"
            ], "")).lower()

            if target == "sydney":
                # Reject sheltered Heads / Entrance Channel buoy
                if any(bad in loc for bad in ["entrance", "channel", "heads", "inner", "harbour"]):
                    continue
                if any(good in loc for good in ["sydney offshore", "long reef", "syddow", "mhl sydney", "offshore sydney"]):
                    matched = rec
                    break
            elif target == "botany":
                if any(good in loc for good in ["botany", "port botany", "botdow", "molineaux", "offshore"]):
                    if "sydney" not in loc:
                        matched = rec
                        break

        # If Sydney Offshore wasn't in PANSW (or only Sydney Entrance was), pull MHL SYDDOW directly
        if not matched and target == "sydney":
            mhl_data = fetch_mhl_syddow_fallback(session)
            if mhl_data:
                return mhl_data
            return fallback

        if not matched:
            return fallback

        hs = get_first_key(matched, ["Hs", "SignificantWaveHeight", "SigWaveHeight", "Hsig", "WaveHeight", "Value"])
        hmax = get_first_key(matched, ["Hmax", "MaxWaveHeight", "MaximumWaveHeight", "WaveHeightMax"])
        tp = get_first_key(matched, ["Tp", "TP1", "PeakPeriod", "WavePeriod", "Period", "Tz", "ZeroCrossingPeriod"])
        deg = get_first_key(matched, ["WaveDirection", "Direction", "SwellDirection", "DirDegrees", "PeakDirection"])
        card = get_first_key(matched, ["WaveDirectionCardinal", "CardinalDirection", "CompassDirection"])

        deg_clean = fmt_deg(deg)
        card_clean = str(card).strip().upper() if card and str(card).strip().isalpha() else deg_to_compass(deg_clean)

        return {
            "name": label,
            "hs_m": fmt_num(hs, 2),
            "hmax_m": fmt_num(hmax, 2),
            "tp_s": fmt_num(tp, 1),
            "dir_deg": deg_clean,
            "dir_cardinal": card_clean if card_clean != "--" else deg_to_compass(deg_clean),
            "source": "PANSW/MHL",
        }
    except Exception as exc:
        print(f"[WARN] Wave sensor error ({label}): {exc}")
        return fallback


def extract_tides(session: requests.Session, tide_records: list) -> dict:
    """
    Extracts live gauge height + upcoming High/Low tide schedule for Fort Denison & Botany Bay.
    """
    default_tide = {
        "live_height_m": "--",
        "station": "Fort Denison / Botany",
        "events": [
            {"type": "H", "time": "--", "height_m": "--"},
            {"type": "L", "time": "--", "height_m": "--"},
            {"type": "H", "time": "--", "height_m": "--"},
            {"type": "L", "time": "--", "height_m": "--"},
        ],
    }

    try:
        live_syd = "--"
        live_bot = "--"
        events = []

        for rec in tide_records:
            loc = str(get_first_key(rec, ["Location", "Name", "StationName", "Code"], "")).lower()
            val = get_first_key(rec, ["TideHeight", "Height", "WaterLevel", "Level", "Value", "CurrentTide"])
            if ("denison" in loc or "sydney" in loc or "syd" in loc) and live_syd == "--":
                live_syd = fmt_num(val, 2)
            elif ("botany" in loc or "pilot" in loc or "bot" in loc) and live_bot == "--":
                live_bot = fmt_num(val, 2)

            # Check if embedded high/low predictions exist on the tide record
            for subkey in ("TideEvents", "Predictions", "HighLow", "Extrema", "Details", "TideDetail"):
                sub = rec.get(subkey)
                if isinstance(sub, list):
                    for ev in sub:
                        t_type = str(get_first_key(ev, ["Type", "TideType", "Event", "State"], "")).upper()
                        t_time = get_first_key(ev, ["Time", "DateTime", "EventTime", "TideTime"])
                        t_ht = get_first_key(ev, ["Height", "TideHeight", "Value", "Level"])
                        if t_time and t_ht is not None:
                            events.append({
                                "type": "H" if "H" in t_type else "L",
                                "time": format_tide_time(t_time),
                                "height_m": fmt_num(t_ht, 2),
                            })

        # Query EnvironmentTideDetailDay / EnvironmentTideDetail if events list is still empty
        if not events:
            now_syd = datetime.now(SYDNEY_TZ)
            date_str = now_syd.strftime("%Y-%m-%d")
            detail_urls = [
                f"{PANSW_BASE}/EnvironmentTideDetail?Code=SYD",
                f"{PANSW_BASE}/EnvironmentTideDetailDay/SYD/{date_str}",
                f"{PANSW_BASE}/EnvironmentTideDetail?Code=FortDenison",
            ]
            for d_url in detail_urls:
                d_json = fetch_json(session, d_url)
                d_list = normalize_list(d_json)
                if d_list:
                    for ev in d_list:
                        t_type = str(get_first_key(ev, ["Type", "TideType", "Event", "HighLow", "Description"], "")).upper()
                        t_time = get_first_key(ev, ["Time", "DateTime", "TideTime", "DataDate"])
                        t_ht = get_first_key(ev, ["Height", "TideHeight", "Value", "Prediction"])
                        if t_type in ("H", "L", "HIGH", "LOW") and t_time:
                            events.append({
                                "type": "H" if t_type.startswith("H") else "L",
                                "time": format_tide_time(t_time),
                                "height_m": fmt_num(t_ht, 2),
                            })
                    if events:
                        break

        return {
            "sydney_live_m": live_syd,
            "botany_live_m": live_bot,
            "events": events[:4] if events else default_tide["events"],
        }
    except Exception as exc:
        print(f"[WARN] Tide extraction error: {exc}")
        return {
            "sydney_live_m": "--",
            "botany_live_m": "--",
            "events": default_tide["events"],
        }


def format_tide_time(raw_time) -> str:
    raw_str = str(raw_time).strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%d/%m/%Y %H:%M", "%H:%M:%S", "%H:%M"):
        try:
            dt = datetime.strptime(raw_str[:19], fmt)
            return dt.strftime("%-I:%M%p").lower()
        except ValueError:
            continue
    return raw_str


def main():
    session = create_session()
    now_syd = datetime.now(SYDNEY_TZ)

    wind_raw = normalize_list(fetch_json(session, ENDPOINTS["wind"]))
    wave_raw = normalize_list(fetch_json(session, ENDPOINTS["wave"]))
    tide_raw = normalize_list(fetch_json(session, ENDPOINTS["tide"]))

    # Also merge summary endpoints if primary list is sparse
    for extra_key in ("weather_syd", "weather_bot"):
        extra = fetch_json(session, ENDPOINTS[extra_key])
        if isinstance(extra, dict):
            wind_raw.extend(normalize_list(extra.get("Wind") or extra.get("Winds") or []))
            wave_raw.extend(normalize_list(extra.get("Wave") or extra.get("Waves") or []))
            tide_raw.extend(normalize_list(extra.get("Tide") or extra.get("Tides") or []))

    # 1. Sydney Harbour Winds (4 spread-out stations)
    sydney_winds = [
        extract_wind_station(wind_raw, "W Wedding Cake", ["wedding cake", "wedding", "wwc"]),
        extract_wind_station(wind_raw, "Fort Denison", ["fort denison", "denison", "ft denison"]),
        extract_wind_station(wind_raw, "Manns Point", ["manns point", "manns", "greenwich"]),
        extract_wind_station(wind_raw, "Glebe Island", ["glebe island", "glebe", "white bay", "rozelle"]),
    ]

    # 2. Botany Bay Winds (4 spread-out stations)
    botany_winds = [
        extract_wind_station(wind_raw, "Molineaux Point", ["molineaux", "molineux", "port botany entrance"]),
        extract_wind_station(wind_raw, "Ampol Wharf", ["ampol", "caltex", "kurnell"]),
        extract_wind_station(wind_raw, "Airport Runway", ["airport", "runway", "kingsford", "kurnell runway"]),
        extract_wind_station(wind_raw, "Brotherson Dock", ["brotherson", "bulk liquids", "botany", "channel"]),
    ]

    # 3. True Offshore Swell
    sydney_swell = extract_offshore_swell(wave_raw, session, target="sydney")
    botany_swell = extract_offshore_swell(wave_raw, session, target="botany")

    # 4. Tides
    tides = extract_tides(session, tide_raw)

    payload = {
        "updated_iso": now_syd.isoformat(),
        "updated_display": now_syd.strftime("%-d %b %Y · %-I:%M %p %Z"),
        "timezone": now_syd.tzname() or "AEDT",
        "tides": tides,
        "sydney": {
            "title": "SYDNEY HARBOUR",
            "subtitle": "Port Jackson · 4 Stations",
            "winds": sydney_winds,
            "swell": sydney_swell,
        },
        "botany": {
            "title": "BOTANY BAY",
            "subtitle": "Port Botany · 4 Stations",
            "winds": botany_winds,
            "swell": botany_swell,
        },
    }

    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)

    print(f"[OK] Wrote data.json at {payload['updated_display']}")


if __name__ == "__main__":
    main()
