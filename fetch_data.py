#!/usr/bin/env python3
"""
fetch_data.py
Lightweight direct-API marine conditions fetcher for Sydney Harbour & Botany Bay.
"""

import json
import re
from datetime import datetime
from zoneinfo import ZoneInfo
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

SYDNEY_TZ = ZoneInfo("Australia/Sydney")
TIMEOUT_SECONDS = 10

PANSW_BASE = "https://webservices.portauthoritynsw.com.au/api"
CANDIDATE_URLS = {
    "wind_all": f"{PANSW_BASE}/EnvironmentWind",
    "wind_syd": f"{PANSW_BASE}/EnvironmentWind?Code=SYD",
    "wind_bot": f"{PANSW_BASE}/EnvironmentWind?Code=BOT",
    "wave_all": f"{PANSW_BASE}/EnvironmentWave",
    "wave_syd": f"{PANSW_BASE}/EnvironmentWave?Code=SYD",
    "wave_bot": f"{PANSW_BASE}/EnvironmentWave?Code=BOT",
    "tide_all": f"{PANSW_BASE}/EnvironmentTide",
    "tide_syd": f"{PANSW_BASE}/EnvironmentTide?Code=SYD",
    "tide_bot": f"{PANSW_BASE}/EnvironmentTide?Code=BOT",
    "summary_syd": f"{PANSW_BASE}/EnvironmentWeatherSummary/SYD",
    "summary_bot": f"{PANSW_BASE}/EnvironmentWeatherSummary/BOT",
}

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
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://wavewindtide.portauthoritynsw.com.au/",
        "Origin": "https://wavewindtide.portauthoritynsw.com.au",
    })
    return session


def fetch_probe(session: requests.Session, url: str, debug_log: dict, key: str):
    try:
        resp = session.get(url, timeout=TIMEOUT_SECONDS)
        snippet = resp.text[:400].replace("\n", " ")
        debug_log[key] = {"status": resp.status_code, "sample": snippet}
        if resp.ok:
            return resp.json()
    except Exception as exc:
        debug_log[key] = {"error": str(exc)}
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
        return f"{float(val):.{decimals}f}"
    except (ValueError, TypeError):
        return "--"


def fmt_deg(val):
    if val is None or val == "" or val == "--":
        return "--"
    try:
        return int(round(float(val))) % 360
    except (ValueError, TypeError):
        return "--"


def get_first_key(item: dict, keys: list, default=None):
    if not isinstance(item, dict):
        return default
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
        for key in ("data", "Data", "Items", "items", "Result", "results", "Wind", "Winds", "Wave", "Waves", "Tide", "Tides"):
            if isinstance(payload.get(key), list):
                return payload[key]
        return [payload]
    return []


def extract_wind_station(records: list, label: str, match_terms: list) -> dict:
    fallback = {
        "name": label,
        "speed_kts": "--",
        "gust_kts": "--",
        "dir_deg
