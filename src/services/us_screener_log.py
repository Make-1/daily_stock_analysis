# -*- coding: utf-8 -*-
"""
===================================
美股筛选结果记录存储
===================================

职责：
仅记录每次美股 Top N 筛选**完成后的股票列表**，供前端历史查看。

设计原则：
- 极简：不记录触发源/耗时/候选规模/推送状态/错误信息
- 线程安全，进程内 + JSON 文件持久化（最近 N 条）
- 失败仅 warning，不抛异常向上
"""

from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_DEFAULT_MAX_RECORDS = 50
_DEFAULT_LOG_FILE = "us_screener_runs.json"


@dataclass
class ScreenerRunLog:
    """单次筛选结果记录（仅保存列表本身）。"""

    id: str
    created_at: str            # ISO8601 (UTC+8)
    top_n: int = 10
    items: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class ScreenerLogStore:
    """线程安全的筛选结果存储（进程内 + JSON 文件落盘）。"""

    _instance: Optional["ScreenerLogStore"] = None
    _instance_lock = threading.Lock()

    def __init__(self, log_dir: Optional[str] = None, max_records: int = _DEFAULT_MAX_RECORDS) -> None:
        self._lock = threading.Lock()
        self._max_records = max(5, int(max_records))
        self._records: List[ScreenerRunLog] = []

        log_dir = log_dir or os.getenv("LOG_DIR", "./logs")
        try:
            Path(log_dir).mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            logger.warning("[USScreenerLog] 创建日志目录失败: %s", exc)
        self._log_path = Path(log_dir) / _DEFAULT_LOG_FILE
        self._load_from_disk()

    @classmethod
    def get_instance(cls) -> "ScreenerLogStore":
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    # ------------------------------------------------------------------ I/O
    def _load_from_disk(self) -> None:
        if not self._log_path.exists():
            return
        try:
            raw = self._log_path.read_text(encoding="utf-8")
            data = json.loads(raw or "[]")
            if isinstance(data, list):
                loaded: List[ScreenerRunLog] = []
                for item in data[-self._max_records:]:
                    if not isinstance(item, dict):
                        continue
                    # 仅取兼容字段，向前兼容历史数据
                    try:
                        loaded.append(ScreenerRunLog(
                            id=str(item.get("id") or uuid.uuid4().hex[:12]),
                            created_at=str(item.get("created_at") or item.get("started_at") or ""),
                            top_n=int(item.get("top_n") or 10),
                            items=list(item.get("items") or []),
                        ))
                    except Exception:
                        continue
                self._records = loaded
                logger.info("[USScreenerLog] 已加载历史筛选记录 %d 条", len(loaded))
        except Exception as exc:
            logger.warning("[USScreenerLog] 加载历史记录失败: %s", exc)

    def _flush_to_disk(self) -> None:
        try:
            data = [r.to_dict() for r in self._records]
            self._log_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.warning("[USScreenerLog] 写入记录文件失败: %s", exc)

    # ---------------------------------------------------------------- Helpers
    @staticmethod
    def _now_iso() -> str:
        tz_cn = timezone(timedelta(hours=8))
        return datetime.now(tz_cn).isoformat(timespec="seconds")

    # ----------------------------------------------------------------- API
    def add_run(self, items: List[Dict[str, Any]], top_n: int = 10) -> ScreenerRunLog:
        """记录一次筛选完成后的列表。"""
        with self._lock:
            record = ScreenerRunLog(
                id=uuid.uuid4().hex[:12],
                created_at=self._now_iso(),
                top_n=int(top_n),
                items=list(items or []),
            )
            self._records.append(record)
            if len(self._records) > self._max_records:
                self._records = self._records[-self._max_records:]
            self._flush_to_disk()
            return record

    def list_recent(self, limit: int = 20) -> List[Dict[str, Any]]:
        """按时间倒序返回最近的筛选记录。"""
        with self._lock:
            limit = max(1, min(int(limit), self._max_records))
            return [r.to_dict() for r in reversed(self._records[-limit:])]

    def get(self, run_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            for r in self._records:
                if r.id == run_id:
                    return r.to_dict()
            return None

    def clear(self) -> int:
        with self._lock:
            count = len(self._records)
            self._records = []
            self._flush_to_disk()
            return count


def get_screener_log_store() -> ScreenerLogStore:
    """便捷访问全局记录存储。"""
    return ScreenerLogStore.get_instance()
