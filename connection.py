# ============================================================
# 连接：WiFi / NTP / Token / WebSocket / 心跳 / 看门狗
# ============================================================

import network
import uasyncio as asyncio
import urequests
import ujson
import time
import ntptime
import machine
from ws import AsyncWebsocketClient

import config
from logger import get_logger

log = get_logger("connection")

ws_client       = None
access_token    = None
token_expire_at = 0
hb_interval     = 45
_last_recv_time = 0


async def connect_wifi():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)

    if not wlan.isconnected():
        log.info("WiFi 连接中...")
        wlan.connect(config.WIFI_SSID, config.WIFI_PASS)
        for _ in range(30):
            if wlan.isconnected():
                break
            await asyncio.sleep(1)

    if wlan.isconnected():
        log.info("WiFi 已连接: %s", wlan.ifconfig())
        return True

    log.error("WiFi 连接失败")
    return False


def sync_time():
    ntptime.host = "ntp.aliyun.com"
    try:
        ntptime.settime()
        log.info("NTP 同步成功")
        return True
    except Exception as e:
        log.warning("NTP 同步失败: %s", e)
        return False


def fetch_token():
    global access_token, token_expire_at

    try:
        resp = urequests.post(
            config.TOKEN_URL,
            data=ujson.dumps({
                "appId":        config.APP_ID,
                "clientSecret": config.CLIENT_SECRET,
            }),
            headers={"Content-Type": "application/json"}
        )
        result = ujson.loads(resp.text)
        resp.close()

        if "access_token" in result:
            access_token = result["access_token"]
            token_expire_at = time.ticks_add(
                time.ticks_ms(),
                int(result.get("expires_in", 7200)) * 1000
            )
            log.info("Token 获取成功")
            return True

        log.error("Token 获取失败: %s", result)
    except Exception as e:
        log.error("Token 请求异常: %s: %s", type(e).__name__, e)
    return False


def ensure_token():
    if not access_token:
        return fetch_token()

    remaining = time.ticks_diff(token_expire_at, time.ticks_ms())
    if remaining < 60000:
        log.info("Token 即将过期，主动刷新")
        return fetch_token()

    return True


async def token_refresh_loop():
    while True:
        await asyncio.sleep(6000)
        fetch_token()


async def connect_gateway():
    global ws_client, hb_interval, _last_recv_time

    try:
        ws_client = AsyncWebsocketClient()
        await ws_client.handshake(config.GATEWAY_URL, cert_reqs=0)

        hello = ujson.loads(await ws_client.recv())
        hb_interval = hello["d"]["heartbeat_interval"] / 1000
        log.info("网关心跳间隔 %.1f 秒", hb_interval)

        await ws_client.send(ujson.dumps({
            "op": 2,
            "d": {
                "token":      f"QQBot {access_token}",
                "intents":    (1 << 25) | (1 << 24),
                "shard":      [0, 1],
                "properties": {},
            }
        }))

        ready = ujson.loads(await ws_client.recv())
        if ready.get("t") == "READY":
            log.info("网关鉴权成功")
            _last_recv_time = time.ticks_ms()
            return True

        log.error("网关鉴权失败: %s", ready)
    except Exception as e:
        log.error("网关连接异常: %s: %s", type(e).__name__, e)
    return False


async def reconnect():
    global ws_client

    if ws_client:
        try:
            await asyncio.wait_for(ws_client.close(),
                                   timeout=config.WS_CLOSE_TIMEOUT)
        except Exception:
            pass
    ws_client = None

    if not ensure_token():
        return False

    try:
        return await asyncio.wait_for(
            connect_gateway(),
            timeout=config.RECONNECT_TIMEOUT
        )
    except Exception as e:
        log.error("重连异常: %s", e)
        return False


async def heartbeat_loop():
    while True:
        await asyncio.sleep(hb_interval)
        if ws_client:
            try:
                await ws_client.send(ujson.dumps({"op": 1, "d": None}))
            except Exception as e:
                log.warning("心跳失败: %s", e)


async def watchdog_loop():
    while True:
        await asyncio.sleep(30)
        if not _last_recv_time:
            continue
        elapsed = time.ticks_diff(time.ticks_ms(), _last_recv_time)
        if elapsed > hb_interval * 2 * 1000:
            log.warning("看门狗触发")
            try:
                success = await asyncio.wait_for(
                    reconnect(),
                    timeout=config.RECONNECT_TIMEOUT + 10
                )
                if not success:
                    machine.reset()
            except Exception:
                machine.reset()