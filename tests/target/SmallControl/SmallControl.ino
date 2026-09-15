#include <Arduino.h>

// A small periodic controller: one output, millis scheduling and UART status.
// Uses the real Arduino C++ facade and core; no injected peripheral backend.
static const uint8_t outputPin = P1_3; // Keep UART1 P3.0/P3.1 free.
static uint8_t checks, failures, transitions;
static bool finished;
static unsigned long lastTransition;

static void text(const char *value) {
    while (*value) Serial.write(static_cast<uint8_t>(*value++));
}

static void check(bool condition) {
    ++checks;
    if (!condition) {
        ++failures;
        text("FAIL small-control check\n");
    }
}

static void finish() {
    text("CHECKS ");
    Serial.write(static_cast<uint8_t>('0' + checks / 10u));
    Serial.write(static_cast<uint8_t>('0' + checks % 10u));
    text("\n");
    text(failures || checks != 14u ? "FAIL small-control\n" : "PASS small-control\n");
    Serial.flush();
    finished = true;
}

void setup() {
    Serial.begin(38400UL);
    text("BEGIN small-control\n");
    check(digitalPinIsValid(outputPin));
    if (!digitalPinIsValid(outputPin)) { finish(); return; }
    pinMode(outputPin, OUTPUT);
    digitalWrite(outputPin, LOW);
    check(digitalRead(outputPin) == LOW);
    digitalWrite(outputPin, HIGH);
    check(digitalRead(outputPin) == HIGH);
    digitalWrite(outputPin, LOW);
    check(Serial && !Serial.configurationError());

    unsigned long start = millis();
    delay(3);
    unsigned long elapsed = millis() - start;
    check(elapsed >= 3UL && elapsed < 100UL);
    start = micros();
    delayMicroseconds(50);
    elapsed = micros() - start;
    check(elapsed >= 50UL && elapsed < 5000UL);
    lastTransition = millis();
}

void loop() {
    if (finished) return;
    unsigned long now = millis();
    if (now - lastTransition < 2UL) return;
    lastTransition = now;
    ++transitions;
    uint8_t level = transitions & 1u ? HIGH : LOW;
    digitalWrite(outputPin, level);
    check(digitalRead(outputPin) == level);
    if (transitions == 8u) finish();
}
