"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import { WS_URL, api } from "@/lib/api";
import { appendSample, type LiveSample } from "@/lib/sensorLogic";
import type {
  ActivityBucket,
  Automation,
  ControlKey,
  Device,
  LiveState,
  MetricSeries,
  RealtimeMessage,
  SmartEvent,
  Summary,
  SystemMode,
} from "@/lib/types";

interface DashboardState {
  /** Cảm biến + chế độ + kết nối của ESP32 (qua MQTT), cập nhật realtime. */
  live: LiveState | null;
  /** Live samples from the last 5 minutes (in memory only), for the sparklines. */
  liveHistory: LiveSample[];
  summary: Summary | null;
  devices: Device[];
  events: SmartEvent[];
  automations: Automation[];
  series: MetricSeries[];
  activity: ActivityBucket[];
  connected: boolean;
  loading: boolean;
  error: string | null;
  /** Cảnh báo ngã mới nhất chưa được xác nhận - hiện banner đỏ toàn trang. */
  activeFall: SmartEvent | null;
  refresh: () => Promise<void>;
  setMode: (mode: SystemMode) => Promise<void>;
  sendCommand: (device: ControlKey, state: boolean) => Promise<void>;
  toggleDevice: (device: Device, state: boolean) => Promise<void>;
  setAutoMode: (device: Device, autoMode: boolean) => Promise<void>;
  ackEvent: (id: number) => Promise<void>;
  ackAll: () => Promise<void>;
}

const DashboardContext = createContext<DashboardState | null>(null);

const finite = (value: unknown) =>
  typeof value === "number" && Number.isFinite(value) ? value : undefined;

/** Turns a live state into a sparkline sample, or null when the ESP32 has nothing fresh. */
function toSample(state: LiveState): LiveSample | null {
  const s = state.sensors;
  if (!state.esp_online || Object.keys(s).length === 0) return null;
  const gas = finite(s.gas);
  const base = finite(s.gas_base);
  return {
    t: Date.now() - (state.age ?? 0) * 1000,
    temp: finite(s.temp),
    hum: finite(s.hum),
    ldr: finite(s.ldr),
    gas,
    gasDelta: gas !== undefined && base !== undefined ? gas - base : undefined,
    motion: typeof s.motion === "boolean" ? s.motion : undefined,
  };
}

export function DashboardProvider({ children }: { children: ReactNode }) {
  const [live, setLiveState] = useState<LiveState | null>(null);
  const [liveHistory, setLiveHistory] = useState<LiveSample[]>([]);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [devices, setDevices] = useState<Device[]>([]);
  const [events, setEvents] = useState<SmartEvent[]>([]);
  const [automations, setAutomations] = useState<Automation[]>([]);
  const [series, setSeries] = useState<MetricSeries[]>([]);
  const [activity, setActivity] = useState<ActivityBucket[]>([]);
  const [connected, setConnected] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refreshTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  /** Stores the live state and records it in the sparkline buffer. */
  const setLive = useCallback((state: LiveState) => {
    setLiveState(state);
    const sample = toSample(state);
    if (sample) setLiveHistory((current) => appendSample(current, sample));
  }, []);

  const refresh = useCallback(async () => {
    try {
      const [
        summaryData,
        deviceList,
        eventList,
        automationList,
        seriesData,
        activityData,
        liveData,
      ] = await Promise.all([
        api.summary(),
        api.devices(),
        api.events(40),
        api.automations(),
        api.series("temperature,humidity,ldr,gas", 12, 80),
        api.activity(24),
        api.live(),
      ]);
      setLive(liveData);
      setSummary(summaryData);
      setDevices(deviceList);
      setEvents(eventList);
      setAutomations(automationList);
      setSeries(seriesData);
      setActivity(activityData);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Không gọi được API");
    } finally {
      setLoading(false);
    }
  }, [setLive]);

  /** Gộp nhiều tin realtime liên tiếp thành một lần gọi lại API. */
  const scheduleRefresh = useCallback(() => {
    if (refreshTimer.current) clearTimeout(refreshTimer.current);
    refreshTimer.current = setTimeout(() => {
      void refresh();
    }, 800);
  }, [refresh]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  // Kết nối WebSocket, tự động thử lại khi rớt
  useEffect(() => {
    let socket: WebSocket | null = null;
    let retry: ReturnType<typeof setTimeout> | null = null;
    let closed = false;

    const connect = () => {
      socket = new WebSocket(WS_URL);

      socket.onopen = () => {
        setConnected(true);
        // Đồng bộ lại trạng thái ESP32 sau khi (tái) kết nối WebSocket
        api.live().then(setLive).catch(() => undefined);
      };

      socket.onmessage = (raw) => {
        const message = JSON.parse(raw.data as string) as RealtimeMessage;
        if (message.type === "live") {
          setLive(message.data);
        } else if (message.type === "device") {
          const incoming = message.data;
          setDevices((current) =>
            current.some((item) => item.id === incoming.id)
              ? current.map((item) => (item.id === incoming.id ? { ...item, ...incoming } : item))
              : [...current, incoming],
          );
          scheduleRefresh();
        } else if (message.type === "event") {
          setEvents((current) => [message.data, ...current].slice(0, 60));
          scheduleRefresh();
        } else if (message.type === "reading") {
          const { metric, value, ts } = message.data;
          setSeries((current) =>
            current.map((line) =>
              line.metric === metric
                ? { ...line, points: [...line.points, { ts, value }].slice(-80) }
                : line,
            ),
          );
          setSummary((current) =>
            current && (metric === "temperature" || metric === "humidity" || metric === "lux")
              ? { ...current, [metric]: value }
              : current,
          );
        } else if (message.type === "automation") {
          scheduleRefresh();
        }
      };

      socket.onclose = () => {
        setConnected(false);
        if (!closed) retry = setTimeout(connect, 3000);
      };

      socket.onerror = () => socket?.close();
    };

    connect();
    return () => {
      closed = true;
      if (retry) clearTimeout(retry);
      socket?.close();
    };
  }, [scheduleRefresh, setLive]);

  const setMode = useCallback(async (mode: SystemMode) => {
    const updated = await api.setMode(mode);
    setLive(updated);
  }, [setLive]);

  const sendCommand = useCallback(async (device: ControlKey, state: boolean) => {
    await api.sendCommand(device, state);
  }, []);

  const toggleDevice = useCallback(async (device: Device, state: boolean) => {
    setDevices((current) =>
      current.map((item) => (item.id === device.id ? { ...item, state } : item)),
    );
    try {
      const updated = await api.toggleDevice(device.id, state);
      setDevices((current) => current.map((item) => (item.id === updated.id ? updated : item)));
    } catch (err) {
      // Lệnh bị từ chối (vd: đang ở chế độ tự động) -> trả công tắc về trạng thái cũ
      setDevices((current) =>
        current.map((item) => (item.id === device.id ? { ...item, state: device.state } : item)),
      );
      throw err;
    }
  }, []);

  const setAutoMode = useCallback(async (device: Device, autoMode: boolean) => {
    const updated = await api.updateDevice(device.id, { auto_mode: autoMode });
    setDevices((current) => current.map((item) => (item.id === updated.id ? updated : item)));
  }, []);

  const ackEvent = useCallback(async (id: number) => {
    const updated = await api.ackEvent(id);
    setEvents((current) => current.map((item) => (item.id === id ? updated : item)));
    setSummary((current) =>
      current
        ? { ...current, unacknowledged_alerts: Math.max(0, current.unacknowledged_alerts - 1) }
        : current,
    );
  }, []);

  const ackAll = useCallback(async () => {
    await api.ackAll();
    setEvents((current) => current.map((item) => ({ ...item, acknowledged: true })));
    setSummary((current) => (current ? { ...current, unacknowledged_alerts: 0 } : current));
  }, []);

  const activeFall = useMemo(
    () => events.find((event) => event.type === "fall_detected" && !event.acknowledged) ?? null,
    [events],
  );

  const value: DashboardState = {
    live,
    liveHistory,
    summary,
    devices,
    events,
    automations,
    series,
    activity,
    connected,
    loading,
    error,
    activeFall,
    refresh,
    setMode,
    sendCommand,
    toggleDevice,
    setAutoMode,
    ackEvent,
    ackAll,
  };

  return <DashboardContext.Provider value={value}>{children}</DashboardContext.Provider>;
}

export function useDashboard(): DashboardState {
  const context = useContext(DashboardContext);
  if (!context) throw new Error("useDashboard phải nằm trong DashboardProvider");
  return context;
}
