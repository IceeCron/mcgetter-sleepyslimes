# mcgetter-sleepyslimes（自用版）

> 适用于 AstrBot 的 Minecraft 服务器状态查询插件：多服务器管理、实时状态图片、在线人数柱状图，玩家列表自动过滤 carpet 假玩家。

- 维护者：[IceeCron](https://github.com/IceeCron)
- 仓库地址：<https://github.com/IceeCron/mcgetter-sleepyslimes>
- 许可证：[MIT](LICENSE)

---

## 来龙去脉（本插件的由来）

本插件最初基于社区流传的 AstrBot 插件[`astrbot_mcgetter_enhanced`](https://github.com/exynos967/astrbot_mcgetter_enhanced) （mcgetter 增强版，以 AGPL-3.0 协议发布）重构而来。该插件功能完整，但存在一些与个人使用习惯不符、甚至影响体验的问题：

1. **默认图标不符合预期**：原插件为没有自定义图标的服务器准备的默认图标不符合预期；
2. **假玩家占位**：carpet 模组生成的假玩家会出现在玩家列表里，表现为大量名为 `Anonymous Player` 的条目，面板观感极差；
3. **自动清理造成序号空洞**：原插件会在服务器连续一段时间 ping 不通时自动删除该服务器，但 ID 保留占位，导致面板序号不连续（例如 1 之后是 5，6 之后是 9），非常丑陋；
4. 原插件还包含针对某个特定服务器（csu-mc.org）的定制代码，属于无用的历史包袱。

基于以上原因，本人（IceeCron）对该插件进行了完全重构，并作为**个人自用版**发布：

- 完全移除原插件的 GitHub 作者信息，作者与仓库统一指向 [IceeCron](https://github.com/IceeCron)；
- 更换默认服务器图标；
- 新增**常开**的假玩家过滤器（无开关，不提供关闭选项）；
- 完全移除“长时间 ping 不通自动删除服务器”功能，并附带一次性 ID 压缩迁移，修复历史数据中已存在的序号空洞；
- 精简删除作者特定代码，修复若干细节问题。

> 说明：本仓库只用于个人使用与备份。若原插件社区版本仍在使用中，建议同时关注其后续更新。

## 功能特性

- 🎮 **多服务器管理**：添加、删除、查询、更新多个 Minecraft 服务器（按群独立管理）；
- 📊 **实时状态图片**：延迟、版本、在线人数、玩家列表渲染为图片；
- 👥 **假玩家过滤（常开）**：自动过滤 carpet 假人（如 `Anonymous Player`）并修正在线人数；
- 📈 **在线人数柱状图**：按小时自动采样，`/mcdata` 输出最近 N 小时柱状图；
- 🖼️ **默认图标可更换**：无自定义图标的服务器使用 `resource/default_icon.png`（64×64）；
- 🔄 **无缝数据继承**：数据目录沿用旧插件的 `astrbot_mcgetter`，换装后原有配置与柱状图历史自动继承，首次读取时自动完成 ID 压缩迁移；
- 🧹 **无自动删除**：服务器只会在你手动执行 `/mcdel` 时被删除，绝不会被插件悄悄删掉。

### 依赖

插件依赖由 AstrBot 依据 `requirements.txt` 自动安装：

```
mcstatus
aiohttp
pillow
aiofiles
```

## 使用方法

| 命令 | 参数 | 说明 |
|------|------|------|
| `/mchelp` | 无 | 查看帮助信息 |
| `/mc` | 无 | 查询所有保存的服务器状态（图片） |
| `/mcadd` | 服务器名称 服务器地址 [force] | 添加要查询的服务器，`force=True` 跳过预查询强制添加 |
| `/mcget` | 服务器名称/ID | 获取指定服务器的地址信息 |
| `/mcdel` | 服务器名称/ID | 删除指定的服务器 |
| `/mcup` | 服务器名称/ID [新名称] [新地址] | 更新服务器信息 |
| `/mclist` | 无 | 列出所有服务器及其ID |
| `/mcdata` | [服务器名称/ID] [小时数=24] | 输出当前群全部或指定服务器最近N小时在线人数柱状图 |

示例：

```
/mcadd 主服务器 mc.example.com
/mcadd 本地服务器 127.0.0.1:25565 True
/mcget 主服务器
/mcdata 2 48          # ID 为 2 的服务器，最近 48 小时
/mcdata 24            # 全部服务器，最近 24 小时
```

## 假玩家过滤器（常开）

carpet 模组的假玩家在玩家列表里通常表现为 `Anonymous Player`。本插件在获取玩家列表后**始终**执行过滤（无开关，默认常开），并同步修正在线人数，避免“在线 12 人但列表只有 2 个名字”的错位。

过滤规则（`script/get_server_info.py` 顶部常量，可按需扩展）：

| 类型 | 规则（忽略大小写与前后空白） |
|------|------|
| 完全匹配 | `Anonymous Player`、`Anonymous`、`Carpet Bot`、`CarpetBot` |
| 前缀匹配 | `carpet-`、`carpet_`、`carpetplayer_`、`carpet_player_`、`carpetbot_`、`bot_`、`bot-`、`fakeplayer_` |
| 其他 | 空名称一律视为无效条目并过滤 |

在线人数修正逻辑：从服务器上报的在线人数中减去采样列表里可见的假玩家数量（取不小于 0 的值）。当服务器完整返回玩家采样时该值即真实人数；采样被截断时该值不会高估在线人数。

## 关于“自动删除”与 ID 压缩迁移

- 原插件会在服务器连续 10 天查询失败后自动删除该服务器，但 ID 保留占位，导致面板序号出现空洞（如 1、2、11、15、16）。本插件**已完全移除该功能**：服务器只会在你手动 `/mcdel` 时删除；
- 同时内置**一次性 ID 压缩迁移**：升级到本插件后首次读取旧版配置（版本号低于 3.0）时，会自动把服务器 ID 重排为连续的 1..N（例如 1,2,11,15,16 → 1,2,3,4,5），柱状图历史数据随 ID 同步迁移，不会再出现跳号面板；
- 迁移是幂等的：迁移完成后配置版本号变为 `3.0`，之后不会重复执行。手动 `/mcdel` 造成的缺口属于你主动操作的预期结果，插件不会自动补号。

## 数据与配置说明

- 每个群组一个 JSON 文件，存放于 AstrBot 数据目录的 `astrbot_mcgetter` 下，文件名为群号（如 `852974496.json`）；
- 数据目录名**沿用旧插件**，因此从旧插件切换到本插件时，已保存的服务器与柱状图历史无缝继承；
- 配置格式示例：

```json
{
    "version": "3.0",
    "next_id": 6,
    "servers": {
        "1": { "id": 1, "name": "主服务器", "host": "mc.example.com" },
        "2": { "id": 2, "name": "生存服", "host": "survival.example.com" }
    },
    "trends": {
        "1": { "history": [ { "ts": 1795780800, "count": 3 } ] }
    }
}
```

- 版本迁移：
  - 最旧“以服务器名称为键”的格式 → 自动迁移为 ID 键格式；
  - 版本号低于 3.0 → 自动压缩服务器 ID 并清理自动清理功能遗留字段。

## 目录结构

```
mcgetter-sleepyslimes/
├── main.py                    # 插件入口：命令注册与调度
├── metadata.yaml              # 插件元信息
├── requirements.txt           # 依赖
├── README.md
├── LICENSE
├── resource/
│   ├── default_icon.png       # 默认服务器图标（64×64，可自行替换）
│   └── msyh.ttf               # 渲染中文字体
└── script/
    ├── __init__.py
    ├── get_server_info.py     # 状态获取 + 假玩家过滤
    ├── get_img.py             # 服务器信息图片渲染
    ├── bar_chart.py           # 在线人数柱状图渲染
    └── json_operate.py        # 配置读写与版本迁移
```



## 许可证

本项目以 [MIT](LICENSE) 协议发布，版权归属 [IceeCron](https://github.com/IceeCron)。

