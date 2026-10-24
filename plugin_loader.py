# ============================================================
# 插件加载器
# 扫描 /plugins 目录，收集 PLUGINS / HOOKS / TASKS / EVENTS / SCHEDULES
# ============================================================

import os
import sys

from logger import get_logger

log = get_logger('loader')

PLUGINS   = []
TASKS     = []
HOOKS     = []
EVENTS    = []
SCHEDULES = []


def load_all():
    if '/plugins' not in sys.path:
        sys.path.append('/plugins')

    try:
        files = os.listdir('/plugins')
    except Exception as e:
        log.error('扫描失败: %s', e)
        return

    files.sort()

    for name in files:
        if not name.endswith('.py'):
            continue
        if name.startswith('_'):
            continue

        mod_name = name[:-3]
        try:
            mod = __import__(mod_name)
        except Exception as e:
            log.error('加载 %s 失败: %s: %s',
                      name, type(e).__name__, e)
            continue

        n = 0
        if hasattr(mod, 'PLUGINS'):
            PLUGINS.extend(mod.PLUGINS)
            n = len(mod.PLUGINS)
        if hasattr(mod, 'TASKS'):
            TASKS.extend(mod.TASKS)
        if hasattr(mod, 'HOOKS'):
            HOOKS.extend(mod.HOOKS)
        if hasattr(mod, 'on_message'):
            HOOKS.append(mod.on_message)
        if hasattr(mod, 'EVENTS'):
            EVENTS.extend(mod.EVENTS)
        if hasattr(mod, 'SCHEDULES'):
            SCHEDULES.extend(mod.SCHEDULES)

        if n > 0:
            log.info('加载 %s: %d 插件', name, n)

    log.info('总数: P%d T%d H%d E%d S%d',
             len(PLUGINS), len(TASKS), len(HOOKS),
             len(EVENTS), len(SCHEDULES))


def dispatch_hooks(msg):
    for hook in HOOKS:
        try:
            hook(msg)
        except Exception as e:
            log.error('钩子异常: %s: %s', type(e).__name__, e)


async def dispatch_event(event_type, data):
    for ev in EVENTS:
        if ev.get('type') != event_type:
            continue
        try:
            result = ev['handler'](data)
            if hasattr(result, '__await__'):
                result = await result
            if result is True:
                return True
        except Exception as e:
            log.error('事件 %s 异常: %s: %s',
                      event_type, type(e).__name__, e)
    return False


def start_tasks():
    import uasyncio as asyncio
    for t in TASKS:
        if not t.get('enabled', True):
            continue
        try:
            asyncio.create_task(t['func']())
            log.info('任务启动: %s', t.get('name', '?'))
        except Exception as e:
            log.error('任务 %s 失败: %s', t.get('name'), e)


def start_schedules():
    import uasyncio as asyncio
    for s in SCHEDULES:
        if not s.get('enabled', True):
            continue
        try:
            asyncio.create_task(_schedule_wrapper(s))
            log.info('调度启动: %s', s.get('name', '?'))
        except Exception as e:
            log.error('调度 %s 失败: %s', s.get('name'), e)


async def _schedule_wrapper(s):
    import time
    import uasyncio as asyncio

    name = s.get('name', '?')
    kind = s.get('type')

    if kind == 'interval':
        interval = s.get('seconds', 60)
        await asyncio.sleep(interval)
        while True:
            try:
                await s['func']()
            except Exception as e:
                log.error('调度 %s 异常: %s', name, e)
            await asyncio.sleep(interval)

    elif kind == 'daily':
        th, tm = s['time']
        last_fired = ''
        while True:
            t = time.localtime(time.time() + 8 * 3600)
            stamp = f'{t[0]}-{t[1]}-{t[2]} {t[3]}:{t[4]}'
            if t[3] == th and t[4] == tm and last_fired != stamp:
                last_fired = stamp
                try:
                    await s['func']()
                except Exception as e:
                    log.error('调度 %s 异常: %s', name, e)
            await asyncio.sleep(30)