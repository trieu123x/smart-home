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
import type {
  ActivityBucket,
  Automation,
  Device,
  MetricSeries,
  RealtimeMessage,
  SmartEvent,
  Summary,
} from "@/lib/types";

interface DashboardState {
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
  toggleDevice: (device: Device, state: boolean) => Promise<void>;
  setAutoMode: (device: Device, autoMode: boolean) => Promise<void>;
  ackEvent: (id: number) => Promise<void>;
  ackAll: () => Promise<void>;
}

const DashboardContext = createContext<DashboardState | null>(null);

export function DashboardProvider({ children }: { children: ReactNode }) {
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

  const refresh = useCallback(async () => {
    try {
      const [summaryData, deviceList, eventList, automationList, seriesData, activityData] =
        await Promise.all([
          api.summary(),
          api.devices(),
          api.events(40),
          api.automations(),
          api.series("temperature,humidity,lux", 12, 80),
          api.activity(24),
        ]);
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
  }, []);

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

      socket.onopen = () => setConnected(true);

      socket.onmessage = (raw) => {
        const message = JSON.parse(raw.data as string) as RealtimeMessage;
        if (message.type === "device") {
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
  }, [scheduleRefresh]);

  const toggleDevice = useCallback(async (device: Device, state: boolean) => {
    setDevices((current) =>
      current.map((item) => (item.id === device.id ? { ...item, state } : item)),
    );
    const updated = await api.toggleDevice(device.id, state);
    setDevices((current) => current.map((item) => (item.id === updated.id ? updated : item)));
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
