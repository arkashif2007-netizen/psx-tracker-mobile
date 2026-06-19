import json
import os
import time
import threading
import re
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
from datetime import datetime
from config import SYMBOLS_CACHE, PRICE_REFRESH_SECONDS

# ------------------------------------------------------------------
# TradingView Pakistan scanner (public GET endpoint)
# ------------------------------------------------------------------
_BACKUP_FILE = SYMBOLS_CACHE
_CACHE = {"symbols": None, "fetched_at": 0}


def _cache_age_seconds() -> int:
    return int(time.time()) - int(_CACHE["fetched_at"] or 0)


def _save_cache(symbols):
    _CACHE["symbols"] = symbols
    _CACHE["fetched_at"] = int(time.time())
    try:
        with open(_BACKUP_FILE, "w", encoding="utf-8") as f:
            json.dump(symbols, f)
    except Exception:
        pass


def _load_cache_file():
    try:
        with open(_BACKUP_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


_TV_SCAN_URL = "https://scanner.tradingview.com/pakistan/scan"


def _tv_scan_raw() -> dict:
    req = Request(_TV_SCAN_URL, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json, text/plain, */*",
    })
    with urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _fetch_symbols_from_tv(force_refresh=False):
    if not force_refresh and _CACHE["symbols"] is not None and _cache_age_seconds() < (6 * 3600):
        return _CACHE["symbols"]
    cached = _load_cache_file()
    if cached and not force_refresh:
        _save_cache(cached)
        return cached
    try:
        raw = _tv_scan_raw() or {}
        data = raw.get("data") or []
        symbols = []
        for item in data:
            s = item.get("s", "")
            if not s:
                continue
            # s format: PSX:SYMBOL
            symbol = s.replace("PSX:", "").strip()
            symbols.append({"symbol": symbol, "name": symbol, "sector": "PSX"})
        if symbols:
            _save_cache(symbols)
            return symbols
    except Exception as e:
        print("[SYMBOLS] TradingView fetch failed:", e)
    if cached:
        return cached
    return []


# ------------------------------------------------------------------
# Live price cache (30s)
# ------------------------------------------------------------------
_price_cache: dict[str, dict] = {}
_price_lock = threading.Lock()
_last_refresh_ts: float | None = None


def fetch_live_prices(symbols):
    if not symbols:
        return {}
    return {s: {"price": None} for s in symbols}


def get_cached_prices(symbols):
    global _last_refresh_ts
    with _price_lock:
        now_ts = time.time()
        if _last_refresh_ts is None or (now_ts - _last_refresh_ts) > PRICE_REFRESH_SECONDS:
            try:
                raw = _tv_scan_raw() or {}
                data = raw.get("data") or []
                fresh = {}
                for item in data:
                    s = item.get("s", "").replace("PSX:", "").strip()
                    d = item.get("d") or []
                    # TV scan returns values in order matching requested columns.
                    # We reconstruct minimal useful fields from the payload:
                    close = None
                    for key in ("close", "price", "last", "V"):
                        # d is usually a dict when columns were requested,
                        # but here response appears as ticker list. We handle both.
                        pass
                    if isinstance(d, dict):
                        close = d.get("close") or d.get("price") or d.get("last")
                    if s and close is not None:
                        try:
                            fresh[s] = {"price": round(float(close), 2)}
                        except (TypeError, ValueError):
                            pass
                _price_cache.update(fresh)
                _last_refresh_ts = now_ts
            except Exception as e:
                print("[PRICE] TradingView refresh failed:", e)
        return {s: _price_cache.get(s, {"price": None}) for s in symbols}


def get_single_price(symbol: str):
    result = get_cached_prices([symbol])
    return result.get(symbol, {}).get("price")


# ------------------------------------------------------------------
# Self-test
# ------------------------------------------------------------------
if __name__ == "__main__":
    syms = _fetch_symbols_from_tv(force_refresh=True)
    print("Symbols count:", len(syms))
    print("Sample:", syms[:10])
    prices = get_cached_prices(["ENGRO", "HBL", "LUCK"])
    print("prices:", prices)
