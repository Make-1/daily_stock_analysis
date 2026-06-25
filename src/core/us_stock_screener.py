# -*- coding: utf-8 -*-
"""
===================================
美股技术面筛选模块
===================================

职责：
1. 对一组候选美股（universe）逐个拉取日线数据
2. 使用 `StockTrendAnalyzer` 计算 0-100 综合评分
3. 按评分排序后返回 Top N 可入手标的

设计原则：
- 复用现有数据源（DataFetcherManager）和指标体系（StockTrendAnalyzer），
  不引入平行实现。
- 单只股票失败不影响整体筛选。
- 候选池可通过配置或参数注入，默认提供常见美股龙头列表。
"""

from __future__ import annotations

import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import List, Optional, Sequence

from data_provider import DataFetcherManager
from data_provider.us_index_mapping import is_us_stock_code
from src.stock_analyzer import StockTrendAnalyzer, TrendAnalysisResult, BuySignal

logger = logging.getLogger(__name__)


# 默认候选美股池：覆盖纳指 100 头部 + 标普 500 各行业龙头 + 主流中概 ADR。
# 按行业分组手工维护，避免依赖外部成份股 API；可通过环境变量
# `US_SCREENER_UNIVERSE` 或参数 `universe` 覆盖。
# 规模 161 只，4 worker 下扫描耗时大约 1~2 分钟。
DEFAULT_US_UNIVERSE: List[str] = [
    # 科技 - 巨头
    "AAPL", "MSFT", "GOOGL", "GOOG", "META", "AMZN", "NVDA", "TSLA",
    # 科技 - 半导体
    "AVGO", "AMD", "INTC", "QCOM", "TXN", "MU", "ARM", "SMCI",
    "LRCX", "KLAC", "AMAT", "ASML", "MRVL", "ON", "MCHP", "TSM",
    # 科技 - 软件/SaaS/云
    "ORCL", "ADBE", "CRM", "NFLX", "CSCO", "IBM", "NOW", "INTU",
    "PANW", "CRWD", "FTNT", "CDNS", "SNPS", "WDAY", "MDB", "DDOG",
    "TEAM", "ZS", "NET", "SNOW", "PLTR", "SHOP",
    # 科技 - 互联网/平台/出行
    "PYPL", "UBER", "ABNB", "BKNG", "MELI", "SE", "COIN", "SQ",
    # 金融 - 银行/支付
    "JPM", "BAC", "WFC", "GS", "MS", "C", "V", "MA", "AXP",
    # 金融 - 资管/交易所/评级
    "BLK", "SCHW", "SPGI", "MCO", "ICE", "CME", "BRK.B",
    # 金融 - 保险
    "PGR", "AIG", "MET", "TRV",
    # 医疗 - 制药/生物
    "UNH", "JNJ", "LLY", "PFE", "ABBV", "MRK", "BMY", "AMGN",
    "GILD", "REGN", "VRTX", "BIIB",
    # 医疗 - 医疗器械/服务
    "TMO", "ABT", "DHR", "ISRG", "MDT", "SYK", "BSX", "CVS", "ELV",
    # 消费 - 必选/零售
    "WMT", "COST", "TGT", "PG", "KO", "PEP", "MDLZ", "CL", "KHC",
    "PM", "MO",
    # 消费 - 可选/零售
    "HD", "LOW", "MCD", "SBUX", "NKE", "DIS", "CMG",
    # 能源
    "XOM", "CVX", "COP", "SLB", "EOG", "OXY",
    # 工业/国防/物流
    "CAT", "BA", "GE", "HON", "RTX", "LMT", "NOC", "DE", "UNP",
    "UPS", "FDX",
    # 原材料
    "LIN", "SHW", "APD", "FCX", "NEM",
    # 通信/媒体
    "T", "VZ", "TMUS", "CMCSA", "CHTR",
    # 公用事业
    "NEE", "SO", "DUK",
    # REITs
    "PLD", "AMT", "EQIX",
    # 中概 ADR
    "BABA", "JD", "PDD", "BIDU", "NIO", "XPEV", "LI", "BILI",
    "TCOM", "TME", "ZTO", "YMM", "BEKE", "FUTU", "TIGR",
]


@dataclass
class ScreenedStock:
    """单只股票筛选结果。"""

    code: str
    signal_score: int = 0
    buy_signal: str = ""
    trend_status: str = ""
    current_price: float = 0.0
    # 均线数值
    ma5: float = 0.0
    ma10: float = 0.0
    ma20: float = 0.0
    ma60: float = 0.0
    bias_ma5: float = 0.0
    bias_ma10: float = 0.0
    bias_ma20: float = 0.0
    # MACD
    macd_dif: float = 0.0
    macd_dea: float = 0.0
    macd_bar: float = 0.0
    macd_signal: str = ""
    # RSI（Wilder 平滑，对齐富途/通达信）
    rsi_6: float = 0.0
    rsi_12: float = 0.0
    rsi_24: float = 0.0
    rsi_signal: str = ""
    # 量能
    volume_status: str = ""
    volume_ratio_5d: float = 0.0
    reasons: List[str] = field(default_factory=list)
    risks: List[str] = field(default_factory=list)
    data_source: str = ""

    @classmethod
    def from_analysis(
        cls,
        code: str,
        result: TrendAnalysisResult,
        data_source: str = "",
    ) -> "ScreenedStock":
        return cls(
            code=code,
            signal_score=int(result.signal_score),
            buy_signal=result.buy_signal.value if isinstance(result.buy_signal, BuySignal)
            else str(result.buy_signal),
            trend_status=result.trend_status.value,
            current_price=float(result.current_price or 0.0),
            ma5=float(result.ma5 or 0.0),
            ma10=float(result.ma10 or 0.0),
            ma20=float(result.ma20 or 0.0),
            ma60=float(result.ma60 or 0.0),
            bias_ma5=float(result.bias_ma5 or 0.0),
            bias_ma10=float(result.bias_ma10 or 0.0),
            bias_ma20=float(result.bias_ma20 or 0.0),
            macd_dif=float(result.macd_dif or 0.0),
            macd_dea=float(result.macd_dea or 0.0),
            macd_bar=float(result.macd_bar or 0.0),
            macd_signal=result.macd_signal,
            rsi_6=float(result.rsi_6 or 0.0),
            rsi_12=float(result.rsi_12 or 0.0),
            rsi_24=float(result.rsi_24 or 0.0),
            rsi_signal=result.rsi_signal,
            volume_status=result.volume_status.value,
            volume_ratio_5d=float(result.volume_ratio_5d or 0.0),
            reasons=list(result.signal_reasons or []),
            risks=list(result.risk_factors or []),
            data_source=data_source,
        )


def resolve_us_universe(
    override: Optional[Sequence[str]] = None,
) -> List[str]:
    """
    解析候选美股池。

    优先级：参数 override > 环境变量 US_SCREENER_UNIVERSE > 默认列表。
    """
    if override:
        codes = [str(c).strip().upper() for c in override if str(c).strip()]
    else:
        env_value = os.getenv("US_SCREENER_UNIVERSE", "").strip()
        if env_value:
            codes = [c.strip().upper() for c in env_value.split(",") if c.strip()]
        else:
            codes = list(DEFAULT_US_UNIVERSE)

    # 仅保留合法美股代码，去重并保持顺序
    seen = set()
    cleaned: List[str] = []
    for code in codes:
        if not is_us_stock_code(code):
            logger.debug("跳过非美股代码: %s", code)
            continue
        if code in seen:
            continue
        seen.add(code)
        cleaned.append(code)
    return cleaned


class USStockScreener:
    """
    基于本系统技术指标的美股筛选器。
    """

    def __init__(
        self,
        fetcher_manager: Optional[DataFetcherManager] = None,
        analyzer: Optional[StockTrendAnalyzer] = None,
        max_workers: int = 8,
        history_days: int = 90,
    ) -> None:
        self.fetcher_manager = fetcher_manager or DataFetcherManager()
        self.analyzer = analyzer or StockTrendAnalyzer()
        self.max_workers = max(1, int(max_workers))
        self.history_days = max(30, int(history_days))

    def _analyze_one(self, code: str) -> Optional[ScreenedStock]:
        try:
            df, source = self.fetcher_manager.get_daily_data(
                stock_code=code,
                days=self.history_days,
            )
        except Exception as exc:
            logger.warning("[USScreener] 获取 %s 日线失败: %s", code, exc)
            return None

        if df is None or df.empty or len(df) < 20:
            logger.info("[USScreener] %s 日线数据不足，跳过", code)
            return None

        try:
            result = self.analyzer.analyze(df, code)
        except Exception as exc:
            logger.warning("[USScreener] 分析 %s 失败: %s", code, exc)
            return None

        return ScreenedStock.from_analysis(code, result, data_source=source)

    def screen(
        self,
        universe: Optional[Sequence[str]] = None,
        top_n: int = 10,
        min_score: Optional[int] = None,
    ) -> List[ScreenedStock]:
        """
        对候选池筛选并返回 Top N。

        Args:
            universe: 候选股票代码（覆盖默认池）。
            top_n: 返回前几名。
            min_score: 可选评分下限（None 表示不过滤）。
        """
        codes = resolve_us_universe(universe)
        if not codes:
            logger.warning("[USScreener] 候选股票池为空")
            return []

        logger.info("[USScreener] 开始筛选 %d 只美股 (workers=%d)", len(codes), self.max_workers)

        results: List[ScreenedStock] = []
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {executor.submit(self._analyze_one, code): code for code in codes}
            for future in as_completed(futures):
                code = futures[future]
                try:
                    item = future.result()
                except Exception as exc:
                    logger.warning("[USScreener] %s 任务异常: %s", code, exc)
                    continue
                if item is None:
                    continue
                if min_score is not None and item.signal_score < int(min_score):
                    continue
                results.append(item)

        results.sort(key=lambda r: r.signal_score, reverse=True)
        top = results[: max(1, int(top_n))]
        logger.info(
            "[USScreener] 筛选完成: 候选=%d 有效=%d 返回Top=%d",
            len(codes), len(results), len(top),
        )
        return top
