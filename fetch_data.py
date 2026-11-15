import json, re
from datetime import datetime
from zoneinfo import ZoneInfo
import requests

TZ = ZoneInfo("Australia/Sydney")
BASE = "https://webservices.portauthoritynsw.com.au/api"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://wavewindtide.portauthoritynsw.com.au/",
}

URLS = {
    "wind_all": f"{BASE}/EnvironmentWind",
    "wind_syd": f"{BASE}/EnvironmentWind?Code=SYD",
    "wind_bot": f"{BASE}/EnvironmentWind?Code=BOT",
    "wave_all": f"{BASE}/EnvironmentWave",
    "wave_syd": f"{BASE}/EnvironmentWave?Code=SYD",
    "wave_bot": f"{BASE}/EnvironmentWave?Code=BOT",
    "tide_all": f"{BASE}/EnvironmentTide",
    "tide_syd": f"{BASE}/EnvironmentTide?Code=SYD",
    "summary_syd": f"{BASE}/EnvironmentWeatherSummary/SYD",
    "summary_bot": f"{BASE}/EnvironmentWeatherSummary/BOT",
}

def probe(url, dbg, key):
    for _ in range(3):
        try:
            r = requests.get(url, headers=HEADERS, timeout=10)
            dbg[key] = {"status": r.status_code, "sample": r.text[:350].replace("\n", " ")}
            if r.ok:
                return r.json()
            break
        except Exception as e:
            dbg[key] = {"error": str(e)}
    return None

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

def gkey(item, keys):
    if not isinstance(item, dict):
        return None
    lm = {k.lower(): v for k, v in item.items()}
    for k in keys:
        if item.get(k) is not None:
            return item[k]
        if lm.get(k.lower()) is not None:
            return lm[k.lower()]
    return None

def nlist(p):
    if isinstance(p, list):
        return p
    if isinstance(p, dict):
        for k in ("data","Data","Items","items","Result","results","Wind","Winds","Wave","Waves","Tide","Tides"):
            if isinstance(p.get(k), list):
                return p[k]
        return [p]
    return []

def get_wind(recs, label, terms):
    out = {"name": label, "speed_kts": "--", "gust_kts": "--", "dir_deg": "--", "dir_cardinal": "--", "updated": "--"}
    for r in recs:
        if not isinstance(r, dict):
            continue
        txt = " ".join(str(v) for k, v in r.items() if any(x in k.lower() for x in ("loc","name","site","station","code","title","desc"))).lower()
        if any(t in txt for t in terms):
            spd = gkey(r, ["WindSpeed","AverageWindSpeed","Speed","AvgSpeed","WindSpeedKnots","SpeedKnots","Value","Knots"])
            gst = gkey(r, ["WindGust","GustSpeed","Gust","MaxWindSpeed","WindGustKnots","GustKnots","MaxGust"])
            deg = gkey(r, ["WindDirection","Direction","DirDegrees","WindDirectionDegrees","Bearing","Dir"])
            card = gkey(r, ["WindDirectionCardinal","CardinalDirection","CompassDirection","DirectionCardinal","Cardinal"])
            d_clean = fdeg(deg)
            c_clean = str(card).strip().upper() if card and str(card).strip().isalpha() else compass(d_clean)
            return {
                "name": label,
                "speed_kts": fnum(spd, 1),
                "gust_kts": fnum(gst, 1),
                "dir_deg": d_clean,
                "dir_cardinal": c_clean if c_clean != "--" else compass(d_clean),
                "updated": str(gkey(r, ["DateTime","Timestamp","LastUpdate","DataDate"]) or "--"),
            }
    return out

def get_mhl(dbg):
    for u in ("https://www.mhl.nsw.gov.au/Station-SYDDOW", "https://www.mhl.nsw.gov.au/Data-Wave"):
        try:
            r = requests.get
