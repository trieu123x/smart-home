"""Gia lap ESP32 gui du lieu len backend - dung de demo khi chua co thiet bi that.

Chay:  python simulator.py
Tuy chon: python simulator.py --interval 3 --api http://localhost:8000
"""

import argparse
import math
import random
import time

import httpx

DEFAULT_API = "http://localhost:8000"
DEFAULT_KEY = "esp32-secret-key"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default=DEFAULT_API)
    parser.add_argument("--key", default=DEFAULT_KEY)
    parser.add_argument("--interval", type=float, default=3.0, help="giay giua 2 lan gui")
    args = parser.parse_args()

    client = httpx.Client(base_url=args.api, headers={"X-Device-Key": args.key}, timeout=10)
    tick = 0
    print(f"Dang gui du lieu gia len {args.api} moi {args.interval}s. Ctrl+C de dung.")

    while True:
        tick += 1
        phase = tick / 40 * math.pi
        temperature = round(29.0 + 2.8 * math.sin(phase) + random.uniform(-0.4, 0.4), 2)
        humidity = round(66 + 6 * math.cos(phase) + random.uniform(-1, 1), 1)
        lux = round(max(0.0, 180 + 160 * math.sin(phase - 1) + random.uniform(-25, 25)), 1)
        motion = 1 if random.random() < 0.25 else 0

        payload = {
            "device_code": "esp32-phongkhach",
            "metrics": {
                "temperature": temperature,
                "humidity": humidity,
                "lux": lux,
                "motion": motion,
            },
        }
        _post(client, "/api/ingest/telemetry", payload)
        print(f"#{tick} temp={temperature} hum={humidity} lux={lux} motion={motion}")

        # Thinh thoang gia lap mot cu nga o nha tam
        if random.random() < 0.04:
            _post(
                client,
                "/api/ingest/event",
                {
                    "device_code": "esp32-nhatam",
                    "type": "fall_detected",
                    "severity": "critical",
                    "message": "Gia lap: phat hien nga tai Nha tam",
                },
            )
            print("  -> da gui canh bao NGA")

        time.sleep(args.interval)


def _post(client: httpx.Client, path: str, payload: dict) -> None:
    try:
        response = client.post(path, json=payload)
        if response.status_code >= 400:
            print(f"  loi {response.status_code}: {response.text[:160]}")
    except httpx.HTTPError as exc:
        print(f"  khong ket noi duoc backend: {exc}")


if __name__ == "__main__":
    main()
