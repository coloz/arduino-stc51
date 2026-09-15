#include <Arduino.h>
#include <Wire.h>

/* SDA=P3.2, SCL=P3.3, external pull-ups and common ground required. */
void setup(void) {
    Serial.begin(115200UL);
    if (Wire.setPinsChecked(P3_2, P3_3) != WIRE_STATUS_SUCCESS)
        Serial.println("Invalid I2C pin configuration");
    Wire.begin(); Wire.setWireTimeout(25000UL, 1);
}
void loop(void) {
    uint8_t status;
    Wire.beginTransmission(0x3c);
    status = Wire.endTransmission();
    if (status == WIRE_STATUS_SUCCESS) Serial.println("0x3c ACK");
    else if (status == WIRE_STATUS_TIMEOUT) Serial.println("I2C timeout");
    else Serial.println("I2C transaction failed");
    delay(500);
}
