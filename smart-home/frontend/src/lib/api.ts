import type {
  ActivityBucket,
  Automation,
  ControlKey,
  Device,
  LiveState,
  MetricSeries,
  SmartEvent,
  Summary,
  SystemMode,
} from "./types";

export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "";
export const AUTH_EXPIRED = "dashboard-auth-expired";

export const WS_URL = (API_URL || (typeof window !== "undefined" ? window.location.origin : "http://localhost:3000")).replace(/^http/, "ws") + "/ws";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    ...init,
    credentials: "include",
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    cache: "no-store",
  });
  if (!response.ok) {
    if (response.status === 401 && !path.startsWith("/api/auth/") && typeof window !== "undefined") {
      window.dispatchEvent(new Event(AUTH_EXPIRED));
    }
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

export const api = {
  session: () => request<{ authenticated: boolean; configured: boolean }>("/api/auth/session"),
  login: (password: string) => request("/api/auth/login", { method: "POST", body: JSON.stringify({ password }) }),
  logout: () => request("/api/auth/logout", { method: "POST" }),
  fallView: <T>(signal?: AbortSignal) => request<T>("/api/fall/view", { signal }),
  fallAction: (command: string, enabled?: boolean) => request(`/api/fall/${command}`, {
    method: "POST", body: enabled === undefined ? undefined : JSON.stringify({ enabled }),
  }),
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
  events: (limit = 30) => request<SmartEvent[]>(`/api/events?limit=${limit}`),
  automations: () => request<Automation[]>("/api/automations"),
  series: (metrics: string, hours = 6, points = 60) =>
    request<MetricSeries[]>(`/api/series?metrics=${metrics}&hours=${hours}&points=${points}`),
  activity: (hours = 24) => request<ActivityBucket[]>(`/api/activity?hours=${hours}`),

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
