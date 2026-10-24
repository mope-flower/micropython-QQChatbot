# ============================================================
# 程序入口
# ============================================================

import gc
import time
import machine
import uasyncio as asyncio

import config
import logger
import connection
import messaging
import handler
import plugin_loader
import private_memory

gc.threshold(4096)

log = logger.get_logger('main')


def strip_at_prefix(text):
    text = text.strip()

    if text.startswith('<@'):
        end = text.find('>')
        if end != -1:
            openid = text[2:end]
            if openid == config.BOT_OPENID:
                return text[end + 1:].strip(), True
            return text, False
        return text, False

    if text.startswith('@') and len(text) > 1 and text[1] != ' ':
        for name in config.BOT_NAMES:
            prefix = '@' + name
            if text.startswith(prefix):
                rest = text[len(prefix):]
                if not rest:
                    return '', True
                if rest[0] in ' ,，:：':
                    return rest[1:].strip(), True
                return rest.strip(), True
        return text, False

    return text, False


async def process_event(event):
    op = event.get('op')

    if op == 1:
        await messaging.ack_heartbeat()
        return

    if op != 0 or not event.get('t'):
        return

    t = event['t']
    d = event.get('d', {})

    # 插件事件
    if await plugin_loader.dispatch_event(t, d):
        return

    # 私聊
    if t == 'C2C_MESSAGE_CREATE':
        user_openid = d.get('author', {}).get('user_openid')
        content     = d.get('content', '')
        msg_id      = d.get('id')

        log.info('私聊: %s: %r',
                 user_openid[:8] if user_openid else '?',
                 content[:50])

        if user_openid != config.PRIVATE_MASTER_OPENID:
            log.warning('私聊拒绝: %s',
                        user_openid[:8] if user_openid else '?')
            return

        msg = {
            'content':      content,
            'user_openid':  user_openid,
            'username':     '主人',
            'was_at':       True,
            'group_openid': None,
            'msg_id':       msg_id,
            'mentions':     [],
        }

        reply = handler.handle_private_message(msg)
        if reply:
            messaging.send_user(user_openid, reply, msg_id=msg_id)
        return

    # 群消息
    if t not in ('GROUP_AT_MESSAGE_CREATE', 'GROUP_MESSAGE_CREATE'):
        return

    raw_content = d.get('content', '')
    mentions    = d.get('mentions', [])

    clean_content, was_at_text = strip_at_prefix(raw_content)
    was_at_mentions = any(m.get('bot', False) for m in mentions)
    was_at = was_at_text or was_at_mentions

    msg = {
        'content':      clean_content,
        'was_at':       was_at,
        'group_openid': d.get('group_openid'),
        'msg_id':       d.get('id'),
        'user_openid':  d.get('author', {}).get('member_openid'),
        'username':     d.get('author', {}).get('username'),
        'mentions':     mentions,
    }

    log.info('收到: %s @=%s: %r', msg['username'], was_at, msg['content'])

    reply_text = handler.handle_group_message(msg)

    if reply_text:
        messaging.send_group(msg['group_openid'], reply_text,
                             msg_id=msg['msg_id'])


async def main():
    log.info('=== QQ 机器人启动 ===')

    plugin_loader.load_all()
    private_memory.load()

    if not await connection.connect_wifi():
        return
    connection.sync_time()

    if not connection.fetch_token():
        return
    if not await connection.connect_gateway():
        return

    asyncio.create_task(connection.heartbeat_loop())
    asyncio.create_task(connection.token_refresh_loop())
    asyncio.create_task(connection.watchdog_loop())

    plugin_loader.start_tasks()
    plugin_loader.start_schedules()

    log.info('就绪，插件 %d', len(plugin_loader.PLUGINS))

    while True:
        try:
            event = await messaging.recv_event()
            if event:
                await process_event(event)
        except Exception as e:
            log.error('主循环异常: %s: %s', type(e).__name__, e)
            await asyncio.sleep(5)
            try:
                if await connection.reconnect():
                    continue
            except Exception:
                pass
            await asyncio.sleep(5)
            machine.reset()


asyncio.run(main())