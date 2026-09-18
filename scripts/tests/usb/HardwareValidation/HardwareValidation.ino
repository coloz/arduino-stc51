/* Hardware fixture for scripts/check-usb-hardware.py. No key presses or
 * pointer movements are generated. Build with CDC enabled and the actual
 * ISP clock. Define USB_TEST_COMPOSITE=1 to include neutral HID reports. */
#include <USB.h>
#if USB_TEST_COMPOSITE
#include <Keyboard.h>
#include <Mouse.h>
#include <HID.h>
const uint8_t rawDescriptor[] PROGMEM = {
  0x06,0x00,0xff,0x09,0x01,0xa1,0x01,0x85,0x03,
  0x15,0x00,0x26,0xff,0x00,0x75,0x08,0x95,0x08,
  0x09,0x01,0x81,0x02,0x95,0x08,0x09,0x01,0x91,0x02,0xc0
};
HIDSubDescriptor rawNode(rawDescriptor, sizeof(rawDescriptor));
#endif
uint8_t state, lengthLow, echoBuffer[64], echoCount;
uint16_t remaining;
unsigned long lastToggle, toggles;
bool led;

void put32(uint8_t *data, unsigned long value) {
  for (uint8_t i = 0; i < 4; ++i) { data[i] = (uint8_t)value; value >>= 8; }
}
void status() {
  uint8_t data[24] = {'S','T','C',1};
  put32(data + 4, millis()); put32(data + 8, Serial.baud());
  data[12] = Serial.dtr(); data[13] = Serial.rts();
  data[14] = Serial.stopbits(); data[15] = Serial.paritytype();
  data[16] = Serial.numbits(); data[17] = (bool)Serial;
  data[18] = Serial.getWriteError(); data[19] = Serial.rebootEnabled();
  put32(data + 20, toggles); Serial.write(data, sizeof(data));
}
void setup() {
#if USB_TEST_COMPOSITE
  HID().AppendDescriptor(&rawNode); HID().RegisterReport(3, 8);
  Keyboard.begin(); Mouse.begin();
#endif
  pinMode(P5_2, OUTPUT); Serial.begin(115200); Serial.setTxTimeoutMs(500);
}
void loop() {
  if (millis() - lastToggle >= 100UL) {
    lastToggle = millis(); led = !led; digitalWrite(P5_2, led); ++toggles;
  }
#if USB_TEST_COMPOSITE
  uint8_t report[64];
  int count = HID().read(report, sizeof(report));
  if (count == 9 && report[0] == 3) HID().SendReport(3, report + 1, 8);
#endif
  while (Serial.available()) {
    uint8_t value = (uint8_t)Serial.read();
    if (state == 1) { lengthLow = value; state = 2; }
    else if (state == 2) {
      remaining = lengthLow | ((uint16_t)value << 8); echoCount = 0;
      state = remaining ? 3 : 0;
    } else if (state == 3) {
      echoBuffer[echoCount++] = value; --remaining;
      if (echoCount == sizeof(echoBuffer) || !remaining) {
        Serial.write(echoBuffer, echoCount); echoCount = 0;
      }
      if (!remaining) state = 0;
    } else if (state == 4) { Serial.enableReboot(value != 0); state = 0; }
    else if (value == 'E') state = 1;
    else if (value == 'S') status();
    else if (value == 'U') Serial.println("你好啊 / STC USB CDC");
    else if (value == 'R') state = 4;
    else if (value == 'P') delay(250);
    else if (value == 'B') {
      uint8_t result[4]; put32(result, (unsigned long)Serial.readBreak());
      Serial.write(result, sizeof(result));
    } else if (value == 'N') { Serial.end(); delay(50); Serial.begin(115200); }
    else if (value == 'D') { USBDevice.detach(); delay(300); USBDevice.attach(); }
    else if (value == 'H') {
#if USB_TEST_COMPOSITE
      Mouse.move(0, 0, 0); Keyboard.releaseAll();
#endif
      Serial.write('H');
    }
  }
}
