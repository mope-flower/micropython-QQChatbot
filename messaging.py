# ============================================================
# 消息收发
# ============================================================

import urequests
import ujson
import time
import gc

import connection
import config
from logger import get_logger

log = get_logger("messaging")


async def recv_event():
    if not connection.ws_client:
        return None
    try:
        raw = await connection.ws_client.recv()
    except Exception as e:
        log.error("recv 异常: %s", e)
        raise

    if not raw:
        raise OSError("WebSocket 断开")

    connection._last_recv_time = time.ticks_ms()
    return ujson.loads(raw)


async def ack_heartbeat():
    await connection.ws_client.send(ujson.dumps({"op": 11, "d": None}))


def send_group(group_openid, content, msg_id=None, msg_seq=1):
    connection.ensure_token()

    url = f"{config.API_BASE}/v2/groups/{group_openid}/messages"
    headers = {
        "Authorization": f"QQBot {connection.access_token}",
        "Content-Type":  "application/json; charset=utf-8",
    }

    body = {"content": content, "msg_type": 0}
    if msg_id:
        body["msg_id"]  = msg_id
        body["msg_seq"] = msg_seq

    data = ujson.dumps(body).encode("utf-8")
    gc.collect()

    try:
        resp = urequests.post(url, data=data, headers=headers)
        text = resp.text
        resp.close()
        result = ujson.loads(text)
        if result.get("err_code", 0) == 0:
            log.info("群发成功: %s", content[:30])
        else:
            log.error("群发失败: %s", result)
        del result, text, data
        gc.collect()
        return True
    except Exception as e:
        log.error("群发异常: %s", e)
        return None


def send_user(user_openid, content, msg_id=None, msg_seq=1):
    connection.ensure_token()

    url = f"{config.API_BASE}/v2/users/{user_openid}/messages"
    headers = {
        "Authorization": f"QQBot {connection.access_token}",
        "Content-Type":  "application/json; charset=utf-8",
    }

    body = {"content": content, "msg_type": 0}
    if msg_id:
        body["msg_id"]  = msg_id
        body["msg_seq"] = msg_seq

    data = ujson.dumps(body).encode("utf-8")
    gc.collect()

    try:
        resp = urequests.post(url, data=data, headers=headers)
        text = resp.text
        resp.close()
        result = ujson.loads(text)
        if result.get("err_code", 0) == 0:
            log.info("私聊发送成功")
        else:
            log.error("私聊发送失败: %s", result)
        del result, text, data
        gc.collect()
        return True
    except Exception as e:
        log.error("私聊发送异常: %s", e)
        return None