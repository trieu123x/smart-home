import type {
  ActivityBucket,
  Automation,
  ControlKey,
  Device,
  LakePartition,
  LiveState,
  LoginResult,
  MetricSeries,
  MetricStats,
  RollupBucket,
  RollupPoint,
  SmartEvent,
  Summary,
  SystemMode,
} from "./types";

export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const TOKEN_KEY = "sh_token";

// localStorage can throw (private mode, blocked storage); treat that as "no token"
export function getToken(): string | null {
  try {
    return typeof window === "undefined" ? null : window.localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(token: string): void {
  try {
    window.localStorage.setItem(TOKEN_KEY, token);
  } catch {
    // ignore: the session then lasts until the page reloads
  }
}

export function clearToken(): void {
  try {
    window.localStorage.removeItem(TOKEN_KEY);
  } catch {
    // ignore
  }
}

/** Drops the token and sends the user to the login page (full reload resets all state). */
export function redirectToLogin(): void {
  clearToken();
  if (typeof window !== "undefined" && window.location.pathname !== "/login") {
    window.location.href = "/login";
  }
}

/** WebSocket URL with the login token, since browsers cannot set headers on a WebSocket. */
export function wsUrl(): string {
  const base = API_URL.replace(/^http/, "ws") + "/ws";
  const token = getToken();
  return token ? `${base}?token=${encodeURIComponent(token)}` : base;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const token = getToken();
  const response = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(init?.headers ?? {}),
    },
    cache: "no-store",
  });
  if (response.status === 401) {
    redirectToLogin();
    throw new Error("Phiên đăng nhập đã hết hạn");
  }
  if (!response.ok) {
    const text = await response.text();
    // Backend trả {"detail": "..."} -> hiện nguyên văn câu thông báo cho người dùng
    try {
      const parsed = JSON.parse(text) as { detail?: unknown };
      if (typeof parsed.detail === "string") throw new Error(parsed.detail);
    } catch (err) {
      if (err instanceof Error && !(err instanceof SyntaxError)) throw err;
    }
    throw new Error(`${response.status} ${text.slice(0, 200)}`);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

/** Login is not sent through request(): a 401 here means a wrong password, not an expired session. */
async function login(password: string): Promise<LoginResult> {
  const response = await fetch(`${API_URL}/api/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ password }),
    cache: "no-store",
  });
  if (response.status === 401) throw new Error("Sai mật khẩu");
  if (response.status === 429) throw new Error("Thử lại sau 1 phút");
  if (!response.ok) throw new Error(`Không đăng nhập được (${response.status})`);
  return (await response.json()) as LoginResult;
}

export const api = {
  login,
  live: () => request<LiveState>("/api/live"),
  setMode: (mode: SystemMode) =>
    request<LiveState>("/api/mode", { method: "POST", body: JSON.stringify({ mode }) }),
  sendCommand: (device: ControlKey, state: boolean) =>
    request<{ ok: boolean }>("/api/command", {
      method: "POST",
      body: JSON.stringify({ device, state }),
    }),
  summary: () => request<Summary>("/api/summary"),
  devices: () => request<Device[]>("/api/devices"),
  events: (limit = 30, type?: string) =>
    request<SmartEvent[]>(
      `/api/events?limit=${limit}${type ? `&type=${encodeURIComponent(type)}` : ""}`,
    ),
  automations: () => request<Automation[]>("/api/automations"),
  series: (metrics: string, hours = 6, points = 60) =>
    request<MetricSeries[]>(`/api/series?metrics=${metrics}&hours=${hours}&points=${points}`),
  activity: (hours = 24) => request<ActivityBucket[]>(`/api/activity?hours=${hours}`),
  rollups: (metric: string, bucket: RollupBucket = "1h", hours = 168) =>
    request<RollupPoint[]>(
      `/api/analytics/rollups?metric=${encodeURIComponent(metric)}&bucket=${bucket}&hours=${hours}`,
    ),
  stats: (hours = 24) => request<MetricStats[]>(`/api/analytics/stats?hours=${hours}`),
  lake: () => request<LakePartition[]>("/api/analytics/lake"),

  toggleDevice: (id: number, state: boolean) =>
    request<Device>(`/api/devices/${id}/toggle`, {
      method: "POST",
      body: JSON.stringify({ state }),
    }),
  updateDevice: (id: number, payload: Partial<Pick<Device, "name" | "room" | "auto_mode">>) =>
    request<Device>(`/api/devices/${id}`, { method: "PATCH", body: JSON.stringify(payload) }),
  createDevice: (payload: Pick<Device, "code" | "name" | "kind" | "room">) =>
    request<Device>("/api/devices", { method: "POST", body: JSON.stringify(payload) }),
  deleteDevice: (id: number) => request<void>(`/api/devices/${id}`, { method: "DELETE" }),

  ackEvent: (id: number) => request<SmartEvent>(`/api/events/${id}/ack`, { method: "POST" }),
  ackAll: () => request<{ acknowledged: number }>("/api/events/ack-all", { method: "POST" }),

  createAutomation: (payload: Record<string, unknown>) =>
    request<Automation>("/api/automations", { method: "POST", body: JSON.stringify(payload) }),
  updateAutomation: (id: number, payload: Record<string, unknown>) =>
    request<Automation>(`/api/automations/${id}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  deleteAutomation: (id: number) => request<void>(`/api/automations/${id}`, { method: "DELETE" }),
};
