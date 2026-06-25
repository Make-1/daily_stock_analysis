# -*- coding: utf-8 -*-
"""
===================================
美股 Top N 筛选 - 后台调度器
===================================

职责：
1. 在 Web/常驻进程内以守护线程方式运行 `schedule` 库
2. 根据 Config 中 US_SCREENER_ENABLED / US_SCREENER_SCHEDULE_TIME 注册/反注册任务
3. 支持配置热重载：用户在设置页修改后无需重启进程

设计原则：
- 单例：进程内仅一个调度器线程，避免重复触发
- 失败不阻塞：调度任务异常仅记录日志
- 不与一次性 `--schedule` CLI 模式冲突：阻塞式 `run_with_schedule` 由
  CLI 自己运行，这里只服务 Web 常驻模式
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Optional

import schedule

from src.config import get_config

logger = logging.getLogger(__name__)


class USScreenerBackgroundScheduler:
    """美股筛选后台调度器（单例 + 守护线程）。"""

    _instance: Optional["USScreenerBackgroundScheduler"] = None
    _instance_lock = threading.Lock()

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._current_enabled: bool = False
        self._current_time: str = ""
        self._tag = "us_screener_job"

    @classmethod
    def get_instance(cls) -> "USScreenerBackgroundScheduler":
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    # ------------------------------------------------------------------ Job
    @staticmethod
    def _run_screener_job() -> None:
        try:
            from src.services.us_screener_service import USScreenerService

            logger.info("[USScreenerScheduler] 定时任务触发")
            service = USScreenerService()
            items = service.run(send_notification=True)
            logger.info("[USScreenerScheduler] 完成，返回 %d 只", len(items))
        except Exception as exc:
            logger.exception("[USScreenerScheduler] 任务执行失败: %s", exc)

    # ------------------------------------------------------------- Registry
    def _clear_jobs(self) -> None:
        try:
            schedule.clear(self._tag)
        except Exception as exc:
            logger.warning("[USScreenerScheduler] 清理旧任务失败: %s", exc)

    def _register_jobs(self, hhmm: str) -> None:
        for day in ("monday", "tuesday", "wednesday", "thursday", "friday"):
            try:
                getattr(schedule.every(), day).at(hhmm).do(self._run_screener_job).tag(self._tag)
            except Exception as exc:
                logger.error("[USScreenerScheduler] 注册 %s %s 失败: %s", day, hhmm, exc)

    # ----------------------------------------------------------------- API
    def apply_config(self) -> None:
        """根据最新 Config 注册/反注册任务（幂等）。"""
        cfg = get_config()
        enabled = bool(getattr(cfg, "us_screener_enabled", False))
        hhmm = str(getattr(cfg, "us_screener_schedule_time", "11:00") or "11:00").strip()

        with self._lock:
            if enabled == self._current_enabled and hhmm == self._current_time:
                return

            self._clear_jobs()
            if enabled:
                self._register_jobs(hhmm)
                logger.info(
                    "[USScreenerScheduler] 已启用美股定时任务: 每工作日 %s (Top%d)",
                    hhmm, int(getattr(cfg, "us_screener_top_n", 10)),
                )
            else:
                logger.info("[USScreenerScheduler] 美股定时任务已关闭")

            self._current_enabled = enabled
            self._current_time = hhmm

    def _runner_loop(self) -> None:
        logger.info("[USScreenerScheduler] 后台调度线程启动")
        while not self._stop_event.is_set():
            try:
                schedule.run_pending()
            except Exception as exc:
                logger.warning("[USScreenerScheduler] tick 异常: %s", exc)
            self._stop_event.wait(1.0)
        logger.info("[USScreenerScheduler] 后台调度线程退出")

    def start(self) -> None:
        """启动守护线程并按当前配置注册任务（幂等）。"""
        with self._lock:
            if self._thread and self._thread.is_alive():
                # 已运行，刷新配置即可
                pass
            else:
                self._stop_event.clear()
                self._thread = threading.Thread(
                    target=self._runner_loop,
                    name="us-screener-scheduler",
                    daemon=True,
                )
                self._thread.start()
        # 锁外注册以避免重入死锁
        self.apply_config()

    def stop(self) -> None:
        with self._lock:
            self._stop_event.set()
            self._clear_jobs()
            self._current_enabled = False
            self._current_time = ""


def get_us_screener_scheduler() -> USScreenerBackgroundScheduler:
    return USScreenerBackgroundScheduler.get_instance()
