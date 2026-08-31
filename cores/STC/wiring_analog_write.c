#include "Arduino.h"

void analogWrite(uint8_t pin, int value) STC_REENTRANT
{
    if (digitalPinIsValid(pin) == 0u) {
        return;
    }

    /* Arduino-compatible fallback for pins without a declared PWM channel. */
    pinMode(pin, OUTPUT);
    digitalWrite(pin, (value < 128) ? LOW : HIGH);
}
