## [25_HC210] 반려동물 근육 피로도 측정 디바이스 및 앱 개발


### 1. 프로젝트 개요
---

#### 1-1 프로젝트 소개
- 프로젝트 명: 반려동물 근육 피로도 측정 디바이스 및 앱 개발
- 프로젝트 정의: 바이오센싱 디바이스를 통해 반려동물의 근육 피로도 및 심박수를 실시간으로 측정하고, 이를 시각화하여 반려동물의 건강 상태를 한눈에 확인할 수 있는 종합 헬스케어 플랫폼

<img src="./servicevisual.png" width="400px" alt="SoH 홈화면">


#### 1-2. 개발 배경 및 필요성
현대 사회에서 반려동물은 단순한 반려 존재를 넘어 가족 구성원으로 자리 잡고 있습니다. 이에 따라 반려동물 헬스케어 시장 역시 주목받고 있으며, 특히 고령 반려동물의 근육 약화·퇴행성 질환은 조기 진단이 어려워 만성 질환으로 발전하기 쉽습니다. 그러나 기존의 반려동물 헬스케어 서비스는 보호자가 데이터를 직접 입력해야 하는 수동적 방식으로, 실시간 모니터링이 어렵습니다. 따라서 생체 신호 기반의 자동 측정 및 분석이 가능한 스마트 디바이스와, 이를 가정에서도 쉽게 파악할 수 있도록 하는 웹서비가 필요합니다.

#### 1-3. 프로젝트 특장점
- 정량적 데이터 기반 근육 피로도 분석: EMG·PPG 신호를 통해 근육 상태를 실시간 수치화
- 하네스 일체형 IoT 디바이스: 센서·배터리 내장형 구조로 쉽게 착용 가능
- 실시간 웹 대시보드: FastAPI 기반 백엔드와 React 프론트를 통한 실시간 시각화 및 리포트 제공
- 응급 및 예방 기능 통합: 응급처치 가이드, 예방접종 일정 관리 등 종합 건강관리 기능

#### 1-4. 주요 기능
- 근전도 기반 근육 피로도 측정: RMS 및 Median Frequency 분석을 통한 실시간 피로도 산출
- PPG 센서 기반 심박수 분석: 심박수 변화 감지 및 이상치 제거 로직 적용
- 실시간 데이터 시각화: EMG·ECG 데이터를 1~2초 단위로 웹에 반영
- 주간·월간 리포트 자동 생성: 심박수 평균값 및 최저/최고 수치 시각화
- 응급처치 및 예방접종 관리: 6가지 응급상황별 단계별 가이드 및 월별 접종 일정 표시
- 모바일 대응: 모바일에서도 접근 가능한 반응형 웹 구조

#### 1-5. 기대 효과 및 활용 분야

##### 기대 효과
- 반려동물의 건강 데이터를 실시간 모니터링하여 조기 질환 대응 가능
- 보호자의 시간·비용 절감 및 관리 효율성 향상
- 정량적 피로도 데이터 축적을 통한 반려동물 생리 연구 및 의료데이터 활용 가능
- IoT·AI 헬스케어 시장 확장성 확보

##### 활용 분야
- 고령 반려동물의 근육 건강 관리
- 스포츠견·탐지견 등 전문 동물의 훈련 모니터링
- 동물병원 및 수의학 연구기관의 생체데이터 분석
- 스마트 반려동물 헬스케어 플랫폼 개발

#### 1-6. 기술 스택

- 프론트엔드: HTML, CSS, JavaScript
- 백엔드: Python, FastAPI, Node.js
- AI/Signal Processing:  NumPy, SciPy
- 데이터베이스: SQlite
- IoT/디바이스: Arduino, ESP32, MyoWare 2.0 EMG Sensor, MAX30101 PPG Sensor

***

### 2. 팀원 소개
   
| 이름 | 역할 |
|------|------|
| 이수연 | 총괄 팀장 / UI/UX 기획 |
| 김수영 | UI/UX 기획 / 하드웨어 설계 |
| 송현아 | 하드웨어 설계 / 백엔드(EMG) |
| 강민진 | 백엔드(EMG) / API 개발 |
| 이채은 | 백엔드(PPG) / 신호 전처리 |
| 장기영 | 기술 자문 / 프로젝트 멘토링 |

***

### 3. 시스템 구성도

- 서비스 구성도

- 엔티티 관계도

  ---

### 4. 작품 소개영상

[![25_HC210 시연동영상](https://img.youtube.com/vi/x0vZS7mmrKk/0.jpg)](https://youtu.be/x0vZS7mmrKk)

---

### 5. 핵심 소스코드

- 소스코드 설명: 핵심 PPG 신호 분석 로직 

```cpp
#include <HTTPClient.h>
#include <SparkFun_Bio_Sensor_Hub_Library.h>

SparkFun_Bio_Sensor_Hub bioHub(4, 13);
bioData body;

String getStatus(int bpm) {
  if (bpm < 60) return "low";
  if (bpm > 100) return "high";
  return "normal";
}

void loop() {
  body = bioHub.readBpm();                // 💓 심박수 측정
  int bpm = int(round(body.heartRate));   // 소수점 제거

  if (bpm > 0) {                          // 0 제외 (유효값만)
    String status = getStatus(bpm);       // 상태 분류

    // JSON 데이터 생성
    String json = "{\"bpm\":" + String(bpm) + ",\"status\":\"" + status + "\"}";
    Serial.println("Sending: " + json);

    // 서버로 전송
    HTTPClient http;
    http.begin("http://172.20.10.2:8000/heartbeat_raw");
    http.addHeader("Content-Type", "application/json");
    int httpResponseCode = http.POST(json);

    if (httpResponseCode > 0)
      Serial.println("✅ Sent successfully, code: " + String(httpResponseCode));
    else
      Serial.println("❌ Error sending data, code: " + String(httpResponseCode));

    http.end();
  }

  delay(1000); // 1초마다 전송
}


