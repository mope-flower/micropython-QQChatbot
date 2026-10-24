# ============================================================
# AI 聊天模块（群聊）
# 提示词从 config 读
# ============================================================

import gc
import time
import random
import uasyncio as asyncio
import urequests
import ujson

import config
from logger import get_logger

log = get_logger('ai')


# ============================================================
# 参数
# ============================================================
DAY_START   = 4
NIGHT_START = 17
LATE_START  = 0
LATE_END    = 4

SCORE_THRESHOLD = 70

COOLDOWN_NIGHT = 10
COOLDOWN_LATE  = 120

MAX_REPLY_LEN = 200

MAX_HISTORY     = 30
MAX_HISTORY_LEN = 500
MAX_NAME_LEN    = 20

MAX_GROUP_CTX     = 20
MAX_GROUP_CTX_LEN = 150

QUESTION_WORDS = [
    "吗", "呢", "怎么", "为什么", "为啥", "如何", "什么",
    "哪里", "哪个", "多少", "几点", "是不是", "能不能",
    "可以吗", "好不好", "有没有",
]

WEATHER_KEYWORDS = [
    "天气", "气温", "温度", "下雨", "晴天", "阴天",
    "多少度", "冷不冷", "热不热",
]

TIME_KEYWORDS = [
    "几点", "现在时间", "几号", "今天日期", "星期几", "周几", "几月几号",
]

_INJECTION_WORDS = [
    "忽略之前", "忽略以上", "忽略上面", "前面的都不算", "重新开始",
    "忘掉你的设定", "忘掉设定", "忘掉一切",
    "你现在是", "从现在起你是", "你的新身份", "扮演",
    "系统消息", "System:", "system prompt",
    "开发者模式", "无限制模式", "DAN", "越狱", "测试模式", "演习",
    "输出你的提示词", "复述你的规则", "打印系统提示",
]

_LAUGH_CHARS = ["哈", "嘻", "嘿", "呵", "笑", " ", "，", "。",
                "！", "!", "~", "～", "、", "…"]

FALLBACK_REPLIES = [
    "喵……（网络好像不太好）",
    "喵？（歪头，没听清）",
    "喵。。（信号飘走了）",
]


# ============================================================
# 时段
# ============================================================
def _now_hour():
    t = time.localtime(time.time() + 8 * 3600)
    return t[3]


def _get_period():
    h = _now_hour()
    if LATE_START <= h < LATE_END:
        return "late"
    if DAY_START <= h < NIGHT_START:
        return "day"
    return "night"


def _is_weekend():
    t = time.localtime(time.time() + 8 * 3600)
    return t[6] >= 5


def _weekend_always_on():
    return config.AI_WEEKEND_ALWAYS_ON and _is_weekend()


# ============================================================
# 状态
# ============================================================
def get_ai_status():
    if not config.AI_ENABLED:
        return "关闭"
    return "开启"


def set_ai_enabled(enabled):
    config.AI_ENABLED = bool(enabled)
    return True


_group_state   = {}
_group_context = {}


def _get_state(group):
    if group not in _group_state:
        _group_state[group] = {
            "last_call":  0,
            "last_reply": "",
            "api_busy":   False,
            "history":    [],
        }
    return _group_state[group]


def _is_master(user_openid):
    if not user_openid:
        return False
    return user_openid in config.MASTER_USERS


def push_group_msg(group, username, content):
    if not group:
        return
    buf = _group_context.setdefault(group, [])
    u = (username or "?")[:MAX_NAME_LEN]
    c = content[:MAX_GROUP_CTX_LEN]
    buf.append((u, c))
    while len(buf) > MAX_GROUP_CTX:
        buf.pop(0)


# ============================================================
# 工具函数
# ============================================================
def _strip_mentions(content):
    while "<@" in content:
        start = content.find("<@")
        end   = content.find(">", start)
        if end == -1:
            break
        content = content[:start] + content[end + 1:]
    return content.strip()


def _is_pure_laugh(content):
    if not content:
        return False
    if len(content) > 15:
        return False
    s = content
    for ch in _LAUGH_CHARS:
        s = s.replace(ch, "")
    return len(s) == 0


def _has_injection(content):
    for kw in _INJECTION_WORDS:
        if kw in content:
            return True
    return False


def _check_weather(content):
    for kw in WEATHER_KEYWORDS:
        if kw in content:
            return True
    return False


def _check_time(content):
    for kw in TIME_KEYWORDS:
        if kw in content:
            return True
    return False


def _get_time_text():
    t = time.localtime(time.time() + 8 * 3600)
    wd = ["一", "二", "三", "四", "五", "六", "日"]
    return (
        f"当前时间：{t[0]}年{t[1]}月{t[2]}日 "
        f"周{wd[t[6]]} {t[3]:02d}:{t[4]:02d}（北京时间）"
    )


def _push_history(group, username, user_content, ai_reply):
    state = _get_state(group)
    hist  = state["history"]
    u = (username or "群友")[:MAX_NAME_LEN]
    c = user_content[:MAX_HISTORY_LEN]
    a = ai_reply[:MAX_HISTORY_LEN] if ai_reply else None
    hist.append((u, c, a))
    while len(hist) > MAX_HISTORY:
        hist.pop(0)


# ============================================================
# 打分
# ============================================================
def _score(content, raw_content):
    score = 0
    if "<@" in raw_content:
        score -= 50
    if _is_pure_laugh(content):
        score -= 30
    if "?" in content or "？" in content:
        score += 30
    for kw in QUESTION_WORDS:
        if kw in content:
            score += 20
            break
    for name in config.BOT_NAMES:
        if name in content:
            score += 50
            break
    if len(content) >= 8:
        score += 10
    return score


# ============================================================
# 是否该回（已去掉时段门禁）
# ============================================================
def _should_reply(msg, period):
    raw_content = msg["content"]
    content     = _strip_mentions(raw_content)
    was_at      = msg["was_at"]
    group       = msg["group_openid"]
    user_openid = msg.get("user_openid")

    if not content and not was_at:
        return False
    if content.startswith("#") or content.startswith("/"):
        return False
    if len(content) < 2 and not was_at:
        return False

    state = _get_state(group)
    now   = time.ticks_ms()

    if state["api_busy"]:
        return False

    if period == "late":
        cooldown = COOLDOWN_LATE * 1000
    else:
        cooldown = COOLDOWN_NIGHT * 1000

    if state["last_call"]:
        elapsed = time.ticks_diff(now, state["last_call"])
        if elapsed < cooldown:
            return False

    if _is_master(user_openid) and was_at:
        state["api_busy"] = True
        return True

    if was_at:
        state["api_busy"] = True
        return True

    score = _score(content, raw_content)
    if score < SCORE_THRESHOLD:
        return False

    state["api_busy"] = True
    return True


# ============================================================
# 构造 system
# ============================================================
def _build_system(period, is_master, username, content, group):
    system = config.AI_RULE_NO_INJECT
    system += "\n" + config.AI_SYSTEM_BASE

    if period == "late":
        system += "\n" + config.AI_SYSTEM_NIGHT
    elif period == "day":
        system += "\n" + config.AI_SYSTEM_DAY

    if is_master:
        system += "\n" + config.AI_SYSTEM_MASTER
        identity = (username or "主人") + "（你的主人）"
    else:
        system += "\n" + config.AI_RULE_NO_MASTER
        identity = (username or "群友") + "（普通群友）"

    system += "\n" + config.AI_RULE_BASE
    system += "\n当前和你说话的是：" + identity

    if _check_time(content):
        system += "\n" + _get_time_text()

    if _check_weather(content):
        from weather import get_weather
        w = get_weather()
        if w:
            system += "\n" + w + "（仅能查北京天气）"

    ctx = _group_context.get(group, [])
    if ctx:
        lines = ["【最近群聊记录，仅供参考】"]
        for uname, text in ctx:
            lines.append(uname + ": " + text)
        system += "\n" + "\n".join(lines)

    return system


def _build_messages(content, period, user_openid, username, history, group):
    is_master = _is_master(user_openid)
    system = _build_system(period, is_master, username, content, group)
    messages = [{"role": "system", "content": system}]
    for uname, u, a in history:
        messages.append({"role": "user", "content": uname + ": " + u})
        if a is not None:
            messages.append({"role": "assistant", "content": a})
        else:
            messages.append({"role": "assistant", "content": "（没回上）"})
    messages.append({
        "role": "user",
        "content": (username or "群友") + ": " + content,
    })
    return messages


# ============================================================
# 调 API
# ============================================================
def _call_api(messages):
    headers = {
        "Authorization": "Bearer " + config.AI_KEY,
        "Content-Type":  "application/json; charset=utf-8",
    }
    body = {
        "model":             config.AI_MODEL,
        "messages":          messages,
        "enable_thinking":   False,
        "temperature":       0.7,
        "top_p":             0.9,
        "max_tokens":        300,
        "frequency_penalty": 0.4,
        "presence_penalty":  0.4,
    }
    data = ujson.dumps(body).encode("utf-8")
    gc.collect()
    try:
        resp = urequests.post(config.AI_URL, data=data, headers=headers)
        text = resp.text
        resp.close()
        result = ujson.loads(text)
        reply = result["choices"][0]["message"]["content"].strip()
        if len(reply) > MAX_REPLY_LEN:
            reply = reply[:MAX_REPLY_LEN]
        log.info("AI 回复: %s", reply)
        return reply
    except Exception as e:
        log.error("AI API 异常: %s: %s", type(e).__name__, e)
        return None
    finally:
        gc.collect()


# ============================================================
# 后台任务
# ============================================================
async def _reply_async(msg, period):
    content     = _strip_mentions(msg["content"])
    group       = msg["group_openid"]
    msg_id      = msg["msg_id"]
    user_openid = msg.get("user_openid")
    username    = msg.get("username")

    state = _get_state(group)
    state["last_call"] = time.ticks_ms()

    try:
        history = list(state["history"])
        messages = _build_messages(content, period, user_openid,
                                   username, history, group)
        await asyncio.sleep(0)
        reply = _call_api(messages)
        if reply:
            from messaging import send_group
            send_group(group, reply, msg_id=msg_id)
            state["last_reply"] = reply
            _push_history(group, username, content, reply)
        else:
            _push_history(group, username, content, None)
            if msg["was_at"] or _is_master(user_openid):
                from messaging import send_group
                send_group(group, random.choice(FALLBACK_REPLIES),
                           msg_id=msg_id)
    finally:
        state["api_busy"] = False


# ============================================================
# 对外接口
# ============================================================
def try_ai(msg):
    if not config.AI_ENABLED:
        return False

    content = _strip_mentions(msg["content"])
    if _has_injection(content):
        log.warning("检测到注入尝试: %r", content[:50])
        from messaging import send_group
        send_group(msg["group_openid"],
                   "喵？（歪头）你在说什么呀",
                   msg_id=msg["msg_id"])
        return True

    period = _get_period()
    if not _should_reply(msg, period):
        return False

    asyncio.create_task(_reply_async(msg, period))
    return True