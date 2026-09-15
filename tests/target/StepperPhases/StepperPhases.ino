#include <Arduino.h>
#include <cpp/stc_c_hal.h>
#include <Stepper.h>

// Avoid UART1. These logical pins exist on every declared C++ target.
static const uint8_t pins[5] = {P1_3, P1_4, P1_5, P1_6, P3_5};
static unsigned char checks, failures;
static void text(const char *s) {
    while (*s) Serial_write(static_cast<uint8_t>(*s++));
}
static void decimal(unsigned char n) {
    if (n >= 10) Serial_write(static_cast<uint8_t>('0' + n / 10));
    Serial_write(static_cast<uint8_t>('0' + n % 10));
}
static void check(bool condition) {
    ++checks;
    if (!condition) {
        ++failures; text("FAIL check "); decimal(checks); text("\n");
    }
}
static uint8_t outputs(uint8_t count) {
    uint8_t bits = 0;
    for (uint8_t i = 0; i < count; ++i)
        if (digitalRead(pins[i]) == HIGH) bits |= static_cast<uint8_t>(1u << i);
    return bits;
}
static void winding(Stepper &motor, uint8_t count, uint8_t period,
                    const uint8_t *forward) {
    check(bool(motor));
    motor.step(1); check(outputs(count) == 0); // No speed configured yet.
    motor.setSpeed(3000); check(bool(motor));
    for (uint8_t i = 0; i < period; ++i) {
        motor.step(1); check(outputs(count) == forward[i]);
    }
    for (uint8_t i = 0; i < period; ++i) {
        motor.step(-1);
        uint8_t index = static_cast<uint8_t>((period + period - 2u - i) % period);
        check(outputs(count) == forward[index]);
    }
    uint8_t before = outputs(count);
    motor.step(0); check(outputs(count) == before);
    motor.release(); check(outputs(count) == 0 && bool(motor));
    motor.setSpeed(0); check(!motor && motor.status() == STEPPER_STATUS_INVALID_SPEED);
    motor.step(-1); check(outputs(count) == 0);
    motor.setSpeed(-1); check(!motor && motor.status() == STEPPER_STATUS_INVALID_SPEED);
    motor.setSpeed(3000); check(bool(motor));
    motor.step(1); check(outputs(count) == forward[0]);
    motor.release();
}
void setup() {
    Serial_begin(38400UL); text("BEGIN stepper-phases\n");
    bool valid = true;
    for (uint8_t i = 0; i < 5; ++i) valid = valid && digitalPinIsValid(pins[i]);
    check(valid);
    if (!valid) return;
    const uint8_t twoPhases[4] = {3, 1, 0, 2};
    const uint8_t fourPhases[4] = {6, 10, 9, 5};
    const uint8_t fivePhases[10] = {18, 26, 10, 11, 9, 13, 5, 21, 20, 22};
    Stepper two(200, pins[0], pins[1]);
    Stepper four(200, pins[0], pins[1], pins[2], pins[3]);
    Stepper five(200, pins[0], pins[1], pins[2], pins[3], pins[4]);
    winding(two, 2, 4, twoPhases);
    winding(four, 4, 4, fourPhases);
    winding(five, 5, 10, fivePhases);
    Stepper copy(two); check(copy && two);
    copy.setSpeed(0); check(!copy && two);
    two.step(1); check(outputs(2) == 1);
    copy.step(1); check(outputs(2) == 1);
    copy.setSpeed(3000); copy.step(-1); check(outputs(2) == 2);
    two.step(-1); check(outputs(2) == 3);
    two.release();
    text("CHECKS "); decimal(checks); text("\n");
    text(failures || checks != 73 ? "FAIL stepper-phases\n" : "PASS stepper-phases\n");
}
void loop() {}
