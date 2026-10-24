# ============================================================
# 天气查询 - 北京
# ============================================================

import gc
import time
import urequests
import ujson

from logger import get_logger

log = get_logger("weather")

_LAT = 39.9042
_LON = 116.4074
_CACHE_TTL = 600
_cache = {}

_WMO = {
    0: "晴", 1: "多云转晴", 2: "多云", 3: "阴",
    45: "雾", 48: "雾凇",
    51: "小毛毛雨", 53: "毛毛雨", 55: "大毛毛雨",
    61: "小雨", 63: "中雨", 65: "大雨",
    66: "冻雨", 67: "强冻雨",
    71: "小雪", 73: "中雪", 75: "大雪", 77: "雪粒",
    80: "小阵雨", 81: "阵雨", 82: "强阵雨",
    85: "小阵雪", 86: "大阵雪",
    95: "雷阵雨", 96: "雷阵雨伴小冰雹", 99: "雷阵雨伴大冰雹",
}


def get_weather():
    if "data" in _cache:
        elapsed = time.ticks_diff(time.ticks_ms(), _cache["ts"]) // 1000
        if elapsed < _CACHE_TTL:
            return _cache["data"]

    url = (
        f"https://api.open-meteo.com/v1/forecast?"
        f"latitude={_LAT}&longitude={_LON}"
        f"&current_weather=true&timezone=Asia/Shanghai"
    )

    gc.collect()
    try:
        resp = urequests.get(url)
        raw  = resp.text
        resp.close()
        data = ujson.loads(raw)
        cw   = data.get("current_weather", {})
        temp = cw.get("temperature")
        wind = cw.get("windspeed")
        code = cw.get("weathercode", 0)
        desc = _WMO.get(code, "未知")
        text = f"北京当前天气：{desc}，气温 {temp}°C，风速 {wind} km/h"
        _cache["data"] = text
        _cache["ts"]   = time.ticks_ms()
        return text
    except Exception as e:
        log.error("天气异常: %s", e)
        return None
    finally:
        gc.collect()