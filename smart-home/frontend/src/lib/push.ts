import { API_URL } from "./api";

export function pushSupported() {
  return typeof window !== "undefined" && "Notification" in window &&
    "serviceWorker" in navigator && "PushManager" in window;
}

function keyToBytes(base64url: string): Uint8Array {
  const base64 = base64url.replace(/-/g, "+").replace(/_/g, "/");
  const decoded = atob(base64.padEnd(Math.ceil(base64.length / 4) * 4, "="));
  return Uint8Array.from(decoded, char => char.charCodeAt(0));
}

export async function currentPush() {
  if (!pushSupported()) return null;
  const worker = await navigator.serviceWorker.getRegistration("/");
  return worker ? worker.pushManager.getSubscription() : null;
}

export async function enablePush() {
  if (!pushSupported()) throw new Error("Trình duyệt chưa hỗ trợ Web Push.");
  // Start the permission prompt from a real click/tap gesture.
  const permission = await Notification.requestPermission();
  if (permission !== "granted") throw new Error("Bạn chưa cấp quyền thông báo.");
  const worker = await navigator.serviceWorker.register("/sw.js", { scope: "/" });
  const keyResponse = await fetch(`${API_URL}/api/push/public-key`, { credentials: "include" });
  if (!keyResponse.ok) throw new Error("Chưa cấu hình VAPID hoặc phiên đăng nhập hết hạn.");
  const { publicKey } = await keyResponse.json() as { publicKey: string };
  const subscription = await worker.pushManager.subscribe({
    userVisibleOnly: true,
    applicationServerKey: keyToBytes(publicKey),
  });
  const response = await fetch(`${API_URL}/api/push/subscribe`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(subscription.toJSON()),
  });
  if (!response.ok) throw new Error("Không lưu được thiết bị nhận thông báo.");
  return subscription;
}

export async function disablePush() {
  const subscription = await currentPush();
  if (!subscription) return;
  const data = subscription.toJSON();
  const response = await fetch(`${API_URL}/api/push/unsubscribe`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!response.ok) throw new Error("Không thể hủy đăng ký từ máy chủ.");
  await subscription.unsubscribe();
}

export async function testPush() {
  const response = await fetch(`${API_URL}/api/push/test`, {
    method: "POST", credentials: "include",
  });
  if (!response.ok) throw new Error(response.status === 429
    ? "Bạn đã thử quá nhiều lần trong một phút." : "Không gửi được thông báo kiểm tra.");
  return response.json() as Promise<{ configured: boolean; sent: number; total: number }>;
}
