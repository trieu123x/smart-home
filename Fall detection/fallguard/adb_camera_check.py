"""One-shot diagnostic for Android USB ADB camera (never saves frames)."""
from .adb_camera import _select_device, _run_adb, AdbH264Capture
from .cctv import setting


def main():
    print("==== FALLGUARD ADB USB CHECK ====")
    try:
        serial = _select_device()
        android = _run_adb(["shell", "getprop", "ro.build.version.release"], serial=serial)
        print(f"Device: {serial} | Android: {android}")
        url = setting("CCTV_URL", "adb:back")
        print("Source:", url)
        with_capture = AdbH264Capture(url)
        try:
            ok, frame = with_capture.read()
            if not ok:
                print("[FAIL] Connected to scrcpy-server but got no video frames")
            else:
                print(f"[OK] Decoded frame {frame.shape[1]}x{frame.shape[0]}")
        finally:
            with_capture.release()
    except Exception as exc:
        print("[FAIL]", exc)

if __name__ == "__main__":
    main()
