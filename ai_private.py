# ============================================================
# 私聊 AI 兜底
# ============================================================

import time

import config
from logger import get_logger
from ai import _call_api, _get_time_text, _check_weather

log = get_logger('ai_pvt')


def handle_private_reply(msg):
    from private_memory import get, push, get_facts

    user_openid = msg.get('user_openid')
    content     = msg.get('content', '').strip()

    history = get(user_openid)
    facts   = get_facts()

    system = config.AI_RULE_NO_INJECT
    system += "\n" + config.AI_PRIVATE_SYSTEM

    fact_lines = []
    if facts.get('name'):
        fact_lines.append('名字：' + facts['name'])
    if facts.get('traits'):
        fact_lines.append('特点：' + '、'.join(facts['traits']))
    if facts.get('events'):
        fact_lines.append('近期：' + '；'.join(facts['events'][-8:]))
    if fact_lines:
        system += "\n\n关于对方的记忆：\n" + "\n".join(fact_lines)

    system += "\n" + _get_time_text()

    if _check_weather(content):
        from weather import get_weather
        w = get_weather()
        if w:
            system += "\n" + w + "（仅能查北京天气）"

    messages = [{'role': 'system', 'content': system}]
    for u, a in history:
        messages.append({'role': 'user', 'content': u})
        if a is not None:
            messages.append({'role': 'assistant', 'content': a})
        else:
            messages.append({'role': 'assistant', 'content': '（没回上）'})
    messages.append({'role': 'user', 'content': content})

    reply = _call_api(messages)

    if reply:
        push(user_openid, content, reply)
    else:
        push(user_openid, content, None)
        reply = '喵……没回上'

    return reply


async def extract_facts():
    from private_memory import (get_all_history, get_facts,
                                set_facts, save)

    history = get_all_history()
    if len(history) < 10:
        log.info('历史太少，跳过')
        return

    recent = history[-80:]
    lines = []
    for u, a in recent:
        lines.append('用户: ' + u)
        if a:
            lines.append('你: ' + a)
    text = '\n'.join(lines)

    current = get_facts()
    current_str = ''
    if current.get('name') or current.get('traits') or current.get('events'):
        current_str = (
            '\n\n已有的记忆：\n'
            '- 名字：' + (current.get('name') or '未知') + '\n'
            '- 特点：' + ('、'.join(current.get('traits', [])) or '无') + '\n'
            '- 事件：' + ('；'.join(current.get('events', [])) or '无')
        )

    prompt = (
        '以下是用户和你的对话：\n'
        + text
        + current_str
        + '\n\n请提取关于用户的长期信息，用 JSON 返回：\n'
        '{"name": "名字或空", '
        '"traits": ["性格/爱好/职业等稳定特点"], '
        '"events": ["近期重要事件"]}\n'
        '规则：\n'
        '- 只记长期有效的信息，不要记闲聊\n'
        '- 结合已有记忆，去重、更新\n'
        '- 不确定的不要记\n'
        '只输出 JSON，不要解释。'
    )

    messages = [
        {'role': 'system', 'content': '你是信息提取助手，只输出 JSON。'},
        {'role': 'user',   'content': prompt},
    ]

    reply = _call_api(messages)
    if not reply:
        return

    data = _parse_json(reply)
    if not data:
        return

    set_facts(
        name   = data.get('name', ''),
        traits = data.get('traits', []),
        events = data.get('events', []),
    )
    save()
    log.info('事实提取完成: name=%s', data.get('name') or '-')


def _parse_json(text):
    import ujson
    try:
        s = text.strip()
        if s.startswith('```'):
            s = s.split('```')[1]
            if s.startswith('json'):
                s = s[4:]
        s = s.strip()
        start = s.find('{')
        end   = s.rfind('}')
        if start < 0 or end <= start:
            return None
        return ujson.loads(s[start:end+1])
    except Exception:
        return None