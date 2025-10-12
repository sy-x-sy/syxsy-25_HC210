#include <ArduinoBLE.h>
#include <MyoWare.h>
#include <vector>
#include <WiFi.h>
#include <WebServer.h>

// ===== Wi-Fi =====
const char* WIFI_SSID     = "iPhone (8)";
const char* WIFI_PASSWORD = "38893889";

// ===== BLE & MyoWare =====
const char* kExpectedName = "MyoWareSensor1";
const bool  debugLogging  = true;
const unsigned long kScanWindowMs = 10000;

MyoWare myoware;
std::vector<BLEDevice> shields;

// ===== 피로도 계산 파라미터 (민감도 매우 높게) =====
static const unsigned long WINDOW_MS = 1000;   // 1초 RMS 창
static const unsigned long REST_MS   = 10000;  // 휴식 캘리브 10초
static const double EPS_DENOM        = 1e-9;

static const double ALPHA         = 0.6;   // 스무딩: 반응성 매우 높게
static const double K_INTENSITY   = 4.5;   // 작을수록 빨리 쌓임
static const double GAMMA_ACTIVE  = 0.010; // 운동 시 회복 
static const double GAMMA_REST    = 0.035; // 휴식 시 회복도
static const double BASELINE_S    = 26.0;  // 누적 기준선 


// ===== 1초 RMS용 링버퍼 =====
static const int CAP = 2000;
double  valBuf[CAP];
unsigned long tBuf[CAP];
int headIdx = 0, tailIdx = 0, countSamples = 0;
double sumSq = 0.0;

enum Phase { CALIB_REST, RUN };
Phase phase = CALIB_REST;

unsigned long tStart = 0;
unsigned long tLastCompute = 0;

// 캘리브 & 상태
double RMS_rest = 0.0;
double RMS_max  = 1.0;
double S_prev   = 0.0; // 스무딩된 순간 피로(0~100)
double F_prev   = 0.0; // 누적 피로(0~100)

// ===== 전송값(2개) =====
volatile double g_lastEMG  = 0.0; // 현재 측정 EMG
volatile double g_fatigue  = 0.0; // 누적 피로도 F_t (0~100)

// ===== WebServer =====
WebServer server(80);

// ---------- 유틸 ----------
static bool nameMatches(const BLEDevice& dev) {
  if (!kExpectedName || strlen(kExpectedName) == 0) return true;
  String ln = dev.localName();
  return ln.length() && ln.equals(kExpectedName);
}
static void PrintPeripheralInfo(BLEDevice dev) {
  Serial.print(dev.address()); Serial.print(" '");
  Serial.print(dev.localName()); Serial.print("' ");
  Serial.println(dev.advertisedServiceUuid());
}
static double ReadBLEData(BLECharacteristic& ch) {
  if (ch && ch.canRead()) {
    char buf[20] = {0};
    int n = ch.readValue((void*)buf, sizeof(buf) - 1);
    if (n > 0) { buf[n] = '\0'; return String(buf).toDouble(); }
  }
  return NAN;
}
inline void popExpired(unsigned long nowMs) {
  while (countSamples > 0) {
    if (tBuf[headIdx] + WINDOW_MS > nowMs) break;
    sumSq -= valBuf[headIdx] * valBuf[headIdx];
    headIdx = (headIdx + 1) % CAP;
    countSamples--;
  }
}
inline void pushSample(double v, unsigned long nowMs) {
  popExpired(nowMs);
  if (countSamples == CAP) {
    sumSq -= valBuf[headIdx] * valBuf[headIdx];
    headIdx = (headIdx + 1) % CAP;
    countSamples--;
  }
  valBuf[tailIdx] = v;
  tBuf[tailIdx] = nowMs;
  tailIdx = (tailIdx + 1) % CAP;
  countSamples++;
  sumSq += v * v;
}
inline double currentRMS() {
  if (countSamples <= 0) return 0.0;
  double m2 = sumSq / (double)countSamples;
  return m2 > 0 ? sqrt(m2) : 0.0;
}

// ---------- Web ----------
void sendCORS() {
  server.sendHeader("Access-Control-Allow-Origin", "*");
  server.sendHeader("Access-Control-Allow-Methods", "GET,OPTIONS");
  server.sendHeader("Access-Control-Allow-Headers", "Content-Type");
  server.sendHeader("Cache-Control", "no-cache, no-store, must-revalidate");
}
void handleRoot() {
  sendCORS();
  const char* html =
    "<!doctype html><meta charset='utf-8'>"
    "<meta name='viewport' content='width=device-width,initial-scale=1'>"
    "<title>ESP32 EMG</title>"
    "<style>body{font-family:system-ui;margin:24px}h1{margin:0 0 16px}"
    ".mono{font-family:ui-monospace,Consolas,Menlo,monospace;font-size:18px}"
    ".bar{height:18px;background:#eee;border-radius:9px;overflow:hidden;max-width:440px}"
    ".fill{height:100%;width:0;background:#4caf50}"
    "</style>"
    "<h1>EMG & Fatigue</h1>"
    "<div class='mono'>EMG: <span id='emg'>--</span></div>"
    "<div class='mono'>Fatigue: <span id='fatigue'>--</span> %</div>"
    "<div class='bar'><div id='fill' class='fill'></div></div>"
    "<p class='mono'><a href='/data'>/data</a> (JSON)</p>"
    "<script>"
    "async function tick(){try{let r=await fetch('/data');let j=await r.json();"
    "document.getElementById('emg').textContent=(j.emg||0).toFixed(4);"
    "document.getElementById('fatigue').textContent=(j.fatigue||0).toFixed(2);"
    "document.getElementById('fill').style.width=Math.min(100,Math.max(0,j.fatigue||0))+'%';"
    "}catch(e){}} setInterval(tick,1000); tick();"
    "</script>";
  server.send(200, "text/html; charset=utf-8", html);
}
void handleDataGET() {
  sendCORS();
  char body[96];
  snprintf(body, sizeof(body),
    "{"
      "\"emg\":%.4f,"
      "\"fatigue\":%.2f"
    "}",
    g_lastEMG, g_fatigue
  );
  server.send(200, "application/json", body);
}
void handleDataOPTIONS() { sendCORS(); server.send(204); }
void handleNotFound() { sendCORS(); server.send(404, "text/plain", "Not found. Try / or /data\n"); }

// ---------- 네트워크 ----------
void wifiConnect() {
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  unsigned long t0 = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - t0 < 15000) {
    delay(250);
  }
  if (WiFi.status() == WL_CONNECTED) {
    Serial.print("# WiFi IP: "); Serial.println(WiFi.localIP());
  } else {
    Serial.println("# WiFi not connected (proceeding, web disabled).");
  }
}

// ---------- Arduino ----------
void setup() {
  Serial.begin(115200);
  while (!Serial) {}
  pinMode(myoware.getStatusLEDPin(), OUTPUT);

  // Wi-Fi & Web
  wifiConnect();
  if (WiFi.status() == WL_CONNECTED) {
    server.on("/", HTTP_GET, handleRoot);
    server.on("/data", HTTP_GET, handleDataGET);
    server.on("/data", HTTP_OPTIONS, handleDataOPTIONS);
    server.onNotFound(handleNotFound);
    server.begin();
    Serial.println("# WebServer started on port 80 (/, /data)");
  }

  // BLE
  if (!BLE.begin()) { Serial.println("Starting BLE failed!"); while (1) {} }
  if (debugLogging) {
    Serial.println("MyoWare BLE Central (ESP32)");
    Serial.print("Scan UUID: "); Serial.println(MyoWareBLE::uuidMyoWareService.c_str());
    Serial.print("Expected name: "); Serial.println(kExpectedName);
  }
  BLE.scanForUuid(MyoWareBLE::uuidMyoWareService.c_str(), true);

  unsigned long t0 = millis();
  while (millis() - t0 < kScanWindowMs) {
    myoware.blinkStatusLED();
    BLEDevice p = BLE.available();
    if (!p) continue;
    if (!nameMatches(p)) { if (debugLogging) { Serial.print("Skip "); PrintPeripheralInfo(p);} continue; }

    if (debugLogging) { Serial.print("Connecting "); PrintPeripheralInfo(p); }
    BLE.stopScan();
    if (!p.connect()) { Serial.println("Connect fail"); BLE.scanForUuid(MyoWareBLE::uuidMyoWareService.c_str(), true); continue; }
    if (!p.discoverAttributes()) { Serial.println("Attr discover fail"); p.disconnect(); BLE.scanForUuid(MyoWareBLE::uuidMyoWareService.c_str(), true); continue; }
    shields.clear(); shields.push_back(p); break;
  }
  BLE.stopScan();

  if (shields.empty()) { Serial.println("No MyoWare Wireless Shields found!"); while (1) {} }

  digitalWrite(myoware.getStatusLEDPin(), HIGH);
  Serial.print("Connected: "); Serial.println(shields.front().localName());

  tStart = millis();
  tLastCompute = millis();
  phase = CALIB_REST;
  RMS_rest = 0.0; RMS_max = 1.0; S_prev = 0.0; F_prev = 0.0;
  Serial.println("# phase=CALIB_REST (10s) — keep muscle relaxed");
}

void loop() {
  BLE.poll();
  if (WiFi.status() == WL_CONNECTED) server.handleClient();

  if (shields.empty()) return;
  BLEDevice& shield = shields.front();
  if (!shield || !shield.connected()) { delay(50); return; }

  BLEService svc = shield.service(MyoWareBLE::uuidMyoWareService.c_str());
  if (!svc) { shield.disconnect(); return; }
  BLECharacteristic ch = svc.characteristic(MyoWareBLE::uuidMyoWareCharacteristic.c_str());

  // ---- 샘플 수집 ----
  double v = ReadBLEData(ch);
  unsigned long nowMs = millis();
  if (!isnan(v)) {
    g_lastEMG = v;
    pushSample(v, nowMs);
  }

  // ---- 1초 주기 계산 ----
  if (nowMs - tLastCompute >= 1000) {
    tLastCompute = nowMs;
    double RMS_t = currentRMS();

    if (phase == CALIB_REST) {
      static int restCount = 0; restCount++;
      RMS_rest = (restCount == 1) ? RMS_t : (0.85 * RMS_rest + 0.15 * RMS_t); // 좀 더 빠르게 적응

      if (nowMs - tStart >= REST_MS) {
        if (RMS_rest < EPS_DENOM) RMS_rest = EPS_DENOM;
        RMS_max = max(RMS_rest * 1.3, RMS_rest + 0.005); // 초기 상한 낮게
        phase = RUN;
        Serial.print("# RMS_rest="); Serial.println(RMS_rest, 6);
        Serial.print("# RMS_max_init="); Serial.println(RMS_max, 6);
        Serial.println("# phase=RUN");
      } else {
        Serial.print("# calibrating... RMS_rest~="); Serial.println(RMS_rest, 6);
      }

      g_fatigue = 0.0;
    } else {
      // 상한선: 더 빠른 감쇠로 분모 축소
      RMS_max = max(0.990 * RMS_max, RMS_t);

      // r_t (분모 바닥 크게 낮춤)
      double denomR   = RMS_max - RMS_rest;
      double floorDen = max(0.05 * RMS_rest, EPS_DENOM); // 5%로 축소
      if (denomR < floorDen) denomR = floorDen;

      double r_t = (RMS_t - RMS_rest) / denomR;
      if (r_t < 0.0) r_t = 0.0; if (r_t > 1.0) r_t = 1.0;

      // 민감도 극대화: 약한 수축도 크게 반영 (제곱근 스케일) + 약한 바이어스
      double S_raw = 100.0 * sqrt(r_t);
      // 아주 미세한 활성에도 살짝 가산(임계 초과 시 +5)
      if (r_t > 0.03) S_raw = min(100.0, S_raw + 5.0);

      double S_t = ALPHA * S_raw + (1.0 - ALPHA) * S_prev;

      // 누적 F_t (기준선 낮추고, 회복률 완만)
      double gamma = (S_t < 20.0 ? GAMMA_REST : GAMMA_ACTIVE);
      double delta = (S_t - BASELINE_S) / K_INTENSITY;
      double F_t = F_prev + delta - gamma;
      if (F_t < 0.0) F_t = 0.0; if (F_t > 100.0) F_t = 100.0;

      g_fatigue = F_t;

      S_prev = S_t; F_prev = F_t;

      // (옵션) 로그
      Serial.print("emg="); Serial.print(g_lastEMG, 3);
      Serial.print(" r_t="); Serial.print(r_t, 3);
      Serial.print(" S_raw="); Serial.print(S_raw, 1);
      Serial.print(" S_t="); Serial.print(S_t, 1);
      Serial.print(" F="); Serial.println(g_fatigue, 1);
    }
  }

  delay(5);
}
