const BASE = "/api";

async function fetchJSON<T = unknown>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`);
  if (!res.ok) throw new Error(`API ${res.status}: ${path}`);
  return res.json();
}

async function putJSON<T = unknown>(path: string, data: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error(`API ${res.status}: ${path}`);
  return res.json();
}

async function postJSON<T = unknown>(path: string, data?: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: data ? JSON.stringify(data) : undefined,
  });
  if (!res.ok) throw new Error(`API ${res.status}: ${path}`);
  return res.json();
}

// Account
export const getAccountStatus = () => fetchJSON<AccountStatus>("/account/status");
export const getAccountLedger = () => fetchJSON<AccountLedger>("/account/ledger");
export const getPositionsDetailed = () => fetchJSON<DetailedPositionsResponse>("/account/positions/detailed");
export const getRiskBudget = () => fetchJSON<RiskBudget>("/account/risk-budget");
export const resetHWM = (reason: string) =>
  postJSON<ResetHWMResponse>("/account/reset-hwm", { reason });
export const getPrices = (market = "all") => fetchJSON(`/account/prices?market=${market}`);
export const getOrders = () => fetchJSON("/account/orders");

// Health
export const getHealth = () => fetchJSON<HealthData>("/health");

// Daemon
export const getDaemonState = () => fetchJSON<DaemonState>("/daemon/state");
export const getIterators = () => fetchJSON<IteratorsResponse>("/daemon/iterators");
export const toggleIterator = (name: string, enabled: boolean) =>
  putJSON(`/daemon/iterators/${name}`, { enabled });
export const restartDaemon = () => postJSON("/daemon/restart");

// Thesis
export const getAllTheses = () => fetchJSON<ThesesResponse>("/thesis/");
export const getThesis = (market: string) => fetchJSON(`/thesis/${market}`);
export const updateThesis = (market: string, data: Partial<ThesisUpdate>) =>
  putJSON(`/thesis/${market}`, data);

// Config
export const listConfigs = () => fetchJSON<ConfigListResponse>("/config/");
export const getConfig = (filename: string) => fetchJSON(`/config/${filename}`);
export const updateConfig = (filename: string, data: unknown) =>
  putJSON(`/config/${filename}`, { data });

// Watchlist
export const getWatchlist = () => fetchJSON("/watchlist/");

// Authority
export const getAuthority = () => fetchJSON("/authority/");
export const setAuthority = (asset: string, level: string, note = "") =>
  putJSON(`/authority/${asset}`, { level, note });

// Logs
export const getLogSources = () => fetchJSON("/logs/sources");
export const getLogHistory = (source: string, lines = 200) =>
  fetchJSON(`/logs/history?source=${source}&lines=${lines}`);

// News
export const getCatalysts = (limit = 50) => fetchJSON(`/news/catalysts?limit=${limit}`);

// Charts
export const getCandles = (coin: string, interval = "1h", limit = 500) =>
  fetchJSON<CandleResponse>(`/charts/candles/${coin}?interval=${interval}&limit=${limit}`);
export const getCandleMeta = (coin: string) =>
  fetchJSON(`/charts/candles/${coin}/meta`);
export const getChartMarkers = (market: string, lookbackH = 72) =>
  fetchJSON<ChartMarkersResponse>(`/charts/${market}/markers?lookback_h=${lookbackH}`);
export const getChartOverlay = (market: string, lookbackH = 24) =>
  fetchJSON<ChartOverlayResponse>(`/charts/${market}/overlay?lookback_h=${lookbackH}`);

// Strategies
export const getStrategies = () => fetchJSON<StrategiesResponse>("/strategies/");
export const getOilBotState = () => fetchJSON<OilBotStateResponse>("/strategies/oil-botpattern/state");
export const getOilBotJournal = (limit = 20) => fetchJSON<OilBotJournalResponse>(`/strategies/oil-botpattern/journal?limit=${limit}`);
export const getOilBotConfig = () => fetchJSON<OilBotConfigResponse>("/strategies/oil-botpattern/config");

// Types
export interface AccountStatus {
  equity: number;
  positions: Position[];
  spot: SpotBalance[];
}

export interface Position {
  coin: string;
  szi: string;
  entryPx: string;
  positionValue: string;
  unrealizedPnl: string;
  returnOnEquity: string;
  leverage: { type: string; value: number };
  liquidationPx: string | null;
  marginUsed: string;
  maxLeverage: number;
}

export interface SpotBalance {
  coin: string;
  total: number;
  account: string;
}

export interface HealthData {
  processes: {
    daemon: ProcessStatus;
    telegram_bot: ProcessStatus;
    vault_rebalancer: ProcessStatus;
  };
  daemon: {
    tier: string;
    tick_count: number;
    daily_pnl: number;
    total_trades: number;
  };
  telemetry: Record<string, unknown>;
  heartbeat: {
    escalation_level: number;
    failure_count: number;
  };
  tools_health: Record<string, unknown>;
}

export interface ProcessStatus {
  running: boolean;
  pid: number | null;
}

export interface DaemonState {
  tier: string;
  tick_count: number;
  daily_pnl: number;
  total_trades: number;
  pid: number | null;
  pid_alive: boolean;
}

export interface IteratorsResponse {
  iterators: Iterator[];
  valid_tiers: string[];
}

export interface Iterator {
  name: string;
  tiers: string[];
  enabled: boolean;
  has_config: boolean;
}

export interface ThesesResponse {
  theses: Record<string, ThesisData>;
}

export interface ThesisData {
  market: string;
  direction: string;
  conviction: number;
  effective_conviction: number;
  thesis_summary: string;
  age_hours: number;
  needs_review: boolean;
  is_stale: boolean;
  take_profit_price: number | null;
  invalidation_conditions: string[];
  tactical_notes: string;
}

export interface ThesisUpdate {
  direction: string;
  conviction: number;
  thesis_summary: string;
  take_profit_price: number | null;
  invalidation_conditions: string[];
  tactical_notes: string;
}

export interface ConfigListResponse {
  configs: ConfigMeta[];
}

export interface ConfigMeta {
  filename: string;
  type: string;
  size_bytes: number;
  modified: number;
}

// Strategy types
export interface SubSystemState {
  id: number;
  name: string;
  label: string;
  enabled: boolean;
  has_config: boolean;
}

export interface StrategyBrakes {
  daily: string | null;
  weekly: string | null;
  monthly: string | null;
}

export interface StrategyInfo {
  id: string;
  name: string;
  enabled: boolean;
  decisions_only: boolean;
  shadow_mode: boolean;
  short_legs_enabled: boolean;
  sub_system_count: number;
  sub_systems: SubSystemState[];
  brakes_tripped: number;
  brakes: StrategyBrakes;
  instruments: string[];
}

export interface StrategiesResponse {
  strategies: StrategyInfo[];
}

export interface OilBotStateResponse {
  state: {
    brake_cleared_at: string | null;
    daily_brake_tripped_at: string | null;
    daily_realised_pnl_usd: number;
    daily_window_start: string;
    enabled_since: string | null;
    monthly_brake_tripped_at: string | null;
    monthly_realised_pnl_usd: number;
    monthly_window_start: string;
    open_positions: Record<string, unknown>;
    weekly_brake_tripped_at: string | null;
    weekly_realised_pnl_usd: number;
    weekly_window_start: string;
  };
}

export interface JournalEntry {
  id: string;
  instrument: string;
  decided_at: string;
  direction: string;
  action: string;
  edge: number;
  classification: string;
  classifier_confidence: number;
  thesis_conviction: number;
  notes: string;
  gate_results: { name: string; passed: boolean; reason: string }[];
  sizing: {
    edge: number;
    rung: number;
    base_pct: number;
    leverage: number;
    target_notional_usd: number;
    target_size: number;
  };
}

export interface OilBotJournalResponse {
  journal: JournalEntry[];
  count: number;
}

export interface OilBotConfigResponse {
  config: Record<string, unknown>;
}

// Alerts & Signals
export const getAlerts = (limit = 50) => fetchJSON<AlertsResponse>(`/alerts?limit=${limit}`);
export const getSignals = (limit = 30) => fetchJSON<SignalsResponse>(`/alerts/signals?limit=${limit}`);
export const getThesisChallenges = (limit = 20) => fetchJSON<ThesisChallengesResponse>(`/alerts/thesis-challenges?limit=${limit}`);
export const getDisruptions = (limit = 20) => fetchJSON<DisruptionsResponse>(`/alerts/disruptions?limit=${limit}`);
export const getSystemErrors = (limit = 20) => fetchJSON<ErrorsResponse>(`/alerts/errors?limit=${limit}`);

export type AlertSeverity = "critical" | "high" | "medium" | "low";
export type AlertType =
  | "thesis_challenge"
  | "conviction_change"
  | "supply_disruption"
  | "bot_pattern"
  | "system_error"
  | "catalyst"
  | "heatmap_zone";

export interface AlertEntry {
  id: string;
  type: AlertType;
  severity: AlertSeverity;
  market: string;
  summary: string;
  detail: string;
  source: string;
  timestamp: string;
  raw: Record<string, unknown>;
}

export interface AlertsResponse {
  alerts: AlertEntry[];
}

export interface SignalsResponse {
  signals: AlertEntry[];
}

export interface ThesisChallengesResponse {
  challenges: AlertEntry[];
}

export interface DisruptionsResponse {
  disruptions: AlertEntry[];
}

export interface ErrorsResponse {
  errors: AlertEntry[];
}

// Charts
export interface Candle {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface CandleResponse {
  coin: string;
  interval: string;
  candles: Candle[];
}

export interface NewsMarker {
  time: number;
  type: "news";
  severity: number;  // 1-5
  category: string;
  headline: string;
  source: string;
  url: string;
  rationale: string;
  expected_direction: string | null;
  stub: boolean;
}

export interface TradeMarker {
  time: number;
  type: "trade";
  action: string;
  market: string;
  detail: Record<string, unknown>;
  reasoning: string;
  outcome: string;
  stub: boolean;
}

export interface LessonMarker {
  time: number;
  type: "lesson";
  lesson_id: number;
  market: string;
  direction: string;
  lesson_type: string;
  outcome: string;
  pnl_usd: number;
  roe_pct: number;
  holding_ms: number;
  conviction_at_open: number | null;
  summary: string;
  tags: string[];
  stub: boolean;
}

export interface CritiqueMarker {
  time: number;
  type: "critique";
  stub: boolean;
  message?: string;          // present only on stub rows
  // Live critique fields (when stub=false)
  instrument?: string;
  direction?: string;
  entry_price?: number;
  entry_qty?: number;
  leverage?: number;
  overall_label?: string;     // "GREAT" | "GOOD" | "MIXED ENTRY" | "RISKY" | etc.
  pass_count?: number;
  warn_count?: number;
  fail_count?: number;
  suggestions?: string[];
}

export interface ChartMarkersResponse {
  market: string;
  lookback_h: number;
  news: NewsMarker[];
  trades: TradeMarker[];
  lessons: LessonMarker[];
  critiques: CritiqueMarker[];
}

// Entry critiques
export interface EntryCritiqueGrade {
  sizing: string;
  sizing_detail: string;
  direction: string;
  direction_detail: string;
  catalyst_timing: string;
  catalyst_detail: string;
  liquidity: string;
  liquidity_detail: string;
  funding: string;
  funding_detail: string;
  pass_count: number;
  warn_count: number;
  fail_count: number;
  overall_label: string;
  suggestions: string[];
}

export interface EntryCritiqueSignals {
  rsi: number | null;
  atr_value: number | null;
  atr_pct: number | null;
  liquidation_cushion_pct: number | null;
  snapshot_flags: string[];
  lesson_ids: number[];
  funding_bps_annualized: number | null;
  thesis_conviction: number | null;
  thesis_direction: string | null;
}

export interface EntryCritique {
  schema_version: number;
  kind: string;
  created_at: string;
  instrument: string;
  direction: string;
  entry_price: number;
  entry_qty: number;
  leverage: number | null;
  notional_usd: number | null;
  equity_usd: number | null;
  actual_size_pct: number | null;
  grade: EntryCritiqueGrade;
  signals: EntryCritiqueSignals;
  degraded: Record<string, string | null>;
}

export interface EntryCritiquesResponse {
  critiques: EntryCritique[];
  total: number;
  market_filter: string | null;
}

export const getEntryCritiques = (limit = 5, market?: string) =>
  fetchJSON<EntryCritiquesResponse>(
    `/critiques/?limit=${limit}${market ? `&market=${market}` : ""}`
  );

export interface LiqZone {
  snapshot_at: string;
  side: "bid" | "ask";
  price_low: number;
  price_high: number;
  centroid: number;
  notional_usd: number;
  distance_bps: number;
  rank: number;
  stub: boolean;
}

export interface ChartOverlayResponse {
  market: string;
  liq_zones: LiqZone[];
  cascades: { stub: boolean; message?: string }[];
  sweep_risk: { score: number; label: string; stub: boolean; message?: string };
}

// ─── Account Ledger (EquityLedger component) ──────────────────────────────────

export interface WalletRow {
  role: string;
  label: string;
  is_vault: boolean;
  total_equity: number;
  spot_usdc: number;
  spot_assets: number;
  native_equity: number;
  xyz_equity: number;
  free_margin: number;
  spot_balances: { coin: string; total: number }[];
}

export interface AccountLedger {
  total_equity: number;
  accounts: WalletRow[];
  unrealized_pnl: Record<string, number>;
  leverage_summary: {
    total_notional: number;
    total_margin: number;
    effective_leverage: number;
  };
  hwm: {
    value: number | null;
    set_at: string | null;
    drawdown_pct: number | null;
  };
  realized_pnl: {
    today: number | null;
    week: number | null;
    inception: number | null;
  };
  funding_today: number | null;
  trade_count_24h: number | null;
}

export interface RiskBudget {
  risk_usd: number | null;
  risk_pct: number | null;
  total_equity: number | null;
  warn_pct: number;
  cap_pct: number;
  status: "safe" | "warning" | "critical" | "error" | "no_equity";
  positions: {
    coin: string;
    entry: number;
    sl: number | null;
    sl_source: string;
    size: number;
    risk_usd: number;
  }[];
}

export interface ResetHWMResponse {
  ok: boolean;
  previous_hwm: number | null;
  new_hwm: number;
  reset_at: string;
  reason: string;
  backup_path: string;
}

export interface DistanceInfo {
  delta: number;
  pct: number | null;
  atrs: number | null;
}

export interface DetailedPosition {
  coin: string;
  szi: string;
  entryPx: string;
  currentPx: number | null;
  positionValue: string;
  marginUsed: string;
  unrealizedPnl: string;
  returnOnEquity: string;
  leverage: { type: string; value: number };
  maxLeverage: number;
  liquidationPx: string | null;
  liq_cushion_pct: number | null;
  liq_atrs: number | null;
  time_to_liq_atrs: number | null;
  sl_px: number | null;
  sl_distance: DistanceInfo | null;
  tp_px: number | null;
  tp_distance: DistanceInfo | null;
  atr: number | null;
  sweep_risk: { score: number; label: string } | null;
  dex: string;
  wallet: string;
  entry_ts: number | null;
  time_held_ms: number | null;
}

export interface DetailedPositionsResponse {
  positions: DetailedPosition[];
}
