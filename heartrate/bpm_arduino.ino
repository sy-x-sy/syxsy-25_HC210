#include <WiFi.h>
#include <HTTPClient.h>
#include <Wire.h>
#include <SparkFun_Bio_Sensor_Hub_Library.h>

// ================== WiFi 설정 ==================
const char* ssid = "esptest";       // 와이파이 이름
const char* password = "12345678";   // 와이파이 비번

// 서버 주소 (PC IPv4 주소 확인 후 수정!)
const char* serverUrl = "http://172.20.10.2:8000/heartbeat_raw";

// ================== 센서 핀 ==================
int resPin = 4;
int mfioPin = 13;
SparkFun_Bio_Sensor_Hub bioHub(resPin, mfioPin);
bioData body;

// ================== 함수 ==================
String getStatus(int bpm) {
  if (bpm < 60) return "low";
  if (bpm > 100) return "high";
  return "normal";
}




// I2C 재시도 함수
bool i2cReadWithRetry(uint8_t addr, uint8_t reg, uint8_t *data, uint8_t len, int retries = 3) {
    for (int i = 0; i < retries; i++) {
        Wire.beginTransmission(addr);
        Wire.write(reg);
        if (Wire.endTransmission(false) == 0) { // false: repeated start
            Wire.requestFrom(addr, len);
            if (Wire.available() >= len) {
                for (uint8_t j = 0; j < len; j++) {
                    data[j] = Wire.read();
                }
                return true;
            }
        }
        delay(5); // 짧은 지연 후 재시도
    }
    return false; // 재시도 실패
}
// ================== setup ==================
void setup() {
  Serial.begin(115200);
  Wire.begin();
   Wire.setClock(100000); // 100kHz로 낮춰 안정화
    delay(100); // 센서 초기화 대기


  // WiFi 연결
  WiFi.begin(ssid, password);
  Serial.print("WiFi 연결중");
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println("\n✅ WiFi 연결됨!");
  Serial.println(WiFi.localIP());

  // 센서 시작
  int result = bioHub.begin();
  if (result == 0) Serial.println("✅ Sensor started");
  else Serial.println("❌ Could not communicate with the sensor!");

  int error = bioHub.configBpm(MODE_ONE);
  if (error == 0) Serial.println("✅ Sensor configured");
  else Serial.println("❌ Error configuring sensor");

  delay(4000); // 버퍼 채우기
}

// ================== loop ==================
void loop() {

  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("🔄 WiFi reconnecting...");
    WiFi.disconnect();
    WiFi.begin(ssid, password);
    delay(2000);
    return;
}

  body = bioHub.readBpm();
  int bpm = int(round(body.heartRate));

  if (bpm > 0) {  // 0 제외
    String status = getStatus(bpm);

    // JSON 만들기
    String json = "{\"bpm\":" + String(bpm) + ",\"status\":\"" + status + "\"}";

    Serial.println("Sending: " + json);

    if (WiFi.status() == WL_CONNECTED) {
      HTTPClient http;
      http.begin(serverUrl);
      http.setTimeout(2000);  // 2초 응답 대기
      http.addHeader("Content-Type", "application/json");

      int httpResponseCode = http.POST(json);

      if (httpResponseCode > 0) {
        Serial.println("✅ Sent successfully, code: " + String(httpResponseCode));
      } else {
        Serial.println("❌ Error sending data, code: " + String(httpResponseCode));
      }

      http.end();
    } else {
      Serial.println("❌ WiFi disconnected");
    }
  }

  delay(1000); // 1초마다 전송
}
