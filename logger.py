# ============================================================
# 日志工具
# 级别：DEBUG / INFO / WARNING / ERROR / OFF
# ============================================================

import config

_LEVELS = {
    "DEBUG":   10,
    "INFO":    20,
    "WARNING": 30,
    "ERROR":   40,
    "OFF":     100,
}

_current_level = _LEVELS.get(config.LOG_LEVEL.upper(), 20)


class _Logger:
    def __init__(self, name):
        self.name = name

    def _log(self, level, msg, *args):
        if _LEVELS[level] >= _current_level:
            if args:
                msg = msg % args
            print(f"[{level}] {self.name}: {msg} 喵")

    def debug(self, msg, *args):   self._log("DEBUG", msg, *args)
    def info(self, msg, *args):    self._log("INFO", msg, *args)
    def warning(self, msg, *args): self._log("WARNING", msg, *args)
    def error(self, msg, *args):   self._log("ERROR", msg, *args)


def get_logger(name):
    return _Logger(name)