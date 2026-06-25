import type React from 'react';
import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { RefreshCw, Rocket, Settings2 } from 'lucide-react';
import {
  ApiErrorAlert,
  AppPage,
  Badge,
  Button,
  Card,
  EmptyState,
  Loading,
  PageHeader,
} from '../components/common';
import { usScreenerApi, type ScreenerRunLog, type ScreenerStatus } from '../api/usScreener';
import { getParsedApiError, type ParsedApiError } from '../api/error';
import { cn } from '../utils/cn';

function formatDateTime(iso?: string | null): string {
  if (!iso) return '--';
  try {
    return new Date(iso).toLocaleString('zh-CN', { hour12: false });
  } catch {
    return iso;
  }
}

const LogDetails: React.FC<{ log: ScreenerRunLog }> = ({ log }) => {
  if (!log.items || log.items.length === 0) {
    return <div className="text-sm text-muted-text px-2 py-3">本次未产生有效筛选结果。</div>;
  }
  const fmt = (v: number | undefined, digits = 2) =>
    Number.isFinite(Number(v)) ? Number(v).toFixed(digits) : '--';
  const fmtSign = (v: number | undefined, digits = 2) => {
    const n = Number(v ?? 0);
    return `${n >= 0 ? '+' : ''}${n.toFixed(digits)}`;
  };
  return (
    <div className="px-2 py-3 space-y-3">
      {/* 排行速览表 */}
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="text-xs text-muted-text">
            <tr className="border-b border-border/40">
              <th className="text-left py-2 px-2">#</th>
              <th className="text-left py-2 px-2">代码</th>
              <th className="text-right py-2 px-2">评分</th>
              <th className="text-left py-2 px-2">信号</th>
              <th className="text-left py-2 px-2">趋势</th>
              <th className="text-right py-2 px-2">现价</th>
              <th className="text-right py-2 px-2">MA5</th>
              <th className="text-right py-2 px-2">MA10</th>
              <th className="text-right py-2 px-2">MA20</th>
              <th className="text-right py-2 px-2">MA60</th>
              <th className="text-right py-2 px-2">RSI6</th>
              <th className="text-right py-2 px-2">RSI12</th>
              <th className="text-right py-2 px-2">RSI24</th>
              <th className="text-right py-2 px-2">DIF</th>
              <th className="text-right py-2 px-2">DEA</th>
              <th className="text-right py-2 px-2">量比</th>
            </tr>
          </thead>
          <tbody>
            {log.items.map((item, idx) => (
              <tr key={`${item.code}-${idx}`} className="border-b border-border/20 hover:bg-hover/40">
                <td className="py-2 px-2 text-secondary-text">{idx + 1}</td>
                <td className="py-2 px-2 font-mono font-semibold text-foreground">{item.code}</td>
                <td className="py-2 px-2 text-right font-mono text-cyan">{item.signalScore}</td>
                <td className="py-2 px-2">{item.buySignal}</td>
                <td className="py-2 px-2">{item.trendStatus}</td>
                <td className="py-2 px-2 text-right font-mono">{fmt(item.currentPrice)}</td>
                <td className="py-2 px-2 text-right font-mono">{fmt(item.ma5)}</td>
                <td className="py-2 px-2 text-right font-mono">{fmt(item.ma10)}</td>
                <td className="py-2 px-2 text-right font-mono">{fmt(item.ma20)}</td>
                <td className="py-2 px-2 text-right font-mono">{fmt(item.ma60)}</td>
                <td className="py-2 px-2 text-right font-mono">{fmt(item.rsi6)}</td>
                <td className="py-2 px-2 text-right font-mono">{fmt(item.rsi12)}</td>
                <td className="py-2 px-2 text-right font-mono">{fmt(item.rsi24)}</td>
                <td
                  className={cn(
                    'py-2 px-2 text-right font-mono',
                    Number(item.macdDif ?? 0) >= 0 ? 'text-success' : 'text-danger',
                  )}
                >
                  {fmtSign(item.macdDif, 4)}
                </td>
                <td
                  className={cn(
                    'py-2 px-2 text-right font-mono',
                    Number(item.macdDea ?? 0) >= 0 ? 'text-success' : 'text-danger',
                  )}
                >
                  {fmtSign(item.macdDea, 4)}
                </td>
                <td className="py-2 px-2 text-right font-mono">{fmt(item.volumeRatio5D)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* 文字详情 */}
      <div className="space-y-3 text-sm">
        {log.items.map((item, idx) => (
          <div key={`detail-${item.code}-${idx}`} className="rounded-lg border border-border/30 px-3 py-2">
            <div className="font-semibold text-foreground mb-1">
              {idx + 1}. {item.code}
              <span className="ml-2 text-xs text-muted-text">
                评分 {item.signalScore} · {item.buySignal} · {item.trendStatus}
              </span>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-x-4 gap-y-1 text-xs text-secondary-text font-mono">
              <div>
                乖离：MA5={fmtSign(item.biasMa5)}% · MA10={fmtSign(item.biasMa10)}% · MA20=
                {fmtSign(item.biasMa20)}%
              </div>
              <div>
                MACD：DIF={fmtSign(item.macdDif, 4)} · DEA={fmtSign(item.macdDea, 4)} · HIST=
                {fmtSign(item.macdBar, 4)}
              </div>
              <div>
                RSI(Wilder)：RSI6={fmt(item.rsi6)} · RSI12={fmt(item.rsi12)} · RSI24={fmt(item.rsi24)}
              </div>
              <div>
                量能：{item.volumeStatus || '-'} · 量比={fmt(item.volumeRatio5D)}
              </div>
            </div>
            {item.macdSignal ? (
              <div className="mt-1 text-xs text-muted-text">MACD 信号：{item.macdSignal}</div>
            ) : null}
            {item.rsiSignal ? (
              <div className="text-xs text-muted-text">RSI 信号：{item.rsiSignal}</div>
            ) : null}
            {item.reasons && item.reasons.length > 0 ? (
              <div className="mt-1 text-xs text-success">
                入手理由：{item.reasons.slice(0, 4).join(' · ')}
              </div>
            ) : null}
            {item.risks && item.risks.length > 0 ? (
              <div className="text-xs text-warning">⚠️ 风险：{item.risks.slice(0, 3).join(' · ')}</div>
            ) : null}
          </div>
        ))}
      </div>
      <div className="text-xs text-muted-text">
        * RSI 已采用 Wilder 平滑（与富途/通达信一致），与第三方软件可能存在 ±0.5 内的微小偏差。
      </div>
    </div>
  );
};

const USScreenerPage: React.FC = () => {
  const [status, setStatus] = useState<ScreenerStatus | null>(null);
  const [logs, setLogs] = useState<ScreenerRunLog[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [isTriggering, setIsTriggering] = useState(false);
  const [error, setError] = useState<ParsedApiError | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [sendNotification, setSendNotification] = useState(true);

  useEffect(() => {
    document.title = '美股筛选 - DSA';
  }, []);

  const fetchAll = useCallback(async () => {
    setIsLoading(true);
    try {
      const [statusResp, logsResp] = await Promise.all([
        usScreenerApi.getStatus(),
        usScreenerApi.getLogs(20),
      ]);
      setStatus(statusResp);
      setLogs(logsResp.items || []);
      setError(null);
    } catch (err) {
      setError(getParsedApiError(err));
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchAll();
  }, [fetchAll]);

  const handleTrigger = useCallback(async () => {
    setIsTriggering(true);
    setToast(null);
    try {
      const resp = await usScreenerApi.run({ sendNotification });
      setToast(`筛选完成，本次返回 ${resp.items?.length ?? 0} 只`);
      if (resp.runId) setExpandedId(resp.runId);
      await fetchAll();
    } catch (err) {
      setError(getParsedApiError(err));
    } finally {
      setIsTriggering(false);
    }
  }, [sendNotification, fetchAll]);

  return (
    <AppPage>
      <PageHeader
        title="美股 Top N 筛选"
        description="基于本系统 MA/MACD/RSI/量价综合评分自动筛选可入手美股；可立即执行并推送到飞书。"
      />

      {error ? <ApiErrorAlert error={error} className="mb-4" /> : null}

      {/* 操作区 */}
      <Card padding="md" className="mb-4">
        <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
          <div className="flex flex-wrap items-center gap-4 text-sm text-secondary-text">
            <div>
              <span className="text-muted-text">定时任务：</span>
              {status?.schedulerRunning ? (
                <Badge variant="success">
                  已运行 · 每工作日 {status.schedulerActiveTime || status.scheduleTime}
                </Badge>
              ) : status?.enabled ? (
                <Badge variant="warning">已启用 · 待生效（请保存设置或重启服务）</Badge>
              ) : (
                <Badge variant="default">未启用</Badge>
              )}
              <Link
                to="/settings"
                className="ml-2 inline-flex items-center gap-1 text-xs text-cyan hover:underline"
              >
                <Settings2 className="h-3 w-3" />
                去设置
              </Link>
            </div>
            <div>
              <span className="text-muted-text">Top N：</span>
              <span className="font-mono text-foreground">{status?.topN ?? '--'}</span>
            </div>
            <div>
              <span className="text-muted-text">候选池：</span>
              <span className="font-mono text-foreground">{status?.universeSize ?? '--'} 只</span>
            </div>
            <div>
              <span className="text-muted-text">飞书：</span>
              {status?.feishuConfigured ? (
                <Badge variant="success">已配置</Badge>
              ) : (
                <Badge variant="warning">未配置</Badge>
              )}
            </div>
          </div>

          <div className="flex items-center gap-3">
            <label className="flex items-center gap-2 text-sm text-secondary-text cursor-pointer select-none">
              <input
                type="checkbox"
                className="h-4 w-4 accent-cyan"
                checked={sendNotification}
                onChange={(e) => setSendNotification(e.target.checked)}
                disabled={isTriggering}
              />
              推送到飞书
            </label>
            <Button
              variant="ghost"
              size="md"
              onClick={() => void fetchAll()}
              disabled={isLoading}
              aria-label="刷新"
            >
              <RefreshCw className={cn('h-4 w-4', isLoading && 'animate-spin')} />
            </Button>
            <Button
              variant="primary"
              size="md"
              isLoading={isTriggering}
              loadingText="筛选中..."
              onClick={() => void handleTrigger()}
              disabled={isTriggering}
            >
              <span className="inline-flex items-center gap-2">
                <Rocket className="h-4 w-4" />
                立即筛选并推送
              </span>
            </Button>
          </div>
        </div>
        {toast ? (
          <div className="mt-3 rounded-lg border border-cyan/20 bg-cyan/5 px-3 py-2 text-sm text-cyan">
            {toast}
          </div>
        ) : null}
      </Card>

      {/* 历史筛选结果 */}
      <Card title="历史筛选结果" subtitle="RECENT RUNS" padding="md">
        {isLoading && logs.length === 0 ? (
          <Loading />
        ) : logs.length === 0 ? (
          <EmptyState
            title="暂无筛选记录"
            description="点击右上角的「立即筛选并推送」开始第一次筛选。"
          />
        ) : (
          <div className="space-y-2">
            {logs.map((log) => {
              const isOpen = expandedId === log.id;
              return (
                <div
                  key={log.id}
                  className="rounded-xl border border-border/40 bg-elevated/30 transition-all hover:border-border/70"
                >
                  <button
                    type="button"
                    onClick={() => setExpandedId(isOpen ? null : log.id)}
                    className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left"
                  >
                    <div className="flex flex-wrap items-center gap-3 min-w-0">
                      <span className="text-sm text-foreground">{formatDateTime(log.createdAt)}</span>
                      <span className="text-xs text-muted-text">
                        Top {log.items?.length ?? 0} / {log.topN}
                      </span>
                    </div>
                    <span className="text-xs text-muted-text shrink-0">
                      {isOpen ? '收起' : '查看详情'}
                    </span>
                  </button>
                  {isOpen ? (
                    <div className="border-t border-border/30 bg-base/30">
                      <LogDetails log={log} />
                    </div>
                  ) : null}
                </div>
              );
            })}
          </div>
        )}
      </Card>
    </AppPage>
  );
};

export default USScreenerPage;
