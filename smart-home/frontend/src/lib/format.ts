import type { SmartEvent } from "./types";

const timeFormatter = new Intl.DateTimeFormat("vi-VN", {
  hour: "2-digit",
  minute: "2-digit",
});

const dateTimeFormatter = new Intl.DateTimeFormat("vi-VN", {
  day: "2-digit",
  month: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
});

export const formatTime = (iso: string) => timeFormatter.format(new Date(iso));

export const formatDateTime = (iso: string) => dateTimeFormatter.format(new Date(iso));

/** "3 phút trước", "2 giờ trước"... */
export function timeAgo(iso: string | null): string {
  if (!iso) return "chưa có dữ liệu";
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (diff < 60) return "vừa xong";
  if (diff < 3600) return `${Math.floor(diff / 60)} phút trước`;
  if (diff < 86400) return `${Math.floor(diff / 3600)} giờ trước`;
  return `${Math.floor(diff / 86400)} ngày trước`;
}

export const formatNumber = (value: number | null | undefined, unit = "", digits = 1) =>
  value === null || value === undefined ? "--" : `${value.toFixed(digits)}${unit}`;

export const OPERATOR_LABEL: Record<string, string> = {
  gt: ">",
  gte: "≥",
  lt: "<",
  lte: "≤",
  eq: "=",
};

export const METRIC_LABEL: Record<string, string> = {
  temperature: "Nhiệt độ",
  humidity: "Độ ẩm",
  lux: "Ánh sáng",
  ldr: "Độ sáng",
  gas: "Gas/khói",
  motion: "Chuyển động",
  fall: "Phát hiện ngã",
};

export const METRIC_UNIT: Record<string, string> = {
  temperature: "°C",
  humidity: "%",
  lux: " lux",
  ldr: "",
  gas: "",
  motion: "",
  fall: "",
};

export const EVENT_LABEL: Record<string, string> = {
  fall_detected: "Phát hiện ngã",
  motion: "Chuyển động",
  gas_alarm: "Cảnh báo gas/khói",
  gas_clear: "Hết cảnh báo gas",
  automation: "Tự động hóa",
  manual: "Điều khiển tay",
  device_online: "Thiết bị kết nối",
  device_offline: "Mất kết nối",
};

/** Keep existing history intact while hiding old internal diagnostics from the public interface. */
export function isSampleEvent(event: SmartEvent): boolean {
  return event.type === "fall_detected" && /\bdu lieu mau\b|dữ liệu mẫu|\bdemo\b/i.test(event.message);
}

export function displayEventMessage(event: SmartEvent): string {
  switch (event.type) {
    case "fall_detected":
      return "Camera phát hiện dấu hiệu té ngã. Vui lòng kiểm tra ngay.";
    case "gas_alarm":
      return "Phát hiện gas hoặc khói bất thường. Hãy kiểm tra khu vực ngay.";
    case "gas_clear":
      return "Mức gas và khói đã trở lại bình thường.";
    case "motion":
      return "Phát hiện chuyển động trong nhà.";
    case "device_offline":
      return `${event.device_name || "Một thiết bị"} mất kết nối.`;
    case "device_online":
      return `${event.device_name || "Thiết bị"} đã kết nối.`;
    case "automation":
      if (/\bluat\b|\bmetric\b|[a-z_]+=\d|luật \[/i.test(event.message)) {
        return `Hệ thống đã điều khiển ${event.device_name || "thiết bị"} theo quy tắc tự động.`;
      }
      return event.message;
    default:
      return event.message;
  }
}
