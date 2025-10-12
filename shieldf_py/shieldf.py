#include <ArduinoBLE.h>
#include <MyoWare.h>

// ===== 사용자 설정 =====
const char* kLocalName = "MyoWareSensor1";     // 광고에 보일 이름(필수 변경 지점)
const bool   debugLogging = true;

// MyoWare 라이브러리 객체 (상태 LED 등 유틸 포함)
MyoWare myoware;

// MyoWare 라이브러리에서 제공하는 동일 UUID 사용 (Central과 반드시 일치)
BLEService myoWareService(MyoWareBLE::uuidMyoWareService.c_str());
BLEStringCharacteristic sensorCharacteristic(
  MyoWareBLE::uuidMyoWareCharacteristic.c_str(),
  BLERead | BLENotify, 20);

// 선택: ENVELOPE(평활) 또는 RAW
MyoWare::OutputType outputType = MyoWare::ENVELOPE;

// 아날로그 입력 핀 (보드에 따라 다를 수 있음)
// 무선 쉴드의 센서 출력(ENVELOPE 또는 RAW)이 연결된 핀으로 맞춰주세요.
#if defined(ARDUINO_NANO33BLE) || defined(ARDUINO_ARDUINO_NANO33BLE)
  const int kAnalogPin = A0;
#else
  const int kAnalogPin = A0; // 필요 시 보드 핀맵 문서 확인
#endif

void setup() {
  Serial.begin(115200);
  while (!Serial) {}

  pinMode(myoware.getStatusLEDPin(), OUTPUT);

  // (선택) 출력값 변환 여부
  myoware.setConvertOutput(false); // true로 하면 라이브러리 변환 사용

  if (!BLE.begin()) {
    Serial.println("Starting BLE failed!");
    while (1) {}
  }

  // ----- 로컬 이름 설정 (요청하신 핵심 수정) -----
  BLE.setLocalName(kLocalName);
  BLE.setDeviceName(kLocalName);

  // 서비스/캐릭터리스틱 구성
  BLE.setAdvertisedService(myoWareService);
  myoWareService.addCharacteristic(sensorCharacteristic);
  BLE.addService(myoWareService);

  // 초기값
  sensorCharacteristic.writeValue("0.0");

  BLE.advertise();

  if (debugLogging) {
    Serial.println("MyoWare BLE Peripheral (Shield)");
    Serial.print("Advertising as: ");
    Serial.println(kLocalName);
    Serial.print("Service UUID: ");
    Serial.println(MyoWareBLE::uuidMyoWareService.c_str());
    Serial.print("Char UUID   : ");
    Serial.println(MyoWareBLE::uuidMyoWareCharacteristic.c_str());
  }
}

void loop() {
  // 중앙 장치 연결 여부에 따라 상태 LED 간단 표시
  BLEDevice central = BLE.central();
  if (central) {
    digitalWrite(myoware.getStatusLEDPin(), HIGH);
    while (central.connected()) {
      // ---- 센서 읽기 ----
      // 실제 센서 배선에 맞는 핀/출력 사용.
      // ENVELOPE/RAW를 보드 배선 스위치 또는 코드로 선택했다면 그에 맞춰 읽기.
      int raw = analogRead(kAnalogPin);

      // 필요 시 해상도/전압 보정 (예: 10bit → 0~1023, 12bit → 0~4095)
      // 여기서는 간단히 정수값을 문자열로 전송
      char buf[20];
      dtostrf((double)raw, 1, 0, buf); // 소수점 없이 전송(필요 시 자릿수 변경)
      sensorCharacteristic.writeValue(buf); // Notify 포함

      delay(5); // 전송 속도 조절
    }
    digitalWrite(myoware.getStatusLEDPin(), LOW);
  }

  // 연결 안 된 동안엔 광고 유지, LED 블링크
  myoware.blinkStatusLED();
}
