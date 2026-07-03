# -*- coding: utf-8 -*-
"""
===================================
美股 Top N 筛选 + 飞书推送服务
===================================

职责：
1. 调用 `USStockScreener` 完成美股技术面筛选
2. 将 Top N 结果格式化为 Markdown
3. 通过 `FeishuSender` 推送到飞书机器人

设计原则：
- 单一职责：本服务只编排筛选与推送，不重复实现指标或网络层。
- 失败不阻塞：候选池中单只失败、推送失败均不抛异常向上传播。
"""

from __future__ import annotations

import logging
from dataclasses import asdict
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Sequence

from src.config import get_config, Config
from src.core.us_stock_screener import (
    USStockScreener,
    ScreenedStock,
)
from src.notification_sender.feishu_sender import FeishuSender
from src.services.us_screener_log import get_screener_log_store

logger = logging.getLogger(__name__)


# 飞书消息中公司业务摘要的最大长度（过长会让卡片很高、信息密度下降）
_MAX_SUMMARY_CHARS = 220


def _truncate(text: str, limit: int = _MAX_SUMMARY_CHARS) -> str:
    """对长文本做安全截断，避免飞书消息过长。"""
    if not text:
        return ""
    s = " ".join(str(text).split())  # 折叠换行/多空白
    if len(s) <= limit:
        return s
    return s[: max(1, limit - 1)].rstrip() + "…"


def format_topn_markdown(items: Sequence[ScreenedStock], top_n: int) -> str:
    """渲染 Top N 美股筛选结果为飞书 Markdown 文本（含全部指标数值）。"""
    tz_cn = timezone(timedelta(hours=8))
    now = datetime.now(tz_cn).strftime("%Y-%m-%d %H:%M")

    if not items:
        return (
            f"# 🇺🇸 美股技术面 Top{top_n} 筛选\n\n"
            f"_生成时间: {now} (UTC+8)_\n\n"
            "本次筛选未得到符合条件的标的（可能为数据源不可用或评分过低）。"
        )

    lines: List[str] = []
    lines.append(f"# 🇺🇸 美股技术面 Top{top_n} 筛选")
    lines.append("")
    lines.append(
        f"_生成时间: {now} (UTC+8) · RSI 采用 Wilder 平滑（对齐富途/通达信）_"
    )
    lines.append("")
    lines.append("## 排行速览")
    lines.append("| # | 代码 | 名称 | 评分 | 信号 | 趋势 | 现价 | 抛出点位 | 止损位 |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for idx, it in enumerate(items, start=1):
        name_cell = (it.name or "-").replace("|", "/")
        lines.append(
            "| {i} | **{code}** | {name} | {score} | {signal} | {trend} | {price:.2f} | {sell:.2f} | {stop:.2f} |".format(
                i=idx,
                code=it.code,
                name=name_cell,
                score=it.signal_score,
                signal=it.buy_signal,
                trend=it.trend_status,
                price=it.current_price,
                sell=it.sell_target,
                stop=it.stop_loss,
            )
        )

    lines.append("")
    lines.append("## 指标详情")
    for idx, it in enumerate(items, start=1):
        title_name = f" · {it.name}" if it.name else ""
        lines.append(
            f"### {idx}. {it.code}{title_name} （评分 {it.signal_score} · {it.buy_signal}）"
        )
        # 公司简介（行业 + 业务摘要 + 官网），用户最关心"这家公司是做什么的"
        if it.sector or it.industry:
            industry_text = " / ".join(p for p in (it.sector, it.industry) if p)
            lines.append(f"- **行业**：{industry_text}")
        if it.summary:
            lines.append(f"- **公司简介**：{_truncate(it.summary)}")
        if it.website:
            lines.append(f"- **官网**：{it.website}")
        # 抛出点位 / 止损位（用户最关心的执行点位放在前面）
        sell_extra = ""
        if it.current_price > 0 and it.sell_target > 0:
            sell_extra = "（较现价 {pct:+.2f}%）".format(
                pct=(it.sell_target / it.current_price - 1.0) * 100,
            )
        stop_extra = ""
        if it.current_price > 0 and it.stop_loss > 0:
            stop_extra = "（较现价 {pct:+.2f}%）".format(
                pct=(it.stop_loss / it.current_price - 1.0) * 100,
            )
        lines.append(
            "- **抛出点位（止盈）**：{sell:.2f}{sell_extra} · **止损位**：{stop:.2f}{stop_extra}".format(
                sell=it.sell_target, sell_extra=sell_extra,
                stop=it.stop_loss, stop_extra=stop_extra,
            )
        )
        # 均线 + 乖离
        lines.append(
            "- **均线**：MA5={ma5:.2f} · MA10={ma10:.2f} · MA20={ma20:.2f} · MA60={ma60:.2f}".format(
                ma5=it.ma5, ma10=it.ma10, ma20=it.ma20, ma60=it.ma60,
            )
        )
        lines.append(
            "- **乖离率**：bias(MA5)={b5:+.2f}% · bias(MA10)={b10:+.2f}% · bias(MA20)={b20:+.2f}%".format(
                b5=it.bias_ma5, b10=it.bias_ma10, b20=it.bias_ma20,
            )
        )
        # MACD
        lines.append(
            "- **MACD**：DIF={dif:+.4f} · DEA={dea:+.4f} · HIST={bar:+.4f} → {sig}".format(
                dif=it.macd_dif, dea=it.macd_dea, bar=it.macd_bar,
                sig=(it.macd_signal or "-").replace("|", "/").strip(),
            )
        )
        # RSI（三个周期都列出）
        lines.append(
            "- **RSI(Wilder)**：RSI6={r6:.2f} · RSI12={r12:.2f} · RSI24={r24:.2f} → {sig}".format(
                r6=it.rsi_6, r12=it.rsi_12, r24=it.rsi_24,
                sig=(it.rsi_signal or "-").replace("|", "/").strip(),
            )
        )
        # 量能
        lines.append(
            "- **量能**：{status} · 量比(5日)={ratio:.2f}".format(
                status=it.volume_status or "-", ratio=it.volume_ratio_5d,
            )
        )
        if it.reasons:
            lines.append("- **入手理由**：")
            for r in it.reasons[:6]:
                lines.append(f"  - {r}")
        if it.risks:
            lines.append("- ⚠️ **风险提示**：")
            for r in it.risks[:4]:
                lines.append(f"  - {r}")
        lines.append("")

    lines.append("---")
    lines.append(
        "> 指标说明：RSI 已切换为 Wilder 平滑算法，与富途牛牛/通达信/同花顺一致；"
        "由于行情数据源、复权方式与时间窗差异，仍可能与第三方软件有 ±0.5 内的小幅偏差。"
    )
    lines.append("> 本结果仅基于历史日线技术指标，不构成投资建议；请结合基本面与风险偏好自行判断。")
    return "\n".join(lines)


class USScreenerService:
    """美股 Top N 筛选 + 飞书推送服务。"""

    def __init__(self, config: Optional[Config] = None) -> None:
        self.config = config or get_config()

    def run(
        self,
        top_n: Optional[int] = None,
        universe: Optional[Sequence[str]] = None,
        send_notification: bool = True,
    ) -> List[ScreenedStock]:
        """
        执行美股筛选并按需推送，将结果列表写入历史记录。

        Args:
            top_n: 返回的 Top N，默认读取 config.us_screener_top_n
            universe: 候选股票池，默认读取 config.us_screener_universe / 默认池
            send_notification: 是否推送飞书

        Returns:
            排好序的 ScreenedStock 列表。
        """
        cfg = self.config
        n = int(top_n if top_n is not None else getattr(cfg, "us_screener_top_n", 10))
        workers = int(getattr(cfg, "us_screener_workers", 8))
        history_days = int(getattr(cfg, "us_screener_history_days", 90))

        if universe is None:
            cfg_universe = getattr(cfg, "us_screener_universe", None) or []
            universe = cfg_universe or None

        screener = USStockScreener(
            max_workers=workers,
            history_days=history_days,
        )
        items = screener.screen(universe=universe, top_n=n)

        if send_notification and items:
            self._send_to_feishu(items, n)

        # 仅记录每次筛选完成后的列表
        if items:
            get_screener_log_store().add_run(
                items=[asdict(it) for it in items],
                top_n=n,
            )

        return items

    def _send_to_feishu(self, items: List[ScreenedStock], top_n: int) -> bool:
        sender = FeishuSender(self.config)
        if not getattr(self.config, "feishu_webhook_url", None):
            logger.warning("[USScreener] 未配置 FEISHU_WEBHOOK_URL，跳过飞书推送")
            return False
        try:
            content = format_topn_markdown(items, top_n)
            ok = sender.send_to_feishu(content)
            if ok:
                logger.info("[USScreener] 飞书推送成功 (Top%d)", top_n)
            else:
                logger.warning("[USScreener] 飞书推送失败")
            return ok
        except Exception as exc:
            logger.error("[USScreener] 飞书推送异常: %s", exc)
            return False
