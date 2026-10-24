# ============================================================
# 消息分发
# 群聊 / 私聊 分开处理
# 插件用 scope 区分：group / private / both
# ============================================================

from logger import get_logger
import plugin_loader

log = get_logger('handler')


def _match_plugin(plugin, content):
    if 'aliases' in plugin:
        for alias in plugin['aliases']:
            if content == alias:
                return True
            if content.startswith(alias + ' '):
                return True
        return False
    return plugin['match'](content)


def handle_group_message(msg):
    plugin_loader.dispatch_hooks(msg)

    content     = msg.get('content', '')
    was_at      = msg.get('was_at', False)
    user_openid = msg.get('user_openid')

    for plugin in plugin_loader.PLUGINS:
        if plugin.get('scope', 'group') not in ('group', 'both'):
            continue
        if not plugin.get('enabled', True):
            continue
        if plugin.get('at_required', True) and not was_at:
            continue

        allowed = plugin.get('allowed_users')
        if allowed is not None and user_openid not in allowed:
            continue

        try:
            if not _match_plugin(plugin, content):
                continue
        except Exception as e:
            log.error('插件 %s 匹配异常: %s', plugin['name'], e)
            continue

        log.info('群聊命中: %s', plugin['name'])
        try:
            return plugin['handler'](msg)
        except Exception as e:
            log.error('插件 %s 执行异常: %s: %s',
                      plugin['name'], type(e).__name__, e)
            return None

    from ai import try_ai
    try_ai(msg)
    return None


def handle_private_message(msg):
    plugin_loader.dispatch_hooks(msg)

    content = msg.get('content', '').strip()

    if content.startswith('/'):
        cmd = content[1:].strip()
        if not cmd:
            return None

        for plugin in plugin_loader.PLUGINS:
            if plugin.get('scope', 'group') not in ('private', 'both'):
                continue
            if not plugin.get('enabled', True):
                continue

            try:
                if not _match_plugin(plugin, cmd):
                    continue
            except Exception as e:
                log.error('插件 %s 匹配异常: %s', plugin['name'], e)
                continue

            log.info('私聊命中: %s', plugin['name'])
            try:
                return plugin['handler'](msg)
            except Exception as e:
                log.error('插件 %s 执行异常: %s: %s',
                          plugin['name'], type(e).__name__, e)
                return None
        return None

    from ai_private import handle_private_reply
    return handle_private_reply(msg)