#!/usr/bin/env python3
"""Kindle 4 dashboard renderer (Glasgow).

Draws a 600x800 greyscale PNG (weather + world clock, same layout as the
re-kindle "Today" / "10 days" screens) and serves it over HTTP so the Kindle
can fetch it with wget and show it with eips.

    python dashboard.py                  serve on http://0.0.0.0:8080/dashboard.png
    python dashboard.py --demo           same, but with built-in sample data (no internet)
    python dashboard.py --once today.png write one screenshot and exit (--strict: fail if no data)
    python dashboard.py --once 10d.png --view 10d --demo

Needs: Python 3.8+ and Pillow (pip install pillow tzdata). Nothing else.
"""

import argparse
import io
import json
import os
import sys
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
try:
    from zoneinfo import ZoneInfo
except ImportError:  # Python < 3.9
    ZoneInfo = None

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

# ----------------------------------------------------------------------------
# Tuning knobs (same defaults as the re-kindle project)
# ----------------------------------------------------------------------------
PLACE = "Glasgow"
LAT, LON = 55.8642, -4.2518
TIMEZONE = "Europe/London"      # Open-Meteo resolves this for the weather/clock
# World clock cells, shown 3 x 2 in this order: (label, IANA timezone, fallback UTC offset in hours)
WORLD_CITIES = [
    ("Los Angeles", "America/Los_Angeles", -8), ("New York", "America/New_York", -5), ("Dubai", "Asia/Dubai", 4),
    ("Hong Kong", "Asia/Hong_Kong", 8), ("Tokyo", "Asia/Tokyo", 9), ("Sydney", "Australia/Sydney", 10),
]
PORT = 8080
WEATHER_CACHE_S = 30 * 60       # re-ask Open-Meteo at most this often
SCREEN_W, SCREEN_H = 600, 800   # Kindle 4 screen
HERE = os.path.dirname(os.path.abspath(__file__))

FORECAST_URL = "https://api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode({
    "latitude": LAT, "longitude": LON, "timezone": TIMEZONE, "forecast_days": 10,
    "current": "temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,is_day",
    "hourly": "temperature_2m,weather_code,precipitation_probability,is_day",
    "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,wind_speed_10m_max",
})

# WMO weather code -> (icon, label)
WMO = {
    0: ("sun", "Clear"), 1: ("partly", "Mostly clear"), 2: ("partly", "Partly cloudy"), 3: ("cloud", "Cloudy"),
    45: ("fog", "Fog"), 48: ("fog", "Fog"),
    51: ("rain", "Drizzle"), 53: ("rain", "Drizzle"), 55: ("rain", "Drizzle"),
    56: ("rain", "Icy drizzle"), 57: ("rain", "Icy drizzle"),
    61: ("rain", "Light rain"), 63: ("rain", "Rain"), 65: ("rain", "Heavy rain"),
    66: ("rain", "Icy rain"), 67: ("rain", "Icy rain"),
    71: ("snow", "Light snow"), 73: ("snow", "Snow"), 75: ("snow", "Heavy snow"), 77: ("snow", "Snow"),
    80: ("rain", "Showers"), 81: ("rain", "Showers"), 82: ("rain", "Heavy showers"),
    85: ("snow", "Snow showers"), 86: ("snow", "Snow showers"),
    95: ("storm", "Storm"), 96: ("storm", "Storm"), 99: ("storm", "Storm"),
}


def wmo(code, is_day=1):
    kind, label = WMO.get(code, ("cloud", "-"))
    if not is_day:
        if kind == "sun":
            kind = "moon"
        elif kind == "partly":
            kind = "partly_night"
    return kind, label


# ----------------------------------------------------------------------------
# Fonts
# ----------------------------------------------------------------------------
_font_cache = {}


def font(size, weight="regular"):
    key = (size, weight)
    if key in _font_cache:
        return _font_cache[key]
    names = {"regular": "Inter-Regular.otf", "medium": "Inter-Medium.otf", "bold": "Inter-Bold.otf"}
    fallbacks = {
        "regular": ["arial.ttf", "DejaVuSans.ttf", "LiberationSans-Regular.ttf"],
        "medium": ["arial.ttf", "DejaVuSans.ttf", "LiberationSans-Regular.ttf"],
        "bold": ["arialbd.ttf", "DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf"],
    }
    candidates = [os.path.join(HERE, "fonts", names[weight])] + fallbacks[weight]
    f = None
    for path in candidates:
        try:
            f = ImageFont.truetype(path, size)
            break
        except OSError:
            continue
    if f is None:
        f = ImageFont.load_default(size)
    _font_cache[key] = f
    return f


# ----------------------------------------------------------------------------
# Icons: drawn 4x oversampled as outlines, like the e-ink style in the photo
# ----------------------------------------------------------------------------
SS = 4  # supersampling factor


def _cloud_mask(canvas, dx=0, dy=0, scale=1.0):
    """Filled cloud silhouette on a 100x100 unit canvas, as an 'L' mask."""
    f = canvas / 100.0
    m = Image.new("L", (canvas, canvas), 0)
    d = ImageDraw.Draw(m)

    def X(v):
        return (dx + v * scale) * f

    def Y(v):
        return (dy + v * scale) * f

    def circle(cx, cy, r):
        d.ellipse([X(cx - r), Y(cy - r), X(cx + r), Y(cy + r)], fill=255)

    d.rounded_rectangle([X(12), Y(50), X(90), Y(70)], radius=9 * scale * f, fill=255)
    circle(31, 52, 15)
    circle(52, 38, 22)
    circle(73, 52, 15)
    return m


def _ring(mask, width_px):
    """Outline of a mask: mask minus its erosion."""
    k = int(width_px) * 2 + 1
    return ImageChops.subtract(mask, mask.filter(ImageFilter.MinFilter(k)))


def make_icon(kind, size):
    """Return a size x size 'L' image, black strokes on white."""
    c = size * SS
    f = c / 100.0
    stroke = max(2, int(5 * f * 0.55))   # outline thickness in supersampled px
    ink = Image.new("L", (c, c), 0)      # 255 = ink
    d = ImageDraw.Draw(ink)

    def line(x1, y1, x2, y2, w=5):
        d.line([x1 * f, y1 * f, x2 * f, y2 * f], fill=255, width=int(w * f))
        r = w * f / 2
        for (x, y) in ((x1, y1), (x2, y2)):
            d.ellipse([x * f - r, y * f - r, x * f + r, y * f + r], fill=255)

    def sun(cx, cy, r, rays=True, ray_in=1.45, ray_out=1.95):
        d.ellipse([(cx - r) * f, (cy - r) * f, (cx + r) * f, (cy + r) * f], outline=255, width=int(4.2 * f))
        if rays:
            import math
            for i in range(8):
                a = i * math.pi / 4
                line(cx + math.cos(a) * r * ray_in, cy + math.sin(a) * r * ray_in,
                     cx + math.cos(a) * r * ray_out, cy + math.sin(a) * r * ray_out, 4)

    def crescent(cx, cy, r, ox=0.55, oy=-0.35, shrink=0.85):
        m = Image.new("L", (c, c), 0)
        md = ImageDraw.Draw(m)
        md.ellipse([(cx - r) * f, (cy - r) * f, (cx + r) * f, (cy + r) * f], fill=255)
        cut = Image.new("L", (c, c), 0)
        cd = ImageDraw.Draw(cut)
        r2 = r * shrink
        ccx, ccy = cx + r * ox * 1.2, cy + r * oy * 1.2
        cd.ellipse([(ccx - r2) * f, (ccy - r2) * f, (ccx + r2) * f, (ccy + r2) * f], fill=255)
        moon = ImageChops.subtract(m, cut)
        return ImageChops.lighter(ink, _ring(moon, stroke))

    cloud_kinds = ("cloud", "rain", "snow", "storm", "partly", "partly_night")

    if kind == "sun":
        sun(50, 50, 19)
    elif kind == "moon":
        ink = crescent(50, 50, 30)
    elif kind == "fog":
        for i, (x1, x2) in enumerate(((16, 84), (24, 76), (16, 84), (28, 72))):
            line(x1, 28 + i * 17, x2, 28 + i * 17, 5)
    elif kind in cloud_kinds:
        if kind == "cloud":
            m = _cloud_mask(c, 0, 8, 1.0)
            ink = _ring(m, stroke)
        elif kind in ("rain", "snow", "storm"):
            m = _cloud_mask(c, 7, -2, 0.86)
            ink = _ring(m, stroke)
            d = ImageDraw.Draw(ink)
            if kind == "rain":
                for x in (32, 50, 68):
                    line(x + 3, 70, x - 3, 85, 5.5)
            elif kind == "snow":
                for (x, y) in ((33, 77), (50, 85), (67, 77)):
                    d.ellipse([(x - 4.2) * f, (y - 4.2) * f, (x + 4.2) * f, (y + 4.2) * f], fill=255)
            else:
                d.polygon([(54 * f, 66 * f), (38 * f, 86 * f), (50 * f, 86 * f), (44 * f, 99 * f),
                           (66 * f, 77 * f), (53 * f, 77 * f), (60 * f, 66 * f)], fill=255)
        else:  # partly / partly_night: sun or moon peeking out behind a cloud
            if kind == "partly":
                sun(36, 36, 13, ray_in=1.5, ray_out=2.0)
            else:
                ink = crescent(34, 34, 19)
            m = _cloud_mask(c, 12, 14, 0.82)
            halo = m.filter(ImageFilter.MaxFilter(int(3.0 * f) * 2 + 1))
            ink = ImageChops.lighter(ImageChops.subtract(ink, halo), _ring(m, stroke))

    out = ImageChops.invert(ink).resize((size, size), Image.LANCZOS)
    return out


_icon_cache = {}


def icon(kind, size):
    key = (kind, size)
    if key not in _icon_cache:
        _icon_cache[key] = make_icon(kind, size)
    return _icon_cache[key]


def paste_icon(img, kind, size, x, y):
    """Paste icon with its top-left at (x, y), darkening only (white stays transparent)."""
    ic = icon(kind, size)
    region = img.crop((x, y, x + size, y + size))
    img.paste(ImageChops.darker(region, ic), (x, y))


# ----------------------------------------------------------------------------
# Data
# ----------------------------------------------------------------------------
_weather = {"data": None, "fetched": 0.0}
_lock = threading.Lock()


def http_json(url, timeout=25, attempts=3):
    req = urllib.request.Request(url, headers={"User-Agent": "kindle-dashboard/1.0"})
    last_error = None

    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.load(r)
        except (OSError, ValueError) as e:
            last_error = e
            if attempt + 1 < attempts:
                time.sleep(3 * (attempt + 1))

    raise last_error
    

def get_weather(demo=False):
    """Returns (forecast dict or None, fetched epoch seconds)."""
    if demo:
        return demo_weather(), time.time()
    with _lock:
        if _weather["data"] is None or time.time() - _weather["fetched"] > WEATHER_CACHE_S:
            try:
                _weather.update(data=http_json(FORECAST_URL), fetched=time.time())
            except (OSError, ValueError) as e:
                print("weather fetch failed:", e, file=sys.stderr)
        return _weather["data"], _weather["fetched"]


def world_times(now_local, offset_s):
    """List of (city, 'HH:MM', 'Today'/'Tomorrow'/'Yesterday') for the world clock."""
    utc = (now_local - timedelta(seconds=offset_s)).replace(tzinfo=timezone.utc)
    out = []
    for name, tzname, fallback in WORLD_CITIES:
        try:
            if ZoneInfo is None:
                raise KeyError(tzname)
            there = utc.astimezone(ZoneInfo(tzname))
        except Exception:   # no tz database (Windows without tzdata): standard time, no daylight saving
            there = utc.astimezone(timezone(timedelta(hours=fallback)))
        diff = (there.date() - now_local.date()).days
        out.append((name, there.strftime("%H:%M"), {0: "Today", 1: "Tomorrow", -1: "Yesterday"}.get(diff, "")))
    return out


def demo_weather():
    """Sample data that reproduces the screenshot (10 Nov 2026, 00:04)."""
    start = datetime(2026, 11, 10)
    times, temps, codes, pops, days = [], [], [], [], []
    base = {1: (3, 6, 0), 4: (3, 6, 0), 7: (63, 6, 5), 10: (63, 6, 93), 13: (63, 7, 80), 16: (2, 9, 5), 19: (0, 8, 0)}
    for h in range(240):
        t = start + timedelta(hours=h)
        times.append(t.strftime("%Y-%m-%dT%H:00"))
        hh = t.hour
        if h < 24 and hh in base:
            code, temp, pop = base[hh]
        else:
            code, temp, pop = (3, 7, 20)
        codes.append(code)
        temps.append(temp)
        pops.append(pop)
        days.append(1 if 7 <= hh <= 16 else 0)
    daily_dates = [(start + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(10)]
    return {
        "utc_offset_seconds": 0,
        "current": {"temperature_2m": 6.0, "apparent_temperature": 3.0, "relative_humidity_2m": 91,
                    "weather_code": 3, "is_day": 0},
        "hourly": {"time": times, "temperature_2m": temps, "weather_code": codes,
                   "precipitation_probability": pops, "is_day": days},
        "daily": {"time": daily_dates,
                  "weather_code": [63, 61, 3, 2, 61, 71, 3, 1, 0, 80],
                  "temperature_2m_max": [9, 8, 8, 9, 7, 3, 4, 6, 8, 7],
                  "temperature_2m_min": [5, 4, 3, 4, 3, 0, -1, 0, 2, 3],
                  "precipitation_probability_max": [95, 29, 10, 5, 60, 70, 15, 0, 0, 55],
                  "wind_speed_10m_max": [14, 12, 10, 8, 18, 20, 9, 7, 6, 15]},
    }


# ----------------------------------------------------------------------------
# Drawing helpers
# ----------------------------------------------------------------------------
BLACK, WHITE, GREY = 0, 255, 105     # GREY = secondary text; 105 stays readable on a 16-level panel


def deg(v):
    return "-" if v is None else "%d\u00b0" % round(v)


def pct(v):
    return "-" if v is None else "%d%%" % v


def text(d, xy, s, size, weight="regular", fill=BLACK, anchor="la"):
    d.text(xy, s, font=font(size, weight), fill=fill, anchor=anchor)


def hline(d, y, x1=20, x2=SCREEN_W - 20, w=1, fill=BLACK):
    d.rectangle([x1, y, x2, y + w - 1], fill=fill)


def draw_battery(d, x, y, pct_value):
    """Small battery outline with level, ending at x+30. Right-aligned label is drawn by caller."""
    d.rectangle([x, y, x + 28, y + 13], outline=BLACK, width=2)
    d.rectangle([x + 29, y + 4, x + 31, y + 9], fill=BLACK)
    fill_w = int(24 * max(0, min(100, pct_value)) / 100)
    if fill_w:
        d.rectangle([x + 2, y + 2, x + 1 + fill_w, y + 11], fill=BLACK)


def header(img, d, active, place, updated, batt):
    text(d, (22, 14), place, 19, "medium")
    text(d, (300, 14), "Updated " + updated, 18, "regular", GREY, "ma")
    if batt is not None:
        label = "%d%%" % batt
        text(d, (SCREEN_W - 22, 14), label, 17, "regular", GREY, "ra")
        w = font(17).getlength(label)
        draw_battery(d, int(SCREEN_W - 22 - w - 40), 17, batt)
    hline(d, 48)
    # tab labels (the Kindle 4 has no touch; the page buttons switch views)
    text(d, (SCREEN_W // 2 - 110, 58), "Today", 22, "bold" if active == "today" else "regular",
         BLACK if active == "today" else GREY, "ma")
    text(d, (SCREEN_W // 2 + 110, 58), "10 days", 22, "bold" if active == "10d" else "regular",
         BLACK if active == "10d" else GREY, "ma")
    ax = SCREEN_W // 2 - 110 if active == "today" else SCREEN_W // 2 + 110
    hline(d, 92, 20, SCREEN_W - 20, 1)
    d.rectangle([ax - 52, 90, ax + 52, 93], fill=BLACK)


def hourly_slots(hourly, now_local, count=7, step=3):
    stamp = now_local.strftime("%Y-%m-%dT%H:%M")
    start = next((i for i, t in enumerate(hourly["time"]) if t > stamp), len(hourly["time"]))
    return list(range(start, len(hourly["time"]), step))[:count]


# ----------------------------------------------------------------------------
# Screens
# ----------------------------------------------------------------------------
def screen_today(img, d, w, world, now, updated, batt):
    cur, hourly, daily = w["current"], w["hourly"], w["daily"]
    today = now.strftime("%Y-%m-%d")
    tomorrow = (now + timedelta(days=1)).strftime("%Y-%m-%d")
    t0 = daily["time"].index(today)
    t1 = daily["time"].index(tomorrow)

    header(img, d, "today", PLACE, updated, batt)

    # --- current conditions (left) ---
    kind, label = wmo(cur["weather_code"], cur.get("is_day", 1))
    paste_icon(img, kind, 120, 22, 128)
    big = deg(cur["temperature_2m"])
    text(d, (152, 112), big, 112, "bold", BLACK, "la")
    text(d, (150, 252), label, 28, "medium", BLACK, "ma")
    text(d, (150, 292), "Feels like %s \u00b7 Humidity %s" % (deg(cur["apparent_temperature"]),
                                                              pct(cur["relative_humidity_2m"])),
         17, "regular", GREY, "ma")

    # --- today / tomorrow (right) ---
    rx = 372
    k0, l0 = wmo(daily["weather_code"][t0])
    text(d, (rx, 106), "Today", 17, "regular", GREY)
    text(d, (rx, 126), "%s / %s" % (deg(daily["temperature_2m_max"][t0]), deg(daily["temperature_2m_min"][t0])),
         32, "bold")
    text(d, (rx, 172), l0, 22, "medium")
    text(d, (rx, 202), "%s rain \u00b7 %d km/h" % (pct(daily["precipitation_probability_max"][t0]),
                                                   round(daily["wind_speed_10m_max"][t0])), 17, "regular", GREY)
    hline(d, 238, rx - 8, SCREEN_W - 20)
    k1, l1 = wmo(daily["weather_code"][t1])
    paste_icon(img, k1, 46, rx - 4, 252)
    text(d, (rx + 50, 250), "Tomorrow", 17, "regular", GREY)
    text(d, (rx + 50, 270), "%s / %s" % (deg(daily["temperature_2m_max"][t1]), deg(daily["temperature_2m_min"][t1])),
         26, "bold")
    text(d, (rx + 50, 304), "%s rain" % pct(daily["precipitation_probability_max"][t1]), 17, "regular", GREY)

    hline(d, 336)

    # --- hourly strip ---
    slots = hourly_slots(hourly, now)
    col_w = (SCREEN_W - 40) / 7.0
    for n, i in enumerate(slots):
        cx = int(20 + col_w * n + col_w / 2)
        k, _ = wmo(hourly["weather_code"][i], hourly.get("is_day", [1] * 999)[i])
        text(d, (cx, 352), hourly["time"][i][11:16], 17, "regular", GREY, "ma")
        paste_icon(img, k, 52, cx - 26, 382)
        text(d, (cx, 446), deg(hourly["temperature_2m"][i]), 22, "bold", BLACK, "ma")
        text(d, (cx, 478), pct(hourly["precipitation_probability"][i]), 16, "regular", GREY, "ma")

    hline(d, 514)

    # --- world clock ---
    text(d, (22, 530), "World clock", 22, "bold")
    text(d, (SCREEN_W - 22, 535), now.strftime("%A %-d %B %Y") if os.name != "nt"
         else now.strftime("%A %#d %B %Y"), 17, "regular", GREY, "ra")
    cw = (SCREEN_W - 40) // 3
    for idx, (name, hm, day) in enumerate(world):
        r, cidx = divmod(idx, 3)
        x0 = 20 + cidx * cw
        y0 = 568 + r * 100
        mx = x0 + cw // 2
        text(d, (mx, y0 + 4), name, 18, "regular", GREY, "ma")
        text(d, (mx, y0 + 26), hm, 40, "bold", BLACK, "ma")
        text(d, (mx, y0 + 74), day, 15, "regular", GREY, "ma")

    # page dots (view indicator)
    d.rectangle([SCREEN_W // 2 - 14, 776, SCREEN_W // 2 - 6, 784], fill=BLACK)
    d.rectangle([SCREEN_W // 2 + 6, 776, SCREEN_W // 2 + 14, 784], outline=BLACK, width=1)


def screen_10d(img, d, w, world, now, updated, batt):
    daily = w["daily"]
    today = now.strftime("%Y-%m-%d")
    start = daily["time"].index(today)
    header(img, d, "10d", PLACE, updated, batt)
    y = 104
    row_h = 66
    for n, i in enumerate(range(start, min(start + 10, len(daily["time"])))):
        dt = datetime.strptime(daily["time"][i], "%Y-%m-%d")
        name = "Today" if n == 0 else dt.strftime("%a %-d") if os.name != "nt" else dt.strftime("%a %#d")
        kind, label = wmo(daily["weather_code"][i])
        top = y + n * row_h
        text(d, (24, top + 20), name, 24, "bold" if n == 0 else "medium")
        paste_icon(img, kind, 46, 150, top + 8)
        text(d, (212, top + 21), label, 21, "regular")
        text(d, (SCREEN_W - 118, top + 14), "%s / %s" % (deg(daily["temperature_2m_max"][i]),
                                                        deg(daily["temperature_2m_min"][i])),
             24, "bold", BLACK, "ra")
        text(d, (SCREEN_W - 118, top + 40), "%s rain" % pct(daily["precipitation_probability_max"][i]),
             15, "regular", GREY, "ra")
        text(d, (SCREEN_W - 24, top + 24), "%d km/h" % round(daily["wind_speed_10m_max"][i]), 16,
             "regular", GREY, "ra")
        if n < 9:
            hline(d, top + row_h - 1, 20, SCREEN_W - 20, 1, 190)
    d.rectangle([SCREEN_W // 2 - 14, 776, SCREEN_W // 2 - 6, 784], outline=BLACK, width=1)
    d.rectangle([SCREEN_W // 2 + 6, 776, SCREEN_W // 2 + 14, 784], fill=BLACK)


def screen_error(img, d, msg):
    text(d, (SCREEN_W // 2, 360), "Weather unavailable", 34, "bold", BLACK, "mm")
    text(d, (SCREEN_W // 2, 410), msg, 20, "regular", GREY, "mm")


def render(view="today", batt=None, rot=0, demo=False, now_override=None, strict=False):
    w, fetched = get_weather(demo)
    img = Image.new("L", (SCREEN_W, SCREEN_H), WHITE)
    d = ImageDraw.Draw(img)
    try:
        if w is None:
            raise ValueError("Couldn't reach Open-Meteo for " + PLACE)
        tz = timezone(timedelta(seconds=w.get("utc_offset_seconds", 0)))
        now = now_override or (datetime(2026, 11, 10, 0, 4) if demo else datetime.now(tz).replace(tzinfo=None))
        updated = (datetime.fromtimestamp(fetched, tz).replace(tzinfo=None) if not demo else now).strftime("%H:%M")
        world = world_times(now, w.get("utc_offset_seconds", 0))
        (screen_10d if view == "10d" else screen_today)(img, d, w, world, now, updated, batt)
    except (KeyError, ValueError, IndexError) as e:
        print("render failed:", repr(e), file=sys.stderr)
        if strict:   # in CI, fail the job so the last good picture stays published
            raise SystemExit(1)
        img = Image.new("L", (SCREEN_W, SCREEN_H), WHITE)
        d = ImageDraw.Draw(img)
        screen_error(img, d, str(e)[:60])
    if rot:
        img = img.rotate(-rot, expand=True)
    # Kindle 4 panel has 16 grey levels: quantise so what you see here is what the panel shows
    img = img.point(lambda v: min(255, (v + 8) // 17 * 17))
    return img


def png_bytes(img):
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)   # 8-bit greyscale, non-interlaced: what eips -g wants
    return buf.getvalue()


# ----------------------------------------------------------------------------
# HTTP
# ----------------------------------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    demo = False

    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(url.query)
        if url.path in ("/", "/index.html"):
            body = (b"<html><body style='font-family:sans-serif'><h3>Kindle dashboard</h3>"
                    b"<img src='/dashboard.png' width=300> <img src='/dashboard.png?view=10d' width=300>"
                    b"</body></html>")
            ctype = "text/html"
        elif url.path == "/dashboard.png":
            view = q.get("view", ["today"])[0]
            try:
                batt = int(q["batt"][0]) if "batt" in q else None
                rot = int(q.get("rot", ["0"])[0])
            except ValueError:
                batt, rot = None, 0
            body = png_bytes(render(view, batt, rot, self.demo))
            ctype = "image/png"
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        sys.stderr.write("%s %s\n" % (self.address_string(), fmt % args))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--demo", action="store_true", help="use built-in sample data (no internet)")
    ap.add_argument("--once", metavar="FILE", help="write one PNG to FILE and exit")
    ap.add_argument("--view", choices=["today", "10d"], default="today")
    ap.add_argument("--batt", type=int, help="battery %% to draw in the header")
    ap.add_argument("--rot", type=int, default=0, choices=[0, 90, 180, 270], help="rotate output clockwise")
    ap.add_argument("--strict", action="store_true", help="with --once: exit with an error instead of drawing an error screen")
    ap.add_argument("--port", type=int, default=PORT)
    a = ap.parse_args()
    if a.once:
        with open(a.once, "wb") as fh:
            fh.write(png_bytes(render(a.view, a.batt, a.rot, a.demo, strict=a.strict)))
        print("wrote", a.once)
        return
    Handler.demo = a.demo
    print("Serving on http://0.0.0.0:%d/dashboard.png%s" % (a.port, "  (demo data)" if a.demo else ""))
    ThreadingHTTPServer(("0.0.0.0", a.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
