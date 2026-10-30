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
  if (!pushSupported()) throw new Error("Thiết bị này chưa hỗ trợ nhận thông báo.");
  // Start the permission prompt from a real click/tap gesture.
  const permission = await Notification.requestPermission();
  if (permission !== "granted") throw new Error("Bạn chưa cấp quyền thông báo.");
  const worker = await navigator.serviceWorker.register("/sw.js", { scope: "/" });
  const keyResponse = await fetch(`${API_URL}/api/push/public-key`, { credentials: "include" });
  if (!keyResponse.ok) throw new Error("Chưa thể bật thông báo. Vui lòng thử đăng nhập lại hoặc liên hệ người quản lý.");
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
  if (!response.ok) throw new Error("Chưa thể tắt thông báo. Vui lòng thử lại.");
  await subscription.unsubscribe();
}
