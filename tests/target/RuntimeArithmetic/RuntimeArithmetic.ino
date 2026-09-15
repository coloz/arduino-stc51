#include <Arduino.h>
extern "C" unsigned char native_runtime_arithmetic(void);

void setup() {
    Serial.begin(38400UL);
    Serial.println("BEGIN runtime-arithmetic");
    unsigned char failures = native_runtime_arithmetic();
    if (failures) {
        Serial.print("FAIL mask ");
        Serial.println(static_cast<unsigned int>(failures));
    }
    Serial.println(failures ? "FAIL runtime-arithmetic" : "PASS runtime-arithmetic");
    Serial.flush();
}
void loop() {}
