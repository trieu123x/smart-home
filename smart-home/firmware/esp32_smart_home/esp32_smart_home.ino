#include <Arduino.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <PubSubClient.h>   // thư viện "PubSubClient" của Nick O'Leary
#include "DHT.h"

// ================= WIFI + MQTT (SỬA CHO PHÙ HỢP) =================
const char* WIFI_SSID   = "P403";
const char* WIFI_PASS   = "88888888";
// Private HiveMQ Cloud cluster over TLS. Fill in the cluster host and the "esp32" credential.
const char* MQTT_HOST   = "<cluster-id>.s1.eu.hivemq.cloud";
const int   MQTT_PORT   = 8883;
const char* MQTT_USER   = "esp32";
const char* MQTT_PASS   = "<esp32-password>";

// ISRG Root X1 (Let's Encrypt root, valid until 2035-06-04), used to verify the HiveMQ Cloud cert.
// SHA-256 fingerprint 96:BC:EC:06:26:49:76:F3:74:60:77:9A:CF:28:C5:A7:CF:E8:A3:C0:AA:E1:1A:8F:FC:EE:05:C0:BD:DF:08:C6
const char ISRG_ROOT_X1[] = R"PEM(
-----BEGIN CERTIFICATE-----
MIIFazCCA1OgAwIBAgIRAIIQz7DSQONZRGPgu2OCiwAwDQYJKoZIhvcNAQELBQAw
TzELMAkGA1UEBhMCVVMxKTAnBgNVBAoTIEludGVybmV0IFNlY3VyaXR5IFJlc2Vh
cmNoIEdyb3VwMRUwEwYDVQQDEwxJU1JHIFJvb3QgWDEwHhcNMTUwNjA0MTEwNDM4
WhcNMzUwNjA0MTEwNDM4WjBPMQswCQYDVQQGEwJVUzEpMCcGA1UEChMgSW50ZXJu
ZXQgU2VjdXJpdHkgUmVzZWFyY2ggR3JvdXAxFTATBgNVBAMTDElTUkcgUm9vdCBY
MTCCAiIwDQYJKoZIhvcNAQEBBQADggIPADCCAgoCggIBAK3oJHP0FDfzm54rVygc
h77ct984kIxuPOZXoHj3dcKi/vVqbvYATyjb3miGbESTtrFj/RQSa78f0uoxmyF+
0TM8ukj13Xnfs7j/EvEhmkvBioZxaUpmZmyPfjxwv60pIgbz5MDmgK7iS4+3mX6U
A5/TR5d8mUgjU+g4rk8Kb4Mu0UlXjIB0ttov0DiNewNwIRt18jA8+o+u3dpjq+sW
T8KOEUt+zwvo/7V3LvSye0rgTBIlDHCNAymg4VMk7BPZ7hm/ELNKjD+Jo2FR3qyH
B5T0Y3HsLuJvW5iB4YlcNHlsdu87kGJ55tukmi8mxdAQ4Q7e2RCOFvu396j3x+UC
B5iPNgiV5+I3lg02dZ77DnKxHZu8A/lJBdiB3QW0KtZB6awBdpUKD9jf1b0SHzUv
KBds0pjBqAlkd25HN7rOrFleaJ1/ctaJxQZBKT5ZPt0m9STJEadao0xAH0ahmbWn
OlFuhjuefXKnEgV4We0+UXgVCwOPjdAvBbI+e0ocS3MFEvzG6uBQE3xDk3SzynTn
jh8BCNAw1FtxNrQHusEwMFxIt4I7mKZ9YIqioymCzLq9gwQbooMDQaHWBfEbwrbw
qHyGO0aoSCqI3Haadr8faqU9GY/rOPNk3sgrDQoo//fb4hVC1CLQJ13hef4Y53CI
rU7m2Ys6xt0nUW7/vGT1M0NPAgMBAAGjQjBAMA4GA1UdDwEB/wQEAwIBBjAPBgNV
HRMBAf8EBTADAQH/MB0GA1UdDgQWBBR5tFnme7bl5AFzgAiIyBpY9umbbjANBgkq
hkiG9w0BAQsFAAOCAgEAVR9YqbyyqFDQDLHYGmkgJykIrGF1XIpu+ILlaS/V9lZL
ubhzEFnTIZd+50xx+7LSYK05qAvqFyFWhfFQDlnrzuBZ6brJFe+GnY+EgPbk6ZGQ
3BebYhtF8GaV0nxvwuo77x/Py9auJ/GpsMiu/X1+mvoiBOv/2X/qkSsisRcOj/KK
NFtY2PwByVS5uCbMiogziUwthDyC3+6WVwW6LLv3xLfHTjuCvjHIInNzktHCgKQ5
ORAzI4JMPJ+GslWYHb4phowim57iaztXOoJwTdwJx4nLCgdNbOhdjsnvzqvHu7Ur
TkXWStAmzOVyyghqpZXjFaH3pO3JLF+l+/+sKAIuvtd7u+Nxe5AW0wdeRlN8NwdC
jNPElpzVmbUq4JUagEiuTDkHzsxHpFKVK7q4+63SM1N95R1NbdWhscdCb+ZAJzVc
oyi3B43njTOQ5yOf+1CceWxG1bQVs5ZufpsMljq4Ui0/1lvh+wjChP4kqKOJ2qxq
4RgqsahDYVvTH9w7jXbyLeiNdd8XM2w9U/t7y0Ff/9yi0GE44Za4rF2LN9d11TPA
mRGunUHBcnWEvgJBQl9nJEiU0Zsnvgc/ubhPgXRR4Xq37Z0j4r7g1SgEEzwxA57d
emyPxgcYxn/eR44/KJ4EBs+lVDR3veyJm+kXQ99b21/+jh5Xos1AnX5iItreGCc=
-----END CERTIFICATE-----
)PEM";

/*
// Topic (phải khớp với Django)
const char* T_SENSORS = "home/sensors";   // ESP32 -> server
const char* T_STATUS  = "home/status";    // online/offline (LWT)
const char* T_MODE    = "home/mode";      // server -> ESP32: auto | manual
const char* T_CMD     = "home/cmd/";      // server -> ESP32: home/cmd/<light|fan|buzzer> = ON|OFF
*/

const char* MQTT_PREFIX = "ptit_sh_k7x2q9/home/";

char T_SENSORS[96];
char T_STATUS[96];
char T_MODE[96];
char T_CMD[96];

const unsigned long PUBLISH_INTERVAL = 1000;

// ================= KHAI BÁO CHÂN (GPIO) =================
const int PIR_PIN        = 27;
const int LDR_PIN        = 34;
const int DHT_PIN        = 12;
const int MQ2_PIN        = 35;
const int FC51_PIN       = 23;

const int RELAY_LIGHT    = 26;
const int RELAY_FAN      = 14;  // 1 relay quạt dùng chung cho làm mát + xả gas

const int BUZZER_PIN      = 33;
const int AWAY_SWITCH_PIN = 32;

#define DHTTYPE DHT22
DHT dht(DHT_PIN, DHTTYPE);

// ================= NGƯỠNG =================
int LDR_DARK_THRESHOLD  = 2000;
float TEMP_ON  = 31.5;
float TEMP_OFF = 28.0;

const unsigned long NO_MOTION_TIMEOUT = 15000;
const unsigned long DHT_READ_INTERVAL = 2000;
bool RELAY_ACTIVE_LOW = true;
const unsigned long GAS_WARMUP_MS = 20000;
const unsigned long PRINT_INTERVAL = 1000;
unsigned long lastPrintTime = 0;

// ================= GAS =================
int gasBaseline = 0;
float gasSmoothed = 0;
const float GAS_SMOOTH_ALPHA = 0.15;
int GAS_ON_OFFSET  = 500;
int GAS_OFF_OFFSET = 250;

// Ở chế độ thủ công: true = còi + quạt vẫn tự bật khi có gas (an toàn); false = hoàn toàn thủ công
const bool GAS_FAILSAFE_IN_MANUAL = false;

// ================= TRẠNG THÁI =================
unsigned long lastMotionTime = 0;
unsigned long lastDhtRead = 0;
float currentTemp = 25.0;
float currentHum  = 0.0;

bool autoMode = true;        // true = tự động, false = thủ công
bool lightOn = false;
bool fanOn = false;          // trạng thái thực của relay quạt
bool buzzerOn = false;
bool fanCoolOn = false;      // nội bộ chế độ tự động
bool fanVentOn = false;
bool gasAlarm = false;

// Lệnh thủ công
bool manualLight = false, manualFan = false, manualBuzzer = false;
bool publishNow = false;

int motionPrevState = LOW;
int   dbg_pirNow, dbg_ldrValue, dbg_gasRaw;
bool  dbg_isDark, dbg_motionPresent;

String serialBuffer = "";

WiFiClientSecure espClient;
PubSubClient mqtt(espClient);
unsigned long lastMqttTry = 0, lastPublish = 0;

void setRelay(int pin, bool on) {
  digitalWrite(pin, RELAY_ACTIVE_LOW ? (on ? LOW : HIGH) : (on ? HIGH : LOW));
}

// ================= MQTT =================
void setMode(bool toAuto) {
  if (toAuto == autoMode) return;
  autoMode = toAuto;
  if (!autoMode) {
    // Chuyển sang thủ công: giữ nguyên trạng thái hiện tại, không đổi đột ngột
    manualLight = lightOn; manualFan = fanOn; manualBuzzer = buzzerOn;
  }
  Serial.println(autoMode ? "CHE DO: TU DONG" : "CHE DO: THU CONG");
  publishNow = true;
}

void onMqttMessage(char* topic, byte* payload, unsigned int len) {
  String msg;
  for (unsigned int i = 0; i < len; i++) msg += (char)payload[i];
  msg.trim();
  String t = String(topic);

  if (t == T_MODE) {
    setMode(msg == "auto");
    return;
  }
  if (t.startsWith(T_CMD)) {
    if (autoMode) return;                 // bỏ qua lệnh khi đang tự động
    bool on = (msg == "ON");
    String dev = t.substring(strlen(T_CMD));
    if (dev == "light") manualLight = on;
    else if (dev == "fan") manualFan = on;
    else if (dev == "buzzer") manualBuzzer = on;
    else return;
    Serial.print("LENH THU CONG: "); Serial.print(dev); Serial.println(on ? " BAT" : " TAT");
    publishNow = true;
  }
}

void mqttReconnect() {
  if (WiFi.status() != WL_CONNECTED) { WiFi.reconnect(); return; }
  String id = "esp32-" + String((uint32_t)ESP.getEfuseMac(), HEX);
  bool ok = mqtt.connect(id.c_str(),
                         strlen(MQTT_USER) ? MQTT_USER : NULL,
                         strlen(MQTT_USER) ? MQTT_PASS : NULL,
                         T_STATUS, 1, true, "offline");
  if (ok) {
    Serial.println("MQTT: da ket noi");
    mqtt.publish(T_STATUS, "online", true);
    mqtt.subscribe(T_MODE, 1);                         // nhận lại mode retained
    String cmd = String(T_CMD) + "#";
    mqtt.subscribe(cmd.c_str(), 1);
    publishNow = true;
  } else {
    Serial.print("MQTT: loi rc="); Serial.println(mqtt.state());
  }
}

void publishSensors() {
  char buf[400];
  snprintf(buf, sizeof(buf),
    "{\"ldr\":%d,\"dark\":%s,\"temp\":%.1f,\"hum\":%.1f,\"gas\":%d,\"gas_base\":%d,"
    "\"gas_alarm\":%s,\"motion\":%s,\"light\":%s,\"fan\":%s,\"buzzer\":%s,\"mode\":\"%s\"}",
    dbg_ldrValue, dbg_isDark ? "true" : "false", currentTemp, currentHum,
    dbg_gasRaw, gasBaseline, gasAlarm ? "true" : "false",
    dbg_motionPresent ? "true" : "false",
    lightOn ? "true" : "false", fanOn ? "true" : "false", buzzerOn ? "true" : "false",
    autoMode ? "auto" : "manual");
  mqtt.publish(T_SENSORS, buf);
}

// ================= SERIAL =================
void inThongSo() {
  Serial.print("["); Serial.print(millis() / 1000); Serial.print("s] Mode=");
  Serial.print(autoMode ? "AUTO" : "MANUAL");
  Serial.print(" | PIR="); Serial.print(dbg_pirNow == HIGH ? "1" : "0");
  Serial.print(" Present="); Serial.print(dbg_motionPresent ? "1" : "0");
  Serial.print(" | LDR="); Serial.print(dbg_ldrValue); Serial.print(dbg_isDark ? "(toi)" : "(sang)");
  Serial.print(" | T="); Serial.print(currentTemp); Serial.print("C H="); Serial.print(currentHum);
  Serial.print("% | GasRaw="); Serial.print(dbg_gasRaw);
  Serial.print(" Smooth="); Serial.print(gasSmoothed, 1);
  Serial.print(" Base="); Serial.print(gasBaseline);
  Serial.print(" Alarm="); Serial.print(gasAlarm ? "1" : "0");
  Serial.print(" | Den="); Serial.print(lightOn ? "BAT" : "TAT");
  Serial.print(" Quat="); Serial.print(fanOn ? "BAT" : "TAT");
  Serial.print(" Loa="); Serial.print(buzzerOn ? "BAT" : "TAT");
  Serial.print(" | WiFi="); Serial.print(WiFi.status() == WL_CONNECTED ? "OK" : "X");
  Serial.print(" MQTT="); Serial.println(mqtt.connected() ? "OK" : "X");
}

void inNguong() {
  Serial.println("---- NGUONG HIEN TAI ----");
  Serial.print("LDR_DARK_THRESHOLD = "); Serial.println(LDR_DARK_THRESHOLD);
  Serial.print("TEMP_ON  = "); Serial.println(TEMP_ON);
  Serial.print("TEMP_OFF = "); Serial.println(TEMP_OFF);
  Serial.print("GAS_ON_OFFSET  = "); Serial.println(GAS_ON_OFFSET);
  Serial.print("GAS_OFF_OFFSET = "); Serial.println(GAS_OFF_OFFSET);
  Serial.println("-------------------------");
}

void inHuongDan() {
  Serial.println("Cac lenh: LDR=<so> TEMPON=<so> TEMPOFF=<so> GASON=<so> GASOFF=<so> SHOW HELP");
}

void xuLyMotLenh(String cmd) {
  cmd.trim();
  if (cmd.length() == 0) return;
  cmd.toUpperCase();
  if (cmd == "SHOW") { inNguong(); return; }
  if (cmd == "HELP") { inHuongDan(); return; }
  int eq = cmd.indexOf('=');
  if (eq == -1) { Serial.println("Lenh khong hop le. Go HELP."); return; }
  String key = cmd.substring(0, eq);
  float val = cmd.substring(eq + 1).toFloat();
  if (key == "LDR") LDR_DARK_THRESHOLD = (int)val;
  else if (key == "TEMPON") TEMP_ON = val;
  else if (key == "TEMPOFF") TEMP_OFF = val;
  else if (key == "GASON") GAS_ON_OFFSET = (int)val;
  else if (key == "GASOFF") GAS_OFF_OFFSET = (int)val;
  else { Serial.println("Khong nhan dien duoc tham so."); return; }
  Serial.println("Da cap nhat."); inNguong();
}

void xuLyLenhSerial() {
  while (Serial.available() > 0) {
    char c = Serial.read();
    if (c == '\n' || c == '\r') {
      if (serialBuffer.length() > 0) { xuLyMotLenh(serialBuffer); serialBuffer = ""; }
    } else serialBuffer += c;
  }
}

// ================= SETUP =================
void setup() {
  Serial.begin(115200);
  dht.begin();

  snprintf(T_SENSORS, sizeof(T_SENSORS), "%ssensors", MQTT_PREFIX);
  snprintf(T_STATUS,  sizeof(T_STATUS),  "%sstatus",  MQTT_PREFIX);
  snprintf(T_MODE,    sizeof(T_MODE),    "%smode",    MQTT_PREFIX);
  snprintf(T_CMD,     sizeof(T_CMD),     "%scmd/",    MQTT_PREFIX);

  pinMode(PIR_PIN, INPUT);
  pinMode(FC51_PIN, INPUT);
  pinMode(AWAY_SWITCH_PIN, INPUT_PULLDOWN);
  pinMode(RELAY_LIGHT, OUTPUT);
  pinMode(RELAY_FAN, OUTPUT);
  pinMode(BUZZER_PIN, OUTPUT);
  setRelay(RELAY_LIGHT, false);
  setRelay(RELAY_FAN, false);
  digitalWrite(BUZZER_PIN, LOW);

  // Kết nối WiFi (chờ tối đa 15s, hết hạn vẫn chạy tiếp ở chế độ offline)
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  espClient.setCACert(ISRG_ROOT_X1);
  mqtt.setServer(MQTT_HOST, MQTT_PORT);
  mqtt.setCallback(onMqttMessage);
  mqtt.setBufferSize(512);
  mqtt.setSocketTimeout(3);

  Serial.println("Dang lam nong cam bien MQ-2, vui long cho...");
  unsigned long warmupStart = millis();
  while (millis() - warmupStart < GAS_WARMUP_MS) {
    delay(500);
    Serial.print(".");
  }
  Serial.println();

  long sum = 0;
  for (int i = 0; i < 10; i++) { sum += analogRead(MQ2_PIN); delay(50); }
  gasBaseline = sum / 10;
  gasSmoothed = gasBaseline;

  Serial.print("Gas baseline (ADC): "); Serial.println(gasBaseline);
  Serial.print("WiFi: "); Serial.println(WiFi.status() == WL_CONNECTED ? WiFi.localIP().toString() : "chua ket noi");
  inHuongDan();
  inNguong();
}

// ================= LOOP =================
void loop() {
  unsigned long now = millis();

  xuLyLenhSerial();

  // ---- MQTT keep-alive / reconnect (không chặn logic cảm biến) ----
  if (!mqtt.connected()) {
    if (now - lastMqttTry > 5000) { lastMqttTry = now; mqttReconnect(); }
  } else {
    mqtt.loop();
  }

  // ================= ĐỌC CẢM BIẾN (luôn chạy ở cả 2 chế độ) =================
  int pirNow = digitalRead(PIR_PIN);
  int motionNow = (pirNow == HIGH) ? HIGH : LOW;
  motionPrevState = motionNow;
  if (motionNow == HIGH) lastMotionTime = now;
  bool motionPresent = (now - lastMotionTime < NO_MOTION_TIMEOUT);

  int ldrValue = analogRead(LDR_PIN);
  bool isDark = (ldrValue > LDR_DARK_THRESHOLD);

  if (now - lastDhtRead > DHT_READ_INTERVAL) {
    lastDhtRead = now;
    float t = dht.readTemperature();
    float h = dht.readHumidity();
    if (!isnan(t)) currentTemp = t;
    if (!isnan(h)) currentHum = h;
  }

  int gasRaw = analogRead(MQ2_PIN);
  gasSmoothed = GAS_SMOOTH_ALPHA * gasRaw + (1 - GAS_SMOOTH_ALPHA) * gasSmoothed;

  bool gasDetected;
  if (!gasAlarm && gasSmoothed > gasBaseline + GAS_ON_OFFSET) gasDetected = true;
  else if (gasAlarm && gasSmoothed < gasBaseline + GAS_OFF_OFFSET) gasDetected = false;
  else gasDetected = gasAlarm;

  if (gasDetected && !gasAlarm) { gasAlarm = true; Serial.println("CANH BAO GAS/KHOI!"); }
  else if (!gasDetected && gasAlarm) { gasAlarm = false; Serial.println("Het canh bao gas"); }

  // ================= ĐIỀU KHIỂN THIẾT BỊ =================
  bool newLight, newFan, newBuzzer;

  if (autoMode) {
    // ---- Đèn ----
    newLight = motionPresent && isDark;

    // ---- Quạt làm mát (hysteresis) ----
    if (!motionPresent) {
      fanCoolOn = false;
    } else if (!fanCoolOn && currentTemp >= TEMP_ON) {
      fanCoolOn = true;
    } else if (fanCoolOn && currentTemp <= TEMP_OFF) {
      fanCoolOn = false;
    }

    // ---- Quạt xả gas ----
    fanVentOn = gasDetected;

    newFan = fanCoolOn || fanVentOn;
    newBuzzer = gasAlarm;
  } else {
    // ---- Thủ công: chỉ theo lệnh từ web ----
    fanCoolOn = false;
    fanVentOn = false;
    newLight  = manualLight;
    newFan    = manualFan;
    newBuzzer = manualBuzzer;
    if (GAS_FAILSAFE_IN_MANUAL && gasAlarm) { newFan = true; newBuzzer = true; }
  }

  if (newLight != lightOn) {
    lightOn = newLight; setRelay(RELAY_LIGHT, lightOn); publishNow = true;
    Serial.println(lightOn ? "DEN: BAT" : "DEN: TAT");
  }
  if (newFan != fanOn) {
    fanOn = newFan; setRelay(RELAY_FAN, fanOn); publishNow = true;
    Serial.println(fanOn ? "QUAT: BAT" : "QUAT: TAT");
  }
  if (newBuzzer != buzzerOn) {
    buzzerOn = newBuzzer; digitalWrite(BUZZER_PIN, buzzerOn ? HIGH : LOW); publishNow = true;
    Serial.println(buzzerOn ? "LOA: BAT" : "LOA: TAT");
  }

  // ================= LƯU GIÁ TRỊ ĐỂ IN / GỬI =================
  dbg_pirNow = pirNow;
  dbg_ldrValue = ldrValue;
  dbg_gasRaw = gasRaw;
  dbg_isDark = isDark;
  dbg_motionPresent = motionPresent;

  // ================= GỬI LÊN SERVER =================
  if (mqtt.connected() && (publishNow || now - lastPublish >= PUBLISH_INTERVAL)) {
    lastPublish = now;
    publishNow = false;
    publishSensors();
  }

  if (now - lastPrintTime >= PRINT_INTERVAL) {
    lastPrintTime = now;
    inThongSo();
  }

  delay(50);
}


