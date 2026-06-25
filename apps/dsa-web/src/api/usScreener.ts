import apiClient from './index';
import { toCamelCase } from './utils';

export type ScreenerItem = {
  code: string;
  signalScore: number;
  buySignal: string;
  trendStatus: string;
  currentPrice: number;
  ma5: number;
  ma10: number;
  ma20: number;
  ma60: number;
  biasMa5: number;
  biasMa10: number;
  biasMa20: number;
  macdDif: number;
  macdDea: number;
  macdBar: number;
  macdSignal?: string;
  rsi6: number;
  rsi12: number;
  rsi24: number;
  rsiSignal?: string;
  volumeStatus?: string;
  volumeRatio5D: number;
  reasons?: string[];
  risks?: string[];
  dataSource?: string;
};

export type ScreenerRunLog = {
  id: string;
  createdAt: string;
  topN: number;
  items: ScreenerItem[];
};

export type ScreenerLogsResponse = {
  total: number;
  items: ScreenerRunLog[];
};

export type ScreenerStatus = {
  enabled: boolean;
  scheduleTime: string;
  topN: number;
  workers: number;
  historyDays: number;
  universeSize: number;
  feishuConfigured: boolean;
  schedulerRunning: boolean;
  schedulerActiveTime?: string | null;
};

export type ScreenerRunResult = {
  runId: string;
  topN: number;
  items: ScreenerItem[];
};

export const usScreenerApi = {
  async run(params: { topN?: number; sendNotification?: boolean } = {}): Promise<ScreenerRunResult> {
    const payload: Record<string, unknown> = {
      send_notification: params.sendNotification ?? true,
    };
    if (params.topN) payload.top_n = params.topN;
    const response = await apiClient.post<Record<string, unknown>>(
      '/api/v1/us-screener/run',
      payload,
    );
    return toCamelCase<ScreenerRunResult>(response.data);
  },

  async getLogs(limit = 20): Promise<ScreenerLogsResponse> {
    const response = await apiClient.get<Record<string, unknown>>(
      '/api/v1/us-screener/logs',
      { params: { limit } },
    );
    return toCamelCase<ScreenerLogsResponse>(response.data);
  },

  async getStatus(): Promise<ScreenerStatus> {
    const response = await apiClient.get<Record<string, unknown>>(
      '/api/v1/us-screener/status',
    );
    return toCamelCase<ScreenerStatus>(response.data);
  },
};
