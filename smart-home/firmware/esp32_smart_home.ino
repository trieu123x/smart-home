/*
 * Firmware mau cho do an nha thong minh - ESP32 + Arduino IDE
 *
 * Phan cung goi y:
 *   DHT11/DHT22  -> GPIO 4    (nhiet do, do am)
 *   PIR HC-SR501 -> GPIO 5    (chuyen dong)
 *   LDR / BH1750 -> GPIO 34   (anh sang, doc ADC)
 *   MPU6050      -> I2C 21/22 (phat hien nga)
 *   Relay quat   -> GPIO 26
 *   Relay den    -> GPIO 27
 *
 * Thu vien can cai: ArduinoJson, DHT sensor library, Adafruit MPU6050.
 * File nay chi dung DHT + PIR + LDR de ngan gon; phan MPU6050 de o ham
 * detectFall() cho ban ghep cam bien that vao.
 */

#include <Arduino.h>
#include <ArduinoJson.h>
#include <HTTPClient.h>
#include <WiFi.h>

// ---------- Cau hinh ----------
const char *WIFI_SSID = "TEN_WIFI";
const char *WIFI_PASSWORD = "MAT_KHAU_WIFI";

// Dia chi may tinh dang chay backend (KHONG dung localhost)
const char *API_BASE = "http://192.168.1.10:8000";
const char *DEVICE_KEY = "esp32-secret-key"; // trung voi DEVICE_API_KEY trong .env
const char *DEVICE_CODE = "esp32-phongkhach";
const char *FAN_CODE = "fan-phongkhach";
const char *LIGHT_CODE = "light-phongkhach";

const int PIN_PIR = 5;
const int PIN_LDR = 34;
const int PIN_FAN = 26;
const int PIN_LIGHT = 27;

const unsigned long SEND_INTERVAL = 5000;  // gui du lieu moi 5 giay
const unsigned long POLL_INTERVAL = 2000;  // hoi lenh moi 2 giay

unsigned long lastSend = 0;
unsigned long lastPoll = 0;

// ---------- Ket noi ----------
void connectWiFi() {
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  Serial.print("Dang ket noi WiFi");
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.printf("\nDa ket noi, IP: %s\n", WiFi.localIP().toString().c_str());
}

int postJson(const String &path, const String &body) {
  HTTPClient http;
  http.begin(String(API_BASE) + path);
  http.addHeader("Content-Type", "application/json");
  http.addHeader("X-Device-Key", DEVICE_KEY);
  int code = http.POST(body);
  http.end();
  return code;
}

// ---------- Gui du lieu cam bien ----------
void sendTelemetry(float temperature, float humidity, float lux, int motion) {
  StaticJsonDocument<256> doc;
  doc["device_code"] = DEVICE_CODE;
  JsonObject metrics = doc.createNestedObject("metrics");
  metrics["temperature"] = temperature;
  metrics["humidity"] = humidity;
  metrics["lux"] = lux;
  metrics["motion"] = motion;

  String body;
  serializeJson(doc, body);
  int code = postJson("/api/ingest/telemetry", body);
  Serial.printf("telemetry -> HTTP %d\n", code);
}

void sendFallAlert() {
  StaticJsonDocument<256> doc;
  doc["device_code"] = DEVICE_CODE;
  doc["type"] = "fall_detected";
  doc["severity"] = "critical";
  doc["message"] = "Phat hien nga tai phong khach";

  String body;
  serializeJson(doc, body);
  int code = postJson("/api/ingest/event", body);
  Serial.printf("fall alert -> HTTP %d\n", code);
}

// ---------- Nhan lenh bat/tat tu dashboard ----------
void pollCommands(const char *deviceCode, int pin) {
  HTTPClient http;
  http.begin(String(API_BASE) + "/api/devices/" + deviceCode + "/commands");
  http.addHeader("X-Device-Key", DEVICE_KEY);
  int code = http.GET();

  if (code == 200) {
    StaticJsonDocument<512> doc;
    if (deserializeJson(doc, http.getString()) == DeserializationError::Ok) {
      for (JsonObject command : doc.as<JsonArray>()) {
        const char *action = command["action"];
        bool on = strcmp(action, "on") == 0;
        digitalWrite(pin, on ? HIGH : LOW);
        Serial.printf("%s -> %s\n", deviceCode, action);
      }
    }
  }
  http.end();
}

// ---------- Phat hien nga ----------
// Thay bang du lieu that tu MPU6050: tinh do lon gia toc tong hop,
// neu roi tu do (< 0.4g) roi va cham manh (> 2.5g) trong ~0.5s thi bao nga.
bool detectFall() {
  return false;
}

void setup() {
  Serial.begin(115200);
  pinMode(PIN_PIR, INPUT);
  pinMode(PIN_FAN, OUTPUT);
  pinMode(PIN_LIGHT, OUTPUT);
  digitalWrite(PIN_FAN, LOW);
  digitalWrite(PIN_LIGHT, LOW);
  connectWiFi();
}

void loop() {
  if (WiFi.status() != WL_CONNECTED) {
    connectWiFi();
  }

  unsigned long now = millis();

  if (now - lastSend >= SEND_INTERVAL) {
    lastSend = now;

    // TODO: thay 2 dong duoi bang dht.readTemperature() / dht.readHumidity()
    float temperature = 29.0 + random(-20, 25) / 10.0;
    float humidity = 65.0 + random(-40, 40) / 10.0;

    float lux = analogRead(PIN_LDR) / 4095.0 * 1000.0;
    int motion = digitalRead(PIN_PIR) == HIGH ? 1 : 0;

    sendTelemetry(temperature, humidity, lux, motion);
  }

  if (detectFall()) {
    sendFallAlert();
    delay(3000); // tranh gui lien tuc mot su kien
  }

  if (now - lastPoll >= POLL_INTERVAL) {
    lastPoll = now;
    pollCommands(FAN_CODE, PIN_FAN);
    pollCommands(LIGHT_CODE, PIN_LIGHT);
  }
}
