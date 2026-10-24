import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  LIVE_MAX_SAMPLES,
  LIVE_WINDOW_MS,
  actuatorReason,
  appendSample,
  brightnessPercent,
  comfortLabel,
  gasStatus,
  heatIndexC,
  lastMotionAt,
} from "../src/lib/sensorLogic.ts";

describe("brightnessPercent", () => {
  it("maps LDR ADC to an inverted percentage", () => {
    assert.equal(brightnessPercent(218), 95);
    assert.equal(brightnessPercent(2000), 51);
    assert.equal(brightnessPercent(0), 100);
    assert.equal(brightnessPercent(4095), 0);
  });

  it("clamps out-of-range readings", () => {
    assert.equal(brightnessPercent(-5), 100);
    assert.equal(brightnessPercent(5000), 0);
  });
});

describe("gasStatus", () => {
  it("is normal below the baseline with ratio clamped to 0", () => {
    assert.deepEqual(gasStatus(137, 157, false), { delta: -20, level: "normal", ratio: 0 });
  });

  it("is elevated past the off offset", () => {
    assert.equal(gasStatus(500, 157, false).level, "elevated");
  });

  it("trusts the alarm flag over the raw reading", () => {
    assert.equal(gasStatus(700, 157, false).level, "elevated");
    assert.equal(gasStatus(300, 157, true).level, "danger");
  });

  it("has no delta without a baseline", () => {
    assert.deepEqual(gasStatus(900, undefined, false), { delta: null, level: "normal", ratio: 0 });
  });

  it("clamps ratio to 1", () => {
    assert.equal(gasStatus(1200, 157, false).ratio, 1);
  });
});

describe("heatIndexC", () => {
  it("uses the Rothfusz regression when hot", () => {
    assert.ok(Math.abs(heatIndexC(31.3, 69.4) - 38.2) <= 0.3);
  });

  it("uses the simple formula when mild", () => {
    assert.ok(Math.abs(heatIndexC(25, 50) - 25) <= 0.5);
  });
});

describe("comfortLabel", () => {
  it("returns the first matching band", () => {
    assert.equal(comfortLabel(15, 50), "Lạnh");
    assert.equal(comfortLabel(31.3, 69.4), "Nóng ẩm");
    assert.equal(comfortLabel(32, 40), "Nóng");
    assert.equal(comfortLabel(24, 25), "Khô");
    assert.equal(comfortLabel(24, 80), "Ẩm");
    assert.equal(comfortLabel(24, 55), "Thoải mái");
  });
});

describe("actuatorReason", () => {
  it("is null when the device is off", () => {
    assert.equal(actuatorReason("fan", { mode: "auto", fan: false }), null);
  });

  it("reports manual control", () => {
    assert.equal(actuatorReason("light", { mode: "manual", light: true }), "Điều khiển thủ công");
  });

  it("explains the auto rules", () => {
    assert.equal(actuatorReason("fan", { mode: "auto", fan: true, gas_alarm: true }), "Xả gas");
    assert.match(actuatorReason("fan", { mode: "auto", fan: true }), /Làm mát/);
    assert.equal(actuatorReason("light", { mode: "auto", light: true }), "Trời tối + có người");
    assert.equal(actuatorReason("buzzer", { mode: "auto", buzzer: true }), "Báo động gas");
  });
});

describe("appendSample", () => {
  it("returns a new array", () => {
    const buf = [{ t: 0 }];
    const next = appendSample(buf, { t: 1000 });
    assert.notEqual(next, buf);
    assert.deepEqual(buf, [{ t: 0 }]);
    assert.equal(next.length, 2);
  });

  it("drops a sample 200 ms after the last one", () => {
    const next = appendSample([{ t: 1000, temp: 30 }], { t: 1200, temp: 31 });
    assert.deepEqual(next, [{ t: 1000, temp: 30 }]);
  });

  it("drops a sample older than the last one", () => {
    const buf = [{ t: 5000, gas: 2600 }];
    assert.equal(appendSample(buf, { t: 4000, gas: 800 }), buf);
  });

  it("drops samples older than the live window", () => {
    const now = 10 * 60_000;
    const next = appendSample([{ t: now - LIVE_WINDOW_MS - 1 }, { t: now - 1000 }], { t: now });
    assert.deepEqual(
      next.map((s) => s.t),
      [now - 1000, now],
    );
  });

  it("never exceeds the sample cap", () => {
    let buf = [];
    for (let i = 0; i < LIVE_MAX_SAMPLES + 50; i++) buf = appendSample(buf, { t: i * 600 });
    assert.equal(buf.length, LIVE_MAX_SAMPLES);
    assert.equal(buf[buf.length - 1].t, (LIVE_MAX_SAMPLES + 49) * 600);
  });
});

describe("lastMotionAt", () => {
  it("is null on an empty buffer", () => {
    assert.equal(lastMotionAt([]), null);
  });

  it("returns the newest sample with motion", () => {
    const buf = [
      { t: 1, motion: true },
      { t: 2, motion: true },
      { t: 3, motion: false },
    ];
    assert.equal(lastMotionAt(buf), 2);
  });
});
