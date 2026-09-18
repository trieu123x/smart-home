/**
 * Màu biểu đồ - lấy từ bảng màu đã được kiểm tra cho nền tối (#0B1222):
 * đạt ngưỡng tương phản >= 3:1 và tách biệt được với mắt mù màu.
 */
export const CHART_COLORS = {
  temperature: "#d95926", // cam - nóng
  humidity: "#3987e5", // xanh dương - nước
  lux: "#c98500", // vàng - ánh sáng
  motion: "#3987e5",
  automation: "#199e70",
  fall: "#e66767",
} as const;

export const AXIS_COLOR = "#64748b";
export const GRID_COLOR = "rgba(148, 163, 184, 0.12)";
export const SURFACE = "#0B1222";

export const tooltipStyle = {
  backgroundColor: "#121B2F",
  border: "1px solid rgba(255,255,255,0.08)",
  borderRadius: 12,
  fontSize: 12,
  color: "#e2e8f0",
  boxShadow: "0 12px 30px -18px rgba(0,0,0,.9)",
} as const;
