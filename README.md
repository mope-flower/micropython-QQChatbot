# 小云雪 QQ 机器人

在 ESP32-S3 上运行的 QQ 机器人，基于 MicroPython 编写。

项目最初是为了个人使用，逐步迭代成一个带插件系统的完整实现。代码量不大，结构尽量保持清晰，适合作为 ESP32 + MicroPython 的网络应用参考。

## 说明

- 这是一个**个人项目**，不是通用框架，API 和结构可能随时调整
- 主要面向 **ESP32-S3 N16R8**（8MB PSRAM），其他型号未测试
- AI 部分依赖外部 API（默认硅基流动），需要自备 Key
- 插件没有沙箱，**只应加载可信的插件**

## 功能

### 群聊

- **命令**：以 `/` 开头（如 `/ping`、`/rem`），部分命令需要 @ 机器人
- **AI 聊天**：非命令消息按规则打分，达到阈值后交给 AI 回复
- **投票禁言**：`/禁言 @某人`，3 人投票后由 AI 判定是否执行
- **入群欢迎**：可配置模板
- **掷骰**：`/r 3d6`、`/r 2d6+3`
- **吃什么**：`/吃什么` 随机推荐

### 私聊

- 仅允许配置中的主人 openid 使用
- `/` 开头触发命令，其余交给 AI
- **短期记忆**：最近 300 轮对话，持久化到 Flash
- **长期事实**：每天 3:00 从对话中提取用户画像（名字、特点、近期事件），存 Flash

### AI

- 默认模型：Qwen3-8B（硅基流动免费档）
- 猫娘人设，提示词集中在 `config.py`
- 区分主人/普通群友，语气不同
- 关键词触发的数据注入：时间、北京天气
- 防注入：关键词过滤 + 提示词约束

### 系统

- WebSocket 长连接，带心跳、看门狗、自动重连
- 每天 4:00 自动重启
- 内存监控（需自行启用插件）

## 硬件要求

| 项 | 要求 |
|---|---|
| 芯片 | ESP32-S3 |
| PSRAM | 8MB（Octal-SPIRAM） |
| Flash | 建议 8MB 以上 |
| 推荐型号 | ESP32-S3 N16R8 |

**注意**：必须刷入带 **Octal-SPIRAM** 支持的 MicroPython 固件。官方通用固件默认不启用，PSRAM 不会被识别。

固件下载：<https://micropython.org/download/ESP32_GENERIC_S3/>  
选择文件名带 `SPIRAM_OCT` 的版本。

刷入后可在 REPL 中确认：

```python
import gc
gc.collect()
print(gc.mem_free())   # 应为几百万
```

## 部署

### 1. 刷固件

```bash
esptool.py --port /dev/ttyUSB0 erase_flash
esptool.py --port /dev/ttyUSB0 --baud 460800 write_flash 0 firmware.bin
```

### 2. 上传文件

用 `mpremote` 或 Thonny 上传以下文件到板子：

```
main.py
config.py
logger.py
connection.py
messaging.py
handler.py
plugin_loader.py
ai.py
ai_private.py
private_memory.py
weather.py
lib/ws.py
plugins/*.py
```

### 3. 配置

复制 `config.example.py` 为 `config.py`，填入：

- WiFi 名称和密码
- QQ 机器人 AppID / ClientSecret / OpenID
- 管理员和主人的 openid
- AI API 地址和 Key
- 其他提示词（可选）

### 4. 重启

```bash
mpremote reset
```

首次启动会扫描 `/plugins` 目录，加载所有 `.py` 插件。

## 配置说明

`config.py` 分为两部分：

### 基础配置

| 项 | 说明 |
|---|---|
| `WIFI_SSID` / `WIFI_PASS` | WiFi 凭据 |
| `APP_ID` / `CLIENT_SECRET` | QQ 开放平台应用凭据 |
| `BOT_OPENID` | 机器人 openid |
| `BOT_NAMES` | 机器人昵称，用于识别手打 @ |
| `ADMIN_USERS` | 管理员 openid 列表 |
| `MASTER_USERS` | 主人 openid 列表（可与管理員重叠） |
| `PRIVATE_MASTER_OPENID` | 私聊主人 openid |
| `AI_URL` / `AI_KEY` / `AI_MODEL` | AI 接口配置 |
| `AI_ENABLED` | AI 总开关 |
| `LOG_LEVEL` | 日志级别：DEBUG / INFO / WARNING / ERROR / OFF |

### AI 提示词

`config.py` 后半部分是 8 段提示词常量：

| 常量 | 用途 |
|---|---|
| `AI_RULE_NO_INJECT` | 防注入约束 |
| `AI_SYSTEM_BASE` | 基础人设 |
| `AI_SYSTEM_NIGHT` | 深夜语气 |
| `AI_SYSTEM_DAY` | 白天语气 |
| `AI_SYSTEM_MASTER` | 主人专属 |
| `AI_RULE_NO_MASTER` | 普通人防误认 |
| `AI_RULE_BASE` | 通用底线 |
| `AI_PRIVATE_SYSTEM` | 私聊人设 |

提示词拼接逻辑在 `ai.py` 的 `_build_system` 中。

## 插件系统

`plugins/` 目录下的 `.py` 文件会在启动时自动扫描加载，每个文件可以导出：

| 变量 | 类型 | 说明 |
|---|---|---|
| `PLUGINS` | list | 命令列表 |
| `HOOKS` | list | 每条消息都执行的函数 |
| `TASKS` | list | 后台协程 |
| `EVENTS` | list | 平台事件监听 |
| `SCHEDULES` | list | 定时任务 |

插件命令支持 `scope` 字段区分群聊/私聊：

- `group`：只在群聊
- `private`：只在私聊
- `both`：群聊 + 私聊

示例参考 `plugins/_template.py` 和 `plugins/README.md`。

### 插件权限说明

插件是直接 import 进主程序的，**没有沙箱**。一个插件可以：

- 读写任意全局状态
- 直接调用 `send_group` / `send_user`
- 阻塞事件循环
- 占用内存

**只加载你信任的插件。**

## 目录结构

```
/
├── main.py              入口
├── config.py            配置与提示词
├── logger.py            日志
├── connection.py        WiFi / WS / 心跳
├── messaging.py         收发
├── handler.py           消息分发
├── plugin_loader.py     插件加载
├── ai.py                群聊 AI
├── ai_private.py        私聊 AI
├── private_memory.py    私聊记忆
├── weather.py           北京天气
├── LICENSE
├── lib/
│   └── ws.py            WebSocket 客户端
└── plugins/
    ├── README.md
    ├── _template.py
    ├── ping.py
    ├── help.py
    ├── hello.py
    ├── dice.py
    ├── ate.py
    ├── ctx.py
    ├── mute.py
    ├── admin.py
    ├── welcome.py
    └── memory.py
```

## 已知限制

- **单线程**：AI 请求通过 `urequests` 同步执行，会阻塞事件循环数秒。多个群同时触发 AI 时会排队
- **插件无沙箱**：见上文
- **记忆不跨设备**：`private_memory.json` 只存在板子上
- **AI 稳定性依赖模型**：8B 模型在长提示词、复杂指令下可能不稳定
- **私聊需要单独开通权限**：QQ 开放平台需在后台开启单聊权限，且需要独立的 `user_openid`

## 依赖

- **`lib/ws.py`** — 异步 WebSocket 客户端  
  作者：[vovaman](https://pypi.org/project/micropython-async-websocket-client/)  
  协议：MIT

## 致谢

- [MicroPython](https://micropython.org/)
- [vovaman](https://pypi.org/project/micropython-async-websocket-client/) 提供的 WebSocket 实现
- [Open-Meteo](https://open-meteo.com/) 提供免费天气 API
- [硅基流动](https://siliconflow.cn/) 提供免费 AI 模型

## 许可

[MIT](LICENSE)
