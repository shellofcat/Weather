import json, re
from datetime import datetime
from zoneinfo import ZoneInfo
import requests

TZ = ZoneInfo("Australia/Sydney")
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
}

# BOM NSW Observations JSON (reliable, never blocks GitHub IPs)
BOM_STATIONS = {
    "fort_denison": "http://www.bom.gov.au/fwo/IDN60901/IDN60901.94767.json",  # Sydney Harbour (Wedding Cake / Fort Denison area)
    "sydney_airport": "http://www.bom.gov.au/fwo/IDN60901/IDN60901.94767.json",
    "kurnell": "http://www.bom.gov.au/fwo/IDN60901/IDN60901.95756.json",        # Kurnell / Botany Bay
    "wattamolla": "http://www.bom.gov.au/fwo/IDN60901/IDN60901.95752.json",     # Wattamolla / South coast ref
    "north_head": "http://www.bom.gov.au/fwo/IDN60901/IDN60901.95768.json",     # North Head / Sydney Entrance
    "terrey_hills": "http://www.bom.gov.au/fwo/IDN60901/IDN60901.94759.json",
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

def fdeg(v):
    try:
        return int(round(float(v))) % 360 if v not in (None, "", "--", "-") else "--"
    except Exception:
        return "--"

def probe(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        return {"status": r.status_code, "len": len(r.text), "sample": r.text[:250].replace("\n", " ")}
    except Exception as e:
        return {"error": str(e)}

def main():
    now = datetime.now(TZ)
    diag = {
        "pansw_home": probe("https://wavewindtide.portauthoritynsw.com.au/"),
        "pansw_api_wind": probe("https://webservices.portauthoritynsw.com.au/api/EnvironmentWind"),
        "pansw_api_wave": probe("https://webservices.portauthoritynsw.com.au/api/EnvironmentWave"),
        "pansw_api_tide": probe("https://webservices.portauthoritynsw.com.au/api/EnvironmentTide"),
        "mhl_syddow": probe("https://mhl.nsw.gov.au/Station-SYDDOW"),
        "mhl_botdow": probe("https://mhl.nsw.gov.au/Station-BOTDOW"),
        "bom_syd_harbour": probe("http://www.bom.gov.au/fwo/IDN60901/IDN60901.95766.json"),
    }

    payload = {
        "updated_iso": now.isoformat(),
        "updated_display": now.strftime("%-d %b %Y · %-I:%M %p %Z"),
        "diag": diag,
    }
    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)

if __name__ == "__main__":
    main()
