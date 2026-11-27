"""JSON 配置读写模块（精简版）。

本模块负责按群组管理服务器配置与在线人数柱状图历史数据：

- 每个群组一个 JSON 文件，文件名为群号；
- 服务器以自增数字 ID 为键，删除后不复用（手动 /mcdel 造成的缺口是预期行为）；
- 本插件使用独立数据目录，从头开始积累数据，不读取、不迁移旧插件数据；
- 数据文件为空或解析失败时自动备份并重建默认配置（自愈）。

维护者: IceeCron (https://github.com/IceeCron)
"""
import asyncio
import copy
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import aiofiles

from astrbot.api import logger

# 当前配置格式版本
CURRENT_VERSION = "3.0"

DEFAULT_CONFIG = {
    "version": CURRENT_VERSION,
    "next_id": 1,
    "servers": {},
    # 多服务器柱状图/趋势数据：{"<server_id>": {"history": [{"ts": int, "count": int}]}}
    "trends": {},
}

# 柱状图历史最大保留条数（对应 /mcdata 允许的最大小时数 168）
MAX_HISTORY_POINTS = 168


# ---------------------------------------------------------------------------
# 文件读写
# ---------------------------------------------------------------------------
# 简单的进程内写锁：避免高并发下多任务同时写同一路径
_PATH_LOCKS: Dict[str, asyncio.Lock] = {}


async def _acquire_path_lock(path: str) -> asyncio.Lock:
    lock = _PATH_LOCKS.get(path)
    if lock is None:
        lock = asyncio.Lock()
        _PATH_LOCKS[path] = lock
    await lock.acquire()
    return lock


async def write_json(json_path: str, new_data: Dict[str, Any]) -> None:
    """异步写入 JSON 数据到文件（临时文件 + 原子替换，避免 0KB 截断）。"""
    lock = await _acquire_path_lock(json_path)
    try:
        dest = Path(json_path)
        dest.parent.mkdir(parents=True, exist_ok=True)

        tmp_path = dest.with_suffix(dest.suffix + ".tmp")
        payload = json.dumps(new_data, indent=4, ensure_ascii=False)

        async with aiofiles.open(tmp_path, "w", encoding="utf-8") as f:
            await f.write(payload)
            try:
                await f.flush()  # type: ignore[attr-defined]
            except Exception:
                pass

        os.replace(str(tmp_path), str(dest))
        logger.info(f"成功写入JSON文件(原子替换): {json_path}")
    except Exception as e:
        logger.error(f"写入JSON文件失败: {e}")
        raise IOError(f"写入JSON文件失败: {e}")
    finally:
        try:
            lock.release()
        except Exception:
            pass


async def _backup_corrupt_file(json_path: str, suffix: str = "corrupt") -> None:
    """备份疑似损坏的 JSON 文件，避免自愈时直接覆盖原数据。"""
    try:
        p = Path(json_path)
        if not p.exists():
            return
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_path = p.with_name(f"{p.stem}.{suffix}-{ts}{p.suffix}")
        try:
            if p.stat().st_size > 0:
                os.replace(str(p), str(backup_path))
                logger.warning(f"已备份疑似损坏的 JSON 档: {backup_path}")
            else:
                logger.warning(f"JSON 档为空，跳过备份: {json_path}")
        except PermissionError:
            async with aiofiles.open(p, "rb") as rf, aiofiles.open(backup_path, "wb") as wf:
                await wf.write(await rf.read())
            logger.warning(f"已复制备份疑似损坏的 JSON 档: {backup_path}")
    except Exception as e:
        logger.error(f"备份疑似损坏 JSON 档失败: {e}")


async def read_json(json_path: str) -> Dict[str, Any]:
    """异步读取 JSON 文件内容，自动完成格式自愈。

    - 文件不存在 / 为空 / 解析失败 → 备份后重建默认配置；
    - 读取后补全缺失的结构键（version / next_id / servers / trends）。
    """
    try:
        path = Path(json_path)
        if not path.exists():
            logger.info(f"JSON文件不存在，创建新文件: {json_path}")
            fresh = copy.deepcopy(DEFAULT_CONFIG)
            await write_json(json_path=json_path, new_data=fresh)
            return fresh

        # 若存在临时文件残留，忽略它（由原子替换保证最终一致）
        tmp = path.with_suffix(path.suffix + ".tmp")
        if tmp.exists():
            logger.warning(f"检测到临时文件残留，将忽略并继续读取正式文件: {json_path}")

        async with aiofiles.open(json_path, "r", encoding="utf-8") as f:
            content = await f.read()

        # 空文件/全空白 → 自愈
        if content is None or not content.strip():
            logger.error(f"JSON为空或仅空白，启动自愈: {json_path}")
            await _backup_corrupt_file(json_path, suffix="empty")
            fresh = copy.deepcopy(DEFAULT_CONFIG)
            await write_json(json_path=json_path, new_data=fresh)
            return fresh

        logger.debug(f"读取到的JSON内容（{len(content)} 字节）")
        data = json.loads(content)
        if not isinstance(data, dict):
            raise ValueError("JSON 顶层结构不是对象")

        # 确保数据结构键齐全
        if "version" not in data:
            data["version"] = CURRENT_VERSION
        if "next_id" not in data:
            data["next_id"] = 1
        if "servers" not in data or not isinstance(data.get("servers"), dict):
            data["servers"] = {}
        if "trends" not in data or not isinstance(data.get("trends"), dict):
            data["trends"] = {}

        try:
            servers_cnt = len(data.get("servers", {}))
            trends_cnt = sum(len((v or {}).get("history", [])) for v in data.get("trends", {}).values())
            logger.info(f"成功读取JSON文件: {json_path}, servers={servers_cnt}, trends_points={trends_cnt}")
        except Exception:
            logger.info(f"成功读取JSON文件: {json_path}")
        return data
    except json.JSONDecodeError as e:
        logger.error(f"JSON解析失败: {e}, 将尝试备份并恢复默认配置，路径: {json_path}")
        try:
            await _backup_corrupt_file(json_path, suffix="invalid")
            fresh = copy.deepcopy(DEFAULT_CONFIG)
            await write_json(json_path=json_path, new_data=fresh)
            return fresh
        except Exception as ie:
            logger.error(f"自愈失败: {ie}")
            raise json.JSONDecodeError(f"JSON解析失败且自愈失败: {e}", e.doc, e.pos)
    except Exception as e:
        logger.error(f"读取JSON文件失败: {e}, 文件路径: {json_path}")
        raise IOError(f"读取JSON文件失败: {e}")


# ---------------------------------------------------------------------------
# 服务器增删改查
# ---------------------------------------------------------------------------
def get_server_by_name(data: Dict[str, Any], name: str) -> Optional[Tuple[str, Dict[str, Any]]]:
    """通过服务器名称查找服务器信息，返回 (id, server_info) 或 None。"""
    servers = data.get("servers", {})
    for server_id, server_info in servers.items():
        if server_info.get("name") == name:
            return server_id, server_info
    return None


async def add_data(json_path: str, name: str, host: str) -> bool:
    """添加新的服务器，ID 自增且不复用已删除的 ID。"""
    try:
        data = await read_json(json_path)

        existing_server = get_server_by_name(data, name)
        if existing_server:
            logger.warning(f"服务器名称已存在: {name} (ID: {existing_server[0]})")
            return False

        servers = data.get("servers", {})
        used_ids = set()
        for k in servers.keys():
            try:
                used_ids.add(int(k))
            except (TypeError, ValueError):
                continue

        next_id_val = int(data.get("next_id", 1) or 1)
        max_used = max(used_ids) if used_ids else 0
        # 确保新 ID 大于当前已用最大 ID
        new_id_int = max(next_id_val, max_used + 1)
        server_id = str(new_id_int)

        data["next_id"] = new_id_int + 1
        data["servers"][server_id] = {
            "id": int(server_id),
            "name": name,
            "host": host,
        }

        await write_json(json_path, data)
        logger.info(f"成功添加服务器数据: {name} (ID: {server_id})")
        return True
    except Exception as e:
        logger.error(f"添加服务器数据失败: {e}")
        return False


async def del_data(json_path: str, identifier: str) -> bool:
    """删除服务器（支持通过 ID 或名称），同时清理其柱状图历史。"""
    try:
        data = await read_json(json_path)
        servers = data.get("servers", {})

        server_id = None
        if identifier in servers:
            server_id = identifier
            server_info = servers[identifier]
        else:
            existing_server = get_server_by_name(data, identifier)
            if existing_server:
                server_id, server_info = existing_server

        if server_id is None:
            logger.warning(f"服务器不存在: {identifier}")
            return False

        del servers[server_id]
        # 同步清理该服务器的柱状图历史，避免残留孤儿数据
        data.get("trends", {}).pop(str(server_id), None)

        await write_json(json_path, data)
        logger.info(f"成功删除服务器数据: {server_info['name']} (ID: {server_id})")
        return True
    except Exception as e:
        logger.error(f"删除服务器数据失败: {e}")
        return False


async def update_data(json_path: str, identifier: str, new_name: Optional[str] = None, new_host: Optional[str] = None) -> bool:
    """更新服务器信息（支持通过 ID 或名称更新名称/地址）。"""
    try:
        data = await read_json(json_path)
        servers = data.get("servers", {})

        server_id = None
        server_info = None
        if identifier in servers:
            server_id = identifier
            server_info = servers[identifier]
        else:
            existing_server = get_server_by_name(data, identifier)
            if existing_server:
                server_id, server_info = existing_server

        if not server_info:
            logger.warning(f"服务器不存在: {identifier}")
            return False

        # 检查新名称是否与其他服务器冲突
        if new_name and new_name != server_info["name"]:
            existing_server = get_server_by_name(data, new_name)
            if existing_server and existing_server[0] != server_id:
                logger.warning(f"服务器名称已存在: {new_name}")
                return False

        if new_name is not None:
            server_info["name"] = new_name
        if new_host is not None:
            server_info["host"] = new_host

        await write_json(json_path, data)
        logger.info(f"成功更新服务器数据: {server_info['name']} (ID: {server_id})")
        return True
    except Exception as e:
        logger.error(f"更新服务器数据失败: {e}")
        return False


async def get_all_servers(json_path: str) -> Dict[str, Dict[str, Any]]:
    """获取所有服务器信息 {id: server_info}。"""
    try:
        data = await read_json(json_path)
        return data.get("servers", {})
    except Exception as e:
        logger.error(f"获取服务器列表失败: {e}")
        return {}


async def get_server_info(json_path: str, identifier: str) -> Optional[Dict[str, Any]]:
    """获取指定服务器的信息（支持通过 ID 或名称查找）。"""
    try:
        data = await read_json(json_path)
        servers = data.get("servers", {})

        if identifier in servers:
            return servers[identifier]

        existing_server = get_server_by_name(data, identifier)
        if existing_server:
            return existing_server[1]

        return None
    except Exception as e:
        logger.error(f"获取服务器信息失败: {e}")
        return None


# ---------------------------------------------------------------------------
# 在线人数柱状图历史
# ---------------------------------------------------------------------------
def _hour_bucket(ts: int) -> int:
    """按小时对齐的时间戳（整点）。"""
    return int(ts // 3600 * 3600)


async def append_trend_point(json_path: str, server_id: str, ts: int, count: int) -> bool:
    """为指定服务器追加或更新某整点的人数，最多保留 MAX_HISTORY_POINTS 条。"""
    try:
        data = await read_json(json_path)
        trends = data.get("trends", {})
        trends.setdefault(str(server_id), {}).setdefault("history", [])
        history = trends[str(server_id)]["history"]
        ts_h = _hour_bucket(ts)
        if history and isinstance(history[-1], dict) and _hour_bucket(history[-1].get("ts", 0)) == ts_h:
            history[-1]["ts"] = ts_h
            history[-1]["count"] = int(count)
        else:
            history.append({"ts": ts_h, "count": int(count)})
        if len(history) > MAX_HISTORY_POINTS:
            history[:] = history[-MAX_HISTORY_POINTS:]
        data["trends"] = trends
        await write_json(json_path, data)
        return True
    except Exception as e:
        logger.error(f"追加柱状图记录失败: {e}")
        return False


async def get_trend_history(json_path: str, server_id: str, hours: int = 24) -> Optional[List[Dict[str, Any]]]:
    """获取指定服务器的柱状图历史记录（最近 N 小时）。"""
    try:
        data = await read_json(json_path)
        trends = data.get("trends", {})
        hist = trends.get(str(server_id), {}).get("history", [])
        if hours > 0:
            hist = hist[-hours:]
        return hist
    except Exception as e:
        logger.error(f"获取柱状图历史失败: {e}")
        return None


async def get_all_trend_histories(json_path: str, hours: int = 24) -> Dict[str, List[Dict[str, Any]]]:
    """获取所有服务器的柱状图历史记录（最近 N 小时）。"""
    try:
        data = await read_json(json_path)
        trends = data.get("trends", {}) or {}
        result: Dict[str, List[Dict[str, Any]]] = {}
        for sid, obj in trends.items():
            hist = (obj or {}).get("history", [])
            if hours > 0:
                hist = hist[-hours:]
            result[str(sid)] = hist
        return result
    except Exception as e:
        logger.error(f"获取所有柱状图历史失败: {e}")
        return {}
