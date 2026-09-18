#include <type_traits>
#include <Arduino.h>
#include <USB.h>
static_assert(std::is_same<decltype(Serial1), HardwareSerial>::value, "UART1 remains hardware");
static_assert(std::is_same<decltype(Serial0), HardwareSerial>::value, "ESP32-style UART alias");
#if ARDUINO_USB_CDC_ON_BOOT
static_assert(std::is_same<decltype(Serial), USBCDC>::value, "Serial uses CDC on boot");
#else
static_assert(std::is_same<decltype(Serial), HardwareSerial>::value, "default Serial remains UART1");
#endif
static_assert(std::is_same<decltype(USBSerial), USBCDC>::value, "explicit CDC");
void api_check() {
    uint8_t data[64];
    USBSerial.begin(); SerialUSB.begin(115200, SERIAL_8N1);
    USBSerial.println("hello"); USBSerial.print(123);
    USBSerial.write(data, sizeof(data)); USBSerial.write("hello");
    USBSerial.peek(); USBSerial.read(); USBSerial.readBytes(data,sizeof(data));
    USBSerial.readStringUntil('\n'); USBSerial.parseInt();
    USBSerial.baud(); USBSerial.stopbits(); USBSerial.paritytype(); USBSerial.numbits();
    USBSerial.dtr(); USBSerial.rts(); USBSerial.readBreak();
    USBSerial.setTimeout(100); USBSerial.setTxTimeoutMs(100);
    USBSerial.enableReboot(false); USBSerial.rebootEnabled();
    if (USBSerial) USBSerial.flush();
    USBSerial.end(); USB.begin(); USBDevice.detach();
}
