#include <Arduino.h>
#include <cpp/stc_c_hal.h>
extern "C" uint8_t serial_test_seed_wrapped(void);
extern "C" uint8_t serial_test_interrupts_enabled(void);
static uint8_t checks, failures, first_failure;
static void text(const char *s) {
    while (*s) Serial_write(static_cast<uint8_t>(*s++));
}
static void decimal(uint8_t n) {
    if (n >= 10u) Serial_write(static_cast<uint8_t>('0' + n / 10u));
    Serial_write(static_cast<uint8_t>('0' + n % 10u));
}
static void check(bool condition) {
    ++checks;
    if (!condition) {
        if (!failures) first_failure = checks;
        ++failures;
    }
}
void setup() {
    uint8_t buffer[4] = {0xa1u, 0xa2u, 0xa3u, 0xa4u};
    Serial_begin(38400UL);
    text("BEGIN serial-receive\n");
    check(Serial_available() == 0);
    check(Serial_peek() == -1);
    check(Serial_read() == -1);
    check(Serial_readBytes(static_cast<void *>(0), 3u) == 0u);
    check(serial_test_seed_wrapped() == 1u);
    check(Serial_available() == 3);
    check(Serial_peek() == 0x31);
    check(Serial_peek() == 0x31);
    check(Serial_readBytes(static_cast<void *>(0), 3u) == 0u);
    check(Serial_available() == 3);
    check(Serial_read() == 0x31);
    check(Serial_available() == 2);
    check(Serial_readBytes(buffer, 0u) == 0u);
    check(buffer[0] == 0xa1u);
    check(Serial_readBytes(buffer, 1u) == 1u);
    check(buffer[0] == 0x82u);
    check(buffer[1] == 0xa2u);
    check(Serial_peek() == 0xe7);
    check(Serial_readBytes(buffer + 1u, 3u) == 1u);
    check(buffer[1] == 0xe7u && buffer[2] == 0xa3u && buffer[3] == 0xa4u);
    check(Serial_available() == 0);
    check(Serial_peek() == -1);
    check(Serial_read() == -1);
    noInterrupts();
    check(Serial_overflow());
    check(serial_test_interrupts_enabled() == 0u);
    check(!Serial_overflow());
    interrupts();
    check(serial_test_interrupts_enabled() == 1u);
    check(!Serial_overflow());
    check(serial_test_interrupts_enabled() == 1u);
    check(serial_test_seed_wrapped() == 1u);
    Serial_end();
    check(Serial_available() == 0);
    check(Serial_peek() == -1);
    check(Serial_read() == -1);
    check(Serial_readBytes(buffer, 4u) == 0u);
    Serial_begin(38400UL);
    check(Serial_available() == 0);
    check(Serial_peek() == -1);
    check(Serial_read() == -1);
    check(!Serial_overflow());
    check(serial_test_seed_wrapped() == 1u);
    check(Serial_readBytes(buffer, 4u) == 3u);
    check(buffer[0] == 0x31u && buffer[1] == 0x82u && buffer[2] == 0xe7u && buffer[3] == 0xa4u);
    check(Serial_available() == 0);
    check(Serial_peek() == -1);
    if (failures) { text("FAIL check "); decimal(first_failure); text("\n"); }
    text("CHECKS "); decimal(checks); text("\n");
    text(!failures && checks == 43u ? "PASS serial-receive\n" : "FAIL serial-receive\n");
}
void loop() {}
