# -*- coding: utf-8 -*-
"""
===================================
美股 Top N 筛选 API
===================================

职责：
1. POST /api/v1/us-screener/run    立即触发筛选 + 飞书推送（同步执行）
2. GET  /api/v1/us-screener/logs   查询最近的筛选结果列表
3. GET  /api/v1/us-screener/status 查询配置摘要
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Dict, List, Optional

from dataclasses import asdict
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from src.config import get_config
from src.services.us_screener_log import get_screener_log_store

logger = logging.getLogger(__name__)

router = APIRouter()

# 串行锁：避免同一时刻并发执行多次筛选
_run_lock = threading.Lock()


# ---------------------------------------------------------------- Schemas


class USScreenerRunRequest(BaseModel):
    top_n: Optional[int] = Field(None, ge=1, le=50, description="返回前 N 名，默认读取配置")
    send_notification: bool = Field(True, description="是否推送到飞书")


class USScreenerRunResponse(BaseModel):
    run_id: str
    top_n: int
    items: List[Dict[str, Any]] = Field(default_factory=list)


class USScreenerStatusResponse(BaseModel):
    enabled: bool
    schedule_time: str
    top_n: int
    workers: int
    history_days: int
    universe_size: int
    feishu_configured: bool
    scheduler_running: bool = False
    scheduler_active_time: Optional[str] = None


# ----------------------------------------------------------------- Routes


@router.post(
    "/run",
    response_model=USScreenerRunResponse,
    summary="立即触发美股 Top N 筛选 + 飞书推送",
)
def trigger_run(req: USScreenerRunRequest) -> USScreenerRunResponse:
    if not _run_lock.acquire(blocking=False):
        raise HTTPException(
            status_code=409,
            detail={
                "error": "already_running",
                "message": "已有美股筛选任务正在执行，请稍后再试",
            },
        )
    try:
        from src.services.us_screener_service import USScreenerService

        service = USScreenerService()
        items = service.run(
            top_n=req.top_n,
            send_notification=req.send_notification,
        )
        store = get_screener_log_store()
        recent = store.list_recent(limit=1)
        record = recent[0] if recent else None
        return USScreenerRunResponse(
            run_id=(record or {}).get("id", ""),
            top_n=(record or {}).get("top_n", req.top_n or 10),
            items=[asdict(it) for it in items],
        )
    finally:
        _run_lock.release()


@router.get(
    "/logs",
    summary="获取最近的美股筛选结果列表",
)
def list_logs(limit: int = Query(20, ge=1, le=50)) -> Dict[str, Any]:
    store = get_screener_log_store()
    records = store.list_recent(limit=limit)
    return {"total": len(records), "items": records}


@router.get(
    "/logs/{run_id}",
    summary="获取某次筛选结果详情",
)
def get_log(run_id: str) -> Dict[str, Any]:
    store = get_screener_log_store()
    record = store.get(run_id)
    if record is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "not_found", "message": f"未找到运行记录 {run_id}"},
        )
    return record


@router.get(
    "/status",
    response_model=USScreenerStatusResponse,
    summary="获取美股筛选配置摘要",
)
def get_status() -> USScreenerStatusResponse:
    from src.core.us_stock_screener import resolve_us_universe
    from src.services.us_screener_scheduler import get_us_screener_scheduler

    cfg = get_config()
    universe_size = len(resolve_us_universe(getattr(cfg, "us_screener_universe", None) or None))
    scheduler = get_us_screener_scheduler()
    return USScreenerStatusResponse(
        enabled=bool(getattr(cfg, "us_screener_enabled", False)),
        schedule_time=str(getattr(cfg, "us_screener_schedule_time", "11:00")),
        top_n=int(getattr(cfg, "us_screener_top_n", 10)),
        workers=int(getattr(cfg, "us_screener_workers", 8)),
        history_days=int(getattr(cfg, "us_screener_history_days", 90)),
        universe_size=universe_size,
        feishu_configured=bool(getattr(cfg, "feishu_webhook_url", None)),
        scheduler_running=bool(scheduler._current_enabled),
        scheduler_active_time=scheduler._current_time or None,
    )
