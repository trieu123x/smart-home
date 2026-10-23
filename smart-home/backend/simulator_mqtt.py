"""Gia lap ESP32 noi qua MQTT - dung giao thuc giong firmware that / ban Django.

Chay:   python simulator_mqtt.py
Tuy chon: --host broker.hivemq.com --prefix ptit_sh_k7x2q9/home/ --interval 1
          --gas-at 20   (sau 20 giay gia lap ro ri gas trong 10 giay)

Trong luc chay, go lenh + Enter:  g = bat/tat ro ri gas | m = bat/tat chuyen dong | d = bat/tat troi toi

Che do auto  : den = co nguoi & troi toi; quat = tu bat khi nong (co tre); loa = khi co gas
Che do manual: den/quat/loa chi doi khi nhan lenh <prefix>cmd/<light|fan|buzzer> = ON | OFF
"""

import argparse
import json
import math
import random
import sys
import threading
import time

import paho.mqtt.client as mqtt

parser = argparse.ArgumentParser()
parser.add_argument("--host", default="broker.hivemq.com")
parser.add_argument("--port", type=int, default=1883)
parser.add_argument("--prefix", default="ptit_sh_k7x2q9/home/")
parser.add_argument("--interval", type=float, default=1.0)
parser.add_argument("--gas-at", type=float, default=0, help="giay bat dau gia lap gas (0 = tat)")
args = parser.parse_args()

P = args.prefix if args.prefix.endswith("/") else args.prefix + "/"
T_SENSORS, T_STATUS, T_MODE, T_CMD = P + "sensors", P + "status", P + "mode", P + "cmd/"

state = {
    "mode": "auto",
    "light": False, "fan": False, "buzzer": False,
    "manual": {"light": False, "fan": False, "buzzer": False},
    "gas_leak": False, "motion": False, "dark": False,
}
lock = threading.Lock()


def on_connect(client, userdata, flags, reason_code, properties=None):
    print("ket noi broker:", reason_code)
    client.subscribe([(T_MODE, 1), (T_CMD + "#", 1)])
    client.publish(T_STATUS, "online", qos=1, retain=True)


def on_message(client, userdata, msg):
    payload = msg.payload.decode().strip()
    with lock:
        if msg.topic == T_MODE and payload in ("auto", "manual"):
            if payload == "manual":  # giu nguyen trang thai hien tai khi sang thu cong
                state["manual"] = {k: state[k] for k in ("light", "fan", "buzzer")}
            state["mode"] = payload
            print("che do ->", payload)
        elif msg.topic.startswith(T_CMD):
            dev = msg.topic[len(T_CMD):]
            if dev in state["manual"] and state["mode"] == "manual":
                state["manual"][dev] = payload.upper() == "ON"
                print(f"lenh {dev} -> {payload}")


def stdin_loop():
    for line in sys.stdin:
        key = line.strip().lower()
        with lock:
            if key == "g":
                state["gas_leak"] = not state["gas_leak"]
            elif key == "m":
                state["motion"] = not state["motion"]
            elif key == "d":
                state["dark"] = not state["dark"]
            print("gas_leak=%s motion=%s dark=%s" % (state["gas_leak"], state["motion"], state["dark"]))


client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="esp32-simulator")
client.will_set(T_STATUS, "offline", qos=1, retain=True)
client.on_connect, client.on_message = on_connect, on_message
client.connect(args.host, args.port, keepalive=10)
client.loop_start()
threading.Thread(target=stdin_loop, daemon=True).start()

t0 = time.time()
tick = 0
print(f"Gia lap ESP32 -> {args.host}:{args.port} prefix={P}. Ctrl+C de dung.")
try:
    while True:
        tick += 1
        elapsed = time.time() - t0
        with lock:
            if args.gas_at and args.gas_at <= elapsed < args.gas_at + 10:
                state["gas_leak"] = True
            elif args.gas_at and elapsed >= args.gas_at + 10:
                state["gas_leak"] = False

            temp = round(29.5 + 3.0 * math.sin(tick / 30) + random.uniform(-0.2, 0.2), 1)
            hum = round(66 + 5 * math.cos(tick / 40) + random.uniform(-0.5, 0.5), 1)
            ldr = 3200 if state["dark"] else 900
            gas = 2600 if state["gas_leak"] else 800 + random.randint(-15, 15)
            gas_alarm = gas > 1300
            motion = state["motion"]

            if state["mode"] == "auto":
                state["light"] = motion and state["dark"]
                if temp >= 31.5:
                    state["fan"] = True
                elif temp <= 28.0:
                    state["fan"] = False
                state["buzzer"] = gas_alarm
            else:
                for k in ("light", "fan", "buzzer"):
                    state[k] = state["manual"][k]

            payload = {
                "ldr": ldr + random.randint(-20, 20), "dark": state["dark"],
                "temp": temp, "hum": hum, "gas": gas, "gas_alarm": gas_alarm,
                "motion": motion, "mode": state["mode"],
                "light": state["light"], "fan": state["fan"], "buzzer": state["buzzer"],
            }
        client.publish(T_SENSORS, json.dumps(payload), qos=0)
        time.sleep(args.interval)
except KeyboardInterrupt:
    client.publish(T_STATUS, "offline", qos=1, retain=True).wait_for_publish()
    client.disconnect()
