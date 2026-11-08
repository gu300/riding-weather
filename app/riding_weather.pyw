"""Riding Weather: 7-day NOAA forecast for riding areas, as a Windows desktop app.

Pure Python standard library (tkinter + urllib), no installs needed.
Run with: double-click (as .pyw) or `python riding_weather.pyw`.
Data: National Weather Service API (api.weather.gov), no key needed.
"""
import json
import os
import re
import threading
import tkinter as tk
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone

# ---------- Settings: edit names or coordinates here ----------
AREAS = [
    ("Wildcat", 33.7774, -111.6743),
    ("Boulders", 33.8691, -112.4533),
    ("7mi", 34.5220, -112.3968),
    ("Alto", 34.5887, -112.5609),
    ("Kelly", 34.9528, -111.6357),
    ("Sedona", 34.8697, -111.7610),
]
DAYS = 7
REFRESH_MINUTES = 60
USER_AGENT = "RidingWeather/1.0 (personal use)"
COLD, MID, HOT = (0x5A, 0x8A, 0xC6), (0xFC, 0xFC, 0xFF), (0xF8, 0x69, 0x6B)
# ---------------------------------------------------------------

DATA_DIR = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "RidingWeather")
GRID_FILE = os.path.join(DATA_DIR, "grid.json")
LAST_FILE = os.path.join(DATA_DIR, "last.json")


def read_json(path, fallback):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return fallback


def write_json(path, obj):
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(obj, f)
    except Exception:
        pass


def get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/geo+json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def forecast_url(name, lat, lon, grid):
    key = f"{lat},{lon}"
    if key not in grid:
        p = get_json(f"https://api.weather.gov/points/{lat},{lon}")
        url = (p.get("properties") or {}).get("forecast")
        if not url:
            raise RuntimeError(f"No NWS forecast for {name}")
        grid[key] = url
    return grid[key]


def max_number(s):
    nums = [int(n) for n in re.findall(r"\d+", s or "")]
    return max(nums) if nums else None


def summarize(periods):
    days = {}
    for p in periods:
        d = days.setdefault(p["startTime"][:10], {"high": None, "low": None, "pop": 0, "wind": None,
                                                   "gust": None, "dayText": "", "nightText": ""})
        pop = (p.get("probabilityOfPrecipitation") or {}).get("value")
        if pop is not None:
            d["pop"] = max(d["pop"], pop)
        if p.get("isDaytime"):
            d["high"] = p.get("temperature")
            d["wind"] = max_number(p.get("windSpeed"))
            g = re.search(r"gusts? as high as (\d+)", p.get("detailedForecast") or "", re.I)
            d["gust"] = int(g.group(1)) if g else None
            d["dayText"] = f'{p["name"]}: {p.get("detailedForecast", "")}'
        else:
            d["low"] = p.get("temperature")
            d["nightText"] = f'{p["name"]}: {p.get("detailedForecast", "")}'
    return days


def load_area(area, grid):
    name, lat, lon = area
    try:
        f = get_json(forecast_url(name, lat, lon, grid))
    except Exception:
        grid.pop(f"{lat},{lon}", None)  # grid may have moved: look it up again once
        f = get_json(forecast_url(name, lat, lon, grid))
    return {"name": name, "days": summarize(f["properties"]["periods"])}


def load_all():
    grid = read_json(GRID_FILE, {})
    with ThreadPoolExecutor(max_workers=len(AREAS)) as ex:
        areas = list(ex.map(lambda a: load_area(a, grid), AREAS))
    write_json(GRID_FILE, grid)
    data = {"fetched": datetime.now(timezone.utc).isoformat(), "areas": areas}
    write_json(LAST_FILE, data)
    return data


def color_scale(values):
    v = sorted(x for x in values if x is not None)
    if not v:
        return lambda x: "#eeeeee"
    lo, hi, mid = v[0], v[-1], v[len(v) // 2]

    def mix(a, b, t):
        return "#" + "".join(f"{round(a[i] + (b[i] - a[i]) * t):02x}" for i in range(3))

    def col(x):
        if x is None:
            return "#eeeeee"
        if x <= mid:
            return mix(COLD, MID, 1 if mid == lo else (x - lo) / (mid - lo))
        return mix(MID, HOT, 0 if hi == mid else (x - mid) / (hi - mid))
    return col


def ago(iso):
    m = round((datetime.now(timezone.utc) - datetime.fromisoformat(iso)).total_seconds() / 60)
    return "just now" if m < 1 else f"{m} min ago" if m < 60 else f"{round(m / 60)} h ago"


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Riding Weather")
        self.configure(bg="#f4f5f7")
        self.minsize(640, 520)
        self.geometry("900x700")
        self.data, self.stale = None, False
        self.font = "Segoe UI"

        top = tk.Frame(self, bg="#f4f5f7")
        top.pack(fill="x", padx=14, pady=(12, 4))
        tk.Label(top, text="Riding weather", font=(self.font, 16, "bold"), bg="#f4f5f7").pack(side="left")
        self.meta = tk.Label(top, text="Loading NOAA forecasts…", font=(self.font, 9), fg="#888", bg="#f4f5f7")
        self.meta.pack(side="left", padx=10, pady=(6, 0))
        tk.Button(top, text="Refresh", command=self.refresh, font=(self.font, 9), relief="groove",
                  bg="white").pack(side="right")

        self.grid_frame = tk.Frame(self, bg="#f4f5f7")
        self.grid_frame.pack(fill="both", expand=True, padx=12)

        tk.Label(self, text="Big number = daytime high °F; (n) = tonight's low when today's high has passed. "
                            "Small text: ↓low · rain chance · wind mph (g = gusts). Click a cell for the full NWS forecast.",
                 font=(self.font, 8), fg="#888", bg="#f4f5f7", wraplength=760, justify="left").pack(fill="x", padx=14, pady=4)
        self.detail = tk.Text(self, height=7, wrap="word", font=(self.font, 10), relief="flat", padx=10, pady=8)
        self.detail.pack(fill="x", padx=14, pady=(0, 12))
        self.detail.insert("1.0", "Click a cell to see the full forecast.")
        self.detail.configure(state="disabled")

        cached = read_json(LAST_FILE, None)
        if cached:
            self.data, self.stale = cached, True
            self.render()
        self.refresh()
        self.after(60_000, self.tick)

    def tick(self):
        if self.data:
            self.update_meta()
        self.after(60_000, self.tick)

    def refresh(self):
        self.meta.configure(text="Loading NOAA forecasts…", fg="#888")

        def work():
            try:
                data, err = load_all(), None
            except Exception as e:
                data, err = None, e
            self.after(0, lambda: self.on_loaded(data, err))
        threading.Thread(target=work, daemon=True).start()
        self.after(REFRESH_MINUTES * 60_000, self.refresh)

    def on_loaded(self, data, err):
        if data:
            self.data, self.stale = data, False
            self.render()
        elif self.data:
            self.stale = True
            self.update_meta()
        else:
            self.meta.configure(text=f"Could not reach the National Weather Service: {err}", fg="#c0392b")

    def update_meta(self):
        txt = f"Daily highs °F · NOAA/NWS · updated {ago(self.data['fetched'])}"
        self.meta.configure(text=txt + (" (offline, showing last data)" if self.stale else ""),
                            fg="#c0392b" if self.stale else "#888")

    def show(self, area, day_label, cell):
        self.detail.configure(state="normal")
        self.detail.delete("1.0", "end")
        body = "\n\n".join(t for t in (cell["dayText"], cell["nightText"]) if t)
        self.detail.insert("1.0", f"{area} · {day_label}\n\n{body}")
        self.detail.configure(state="disabled")

    def render(self):
        for w in self.grid_frame.winfo_children():
            w.destroy()
        today = date.today()
        dates = [today + timedelta(days=i) for i in range(DAYS)]
        rows = [[a["days"].get(d.isoformat()) for a in self.data["areas"]] for d in dates]
        col = color_scale([c["high"] for r in rows for c in r if c])
        bg = "#f4f5f7"
        for ci, a in enumerate(self.data["areas"]):
            tk.Label(self.grid_frame, text=a["name"], font=(self.font, 10, "bold"), fg="#444", bg=bg) \
                .grid(row=0, column=ci + 1, sticky="nsew", pady=(4, 2))
        self.grid_frame.columnconfigure(0, minsize=80)
        for ci in range(len(self.data["areas"])):
            self.grid_frame.columnconfigure(ci + 1, weight=1, uniform="area")
        for ri, (d, cells) in enumerate(zip(dates, rows)):
            label = "Today" if ri == 0 else d.strftime("%a %m/%d").replace(" 0", " ").replace("/0", "/")
            long_label = d.strftime("%A, %b %d").replace(" 0", " ")
            tk.Label(self.grid_frame, text=label, font=(self.font, 10, "bold"), fg="#333", bg=bg, anchor="w") \
                .grid(row=ri + 1, column=0, sticky="nsew")
            self.grid_frame.rowconfigure(ri + 1, weight=1, uniform="day")
            for ci, c in enumerate(cells):
                color = col(c["high"]) if c else "#eeeeee"
                cell = tk.Frame(self.grid_frame, bg=color, cursor="hand2", highlightthickness=1,
                                highlightbackground=bg)
                cell.grid(row=ri + 1, column=ci + 1, sticky="nsew", padx=2, pady=2)
                if not c:
                    tk.Label(cell, text="–", bg=color).pack(expand=True)
                    continue
                big = c["high"] if c["high"] is not None else (f'({c["low"]})' if c["low"] is not None else "–")
                low = c["low"] if c["low"] is not None else "–"
                parts = [f"↓{low}" if c["high"] is not None else "",
                         f'{c["pop"]}%' if c["pop"] >= 10 else "",
                         (f'{c["wind"]}' + (f'g{c["gust"]}' if c["gust"] else "")) if c["wind"] is not None else ""]
                small = "  ".join(p for p in parts if p)
                l1 = tk.Label(cell, text=big, font=(self.font, 17, "bold"), bg=color, fg="#1a1a1a")
                l2 = tk.Label(cell, text=small, font=(self.font, 8), bg=color, fg="#333")
                l1.pack(pady=(6, 0))
                l2.pack(pady=(0, 6))
                handler = (lambda e, a=self.data["areas"][ci]["name"], dl=long_label, cc=c: self.show(a, dl, cc))
                for w in (cell, l1, l2):
                    w.bind("<Button-1>", handler)
        self.update_meta()


if __name__ == "__main__":
    App().mainloop()
