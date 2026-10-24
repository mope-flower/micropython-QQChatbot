# ============================================================
# 私聊记忆：300 轮历史 + 事实画像
# ============================================================

import gc
import time
import ujson
import uasyncio as asyncio

from logger import get_logger

log = get_logger('pvt_mem')

_FILE = 'private_memory.json'

MAX_HISTORY = 300
MAX_LEN     = 500
MAX_TRAITS  = 15
MAX_EVENTS  = 30

_SAVE_THRESHOLD = 20

_history = {}
_facts = {'name': '', 'traits': [], 'events': [], 'updated': 0}

_dirty   = False
_pending = 0


def push(user_openid, user_content, ai_reply):
    global _dirty, _pending
    if not user_openid:
        return
    hist = _history.setdefault(user_openid, [])
    u = (user_content or '')[:MAX_LEN]
    a = ai_reply[:MAX_LEN] if ai_reply else None
    hist.append((u, a))
    while len(hist) > MAX_HISTORY:
        hist.pop(0)
    _dirty = True
    _pending += 1
    if _pending >= _SAVE_THRESHOLD:
        save()


def get(user_openid):
    return list(_history.get(user_openid, []))


def get_all_history():
    result = []
    for hist in _history.values():
        result.extend(hist)
    return result


def clear(user_openid):
    global _dirty
    if user_openid in _history:
        _history[user_openid] = []
        _dirty = True


def get_facts():
    return _facts


def set_facts(name, traits, events):
    global _facts, _dirty
    _facts = {
        'name':    (name or '')[:50],
        'traits':  [t[:30] for t in (traits or []) if t][:MAX_TRAITS],
        'events':  [e[:100] for e in (events or []) if e][:MAX_EVENTS],
        'updated': time.time(),
    }
    _dirty = True


def save():
    global _dirty, _pending
    if not _dirty:
        return
    gc.collect()
    try:
        data = {'history': {}, 'facts': _facts}
        for k, hist in _history.items():
            data['history'][k] = [[u, a] for u, a in hist]
        with open(_FILE, 'w') as f:
            f.write(ujson.dumps(data))
        _dirty = False
        _pending = 0
    except Exception as e:
        log.error('保存失败: %s', e)


def load():
    global _history, _facts
    try:
        with open(_FILE) as f:
            data = ujson.loads(f.read())
        _history = {}
        for k, hist in data.get('history', {}).items():
            _history[k] = [(u, a) for u, a in hist]
        _facts = data.get('facts', {'name': '', 'traits': [], 'events': [], 'updated': 0})
        log.info('记忆加载: %d 用户', len(_history))
    except Exception:
        _history = {}
        _facts = {'name': '', 'traits': [], 'events': [], 'updated': 0}


async def save_loop():
    while True:
        await asyncio.sleep(7200)
        save()