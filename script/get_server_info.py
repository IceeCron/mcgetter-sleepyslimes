"""Minecraft 服务器状态获取模块。

通过 mcstatus 异步查询 Java 版服务器状态，并内置“假玩家过滤器”：
carpet 模组生成的假玩家在玩家列表里会表现为 "Anonymous Player" 等名称，
本模块在获取玩家列表后始终执行过滤（常开，无开关），
同时修正在线人数，避免面板出现“在线 N 人但列表只有几个名字”的错位。

维护者: IceeCron (https://github.com/IceeCron)
"""
import asyncio
import base64
import socket
from pathlib import Path

from mcstatus import JavaServer

from astrbot.api import logger

# ---------------------------------------------------------------------------
# 假玩家过滤器配置（常开，无开关）
# ---------------------------------------------------------------------------
# 与名称完全相等（忽略大小写、前后空白）时判定为假玩家
FAKE_PLAYER_EXACT_NAMES = {
    "anonymous player",   # carpet 模组未指定用户名时生成的假玩家
    "anonymous",
    "carpet bot",
    "carpetbot",
}

# 名称以这些前缀开头（忽略大小写）时判定为假玩家
FAKE_PLAYER_PREFIXES = (
    "carpet-",
    "carpet_",
    "carpetplayer_",
    "carpet_player_",
    "carpetbot_",
    "bot_",
    "bot-",
    "fakeplayer_",
)


def is_fake_player(name: str) -> bool:
    """判断一个玩家名称是否为假玩家（carpet 假人等）。

    Args:
        name: 玩家名称（可能为 None 或空字符串）

    Returns:
        是否为假玩家；空名称一律视为无效条目并过滤
    """
    if not name:
        return True
    normalized = str(name).strip().lower()
    if normalized in FAKE_PLAYER_EXACT_NAMES:
        return True
    return normalized.startswith(FAKE_PLAYER_PREFIXES)


def filter_players(names) -> list:
    """过滤玩家名称列表，返回仅含真实玩家的新列表（保持原顺序）。

    Args:
        names: 原始玩家名称列表

    Returns:
        过滤后的玩家名称列表
    """
    return [name for name in names if not is_fake_player(name)]


def _load_default_icon_base64() -> str:
    """读取内置默认服务器图标（resource/default_icon.png）并返回 base64 字符串。"""
    image_path = Path(__file__).resolve().parent.parent / "resource" / "default_icon.png"
    return base64.b64encode(image_path.read_bytes()).decode("utf-8")


def _extract_icon_base64(icon: str) -> str:
    """兼容处理服务器图标字段。

    mcstatus 返回的 favicon 通常形如 "data:image/png;base64,xxxx"，
    部分实现可能直接返回裸 base64，两种情况都要能正确处理。
    """
    if not icon:
        return ""
    if "," in icon:
        return icon.split(",", 1)[1]
    return icon


async def get_server_status(host: str):
    """异步获取指定服务器的状态信息（已内置假玩家过滤）。

    Args:
        host: 服务器地址，如 "mc.example.com" 或 "127.0.0.1:25565"

    Returns:
        包含玩家列表、延迟、人数、版本、图标等字段的字典；
        查询失败时返回 None
    """
    try:
        server = await JavaServer.async_lookup(host)
        status = await server.async_status()

        latency = int(status.latency)
        plays_max = int(status.players.max)
        plays_online_raw = int(status.players.online)
        server_version = status.version.name

        # 服务器图标：优先使用服务器自身图标，缺失时使用内置默认图标
        if status.icon:
            icon_data = _extract_icon_base64(status.icon) or _load_default_icon_base64()
        else:
            icon_data = _load_default_icon_base64()

        # 玩家列表：过滤 carpet 假玩家（常开）
        raw_names = [player.name for player in (status.players.sample or [])]
        players_list = filter_players(raw_names)
        fake_count = len(raw_names) - len(players_list)

        # 在线人数修正：
        # - 若服务器完整返回了玩家采样（sample 长度 == online），减去假玩家即为真实人数；
        # - 若采样被截断，至少减去采样中可见的假玩家数量（真实人数的下限估计）。
        # 无论哪种情况，max(0, online - 可见假玩家) 都不会高估在线人数。
        plays_online = max(0, plays_online_raw - fake_count)

        players_list.sort()

        return {
            "players_list": players_list,    # 过滤后的玩家昵称列表
            "latency": latency,              # 延迟（毫秒）
            "plays_max": plays_max,          # 最大玩家数
            "plays_online": plays_online,    # 过滤假玩家后的在线人数
            "server_version": server_version,
            "icon_base64": icon_data,        # 服务器图标 base64
            "host": host,                    # 服务器录入地址（用于渲染显示）
        }
    except (socket.gaierror, ConnectionRefusedError) as e:
        logger.error(f"连接服务器失败: {e}")
        return None
    except asyncio.TimeoutError:
        logger.error("获取服务器状态超时")
        return None
    except Exception as e:
        logger.error(f"获取服务器状态时发生未知错误: {e}")
        return None
