#include <Arduino.h>
#include <cpp/stc_c_hal.h>

// Logical pins valid across all declared models; avoid UART1 P3.0/P3.1.
#define PROBE_PIN0 P1_3
#define PROBE_PIN1 P1_4
#define PROBE_PIN2 P1_5
#define PROBE_PIN3 P1_6
#define PROBE_PIN4 P3_5
#define PROBE_PIN5 P3_2
#define PROBE_PIN6 P3_3
#define PROBE_PIN7 P3_4

// Select exactly one real library. Reporting uses the C UART boundary so
// unrelated C++ Print formatting does not dominate small-device capacity.
#ifndef STCXX_LIBRARY_CASE
#error Select STCXX_LIBRARY_CASE from 1 to 6
#endif
#if STCXX_LIBRARY_CASE == 1
#include <Wire.h>
#define PROBE_NAME "Wire"
#define PROBE_CHECKS 11u
#elif STCXX_LIBRARY_CASE == 2
#include <SPI.h>
#define PROBE_NAME "SPI"
#define PROBE_CHECKS 11u
#elif STCXX_LIBRARY_CASE == 3
#include <SoftwareSerial.h>
#define PROBE_NAME "SoftwareSerial"
#define PROBE_CHECKS 12u
#elif STCXX_LIBRARY_CASE == 4
#include <LiquidCrystal.h>
#define PROBE_NAME "LiquidCrystal"
#define PROBE_CHECKS 9u
#elif STCXX_LIBRARY_CASE == 5
#include <Stepper.h>
#define PROBE_NAME "Stepper"
#define PROBE_CHECKS 10u
#elif STCXX_LIBRARY_CASE == 6
#include <SD.h>
#define PROBE_NAME "SD"
#define PROBE_CHECKS 12u
#else
#error Invalid STCXX_LIBRARY_CASE
#endif

static unsigned char checks;
static unsigned char failures;
static void text(const char *value) {
    while (*value) Serial_write(static_cast<uint8_t>(*value++));
}
static void decimal(unsigned char value) {
    if (value >= 10u) Serial_write(static_cast<uint8_t>('0' + value / 10u));
    Serial_write(static_cast<uint8_t>('0' + value % 10u));
}
static void check(bool condition) {
    ++checks;
    if (!condition) {
        ++failures;
        text("FAIL check "); decimal(checks); text("\n");
    }
}

static void libraryChecks() {
#if STCXX_LIBRARY_CASE == 1
    Wire.end();
    check(Wire.available() == 0 && Wire.read() == -1 && Wire.peek() == -1);
    check(Wire.setPinsChecked(PROBE_PIN0, PROBE_PIN0) == WIRE_STATUS_OTHER_ERROR);
    check(Wire.configurationError() == WIRE_STATUS_OTHER_ERROR);
    check(Wire.setPinsChecked(PROBE_PIN0, PROBE_PIN1) == WIRE_STATUS_SUCCESS);
    Wire.begin();
    Wire.setWireTimeout(1000UL, true);
    Wire.clearWireTimeoutFlag();
    check(!Wire.getWireTimeoutFlag());
    Wire.beginTransmission(0x50);
    uint8_t buffer[WIRE_BUFFER_LENGTH + 1u] = {};
    check(Wire.write(buffer, sizeof(buffer)) == WIRE_BUFFER_LENGTH);
    check(Wire.getWriteError() != 0);
    check(Wire.endTransmission() == WIRE_STATUS_DATA_TOO_LONG);
    Wire.clearWriteError();
    Wire.beginTransmission(0x50);
    check(Wire.write(static_cast<const uint8_t *>(0), 1u) == 0 && Wire.getWriteError() != 0);
    Wire.end();
    check(Wire.write(uint8_t(7)) == 0);
    check(Wire.available() == 0 && Wire.read() == -1);
#elif STCXX_LIBRARY_CASE == 2
    SPI.end();
    check(SPI.setPinsChecked(PROBE_PIN0, PROBE_PIN0, PROBE_PIN2, PROBE_PIN3) == STC_SPI_INVALID);
    check(SPI.configurationError() == STC_SPI_INVALID);
    check(SPI.setPinsChecked(PROBE_PIN0, PROBE_PIN1, PROBE_PIN2, PROBE_PIN3) == STC_SPI_OK);
    SPI.begin();
    check(SPI.beginTransactionChecked(SPISettings(100000UL, MSBFIRST, SPI_MODE0)) == STC_SPI_OK);
    check(SPI.beginTransactionChecked(SPISettings()) == STC_SPI_BUSY);
    check(SPI.setPinsChecked(PROBE_PIN4, PROBE_PIN5, PROBE_PIN6, PROBE_PIN7) == STC_SPI_BUSY);
    SPI.endTransaction();
    check(SPI.beginTransactionChecked(SPISettings(0UL, MSBFIRST, SPI_MODE0)) == STC_SPI_INVALID);
    check(SPI.beginTransactionChecked(SPISettings(100000UL, MSBFIRST, 4u)) == STC_SPI_INVALID);
    check(SPI.beginTransactionChecked(SPISettings(100000UL, LSBFIRST, SPI_MODE3)) == STC_SPI_OK);
    SPI.endTransaction();
    SPI.setClockDivider(SPI_CLOCK_DIV16);
    check(SPI.configurationError() == STC_SPI_OK);
    SPI.end();
    check(SPI.setPinsChecked(PROBE_PIN4, PROBE_PIN5, PROBE_PIN6, PROBE_PIN7) == STC_SPI_OK);
#elif STCXX_LIBRARY_CASE == 3
    SoftwareSerial first(PROBE_PIN0, PROBE_PIN1);
    SoftwareSerial second(PROBE_PIN2, PROBE_PIN3);
    SoftwareSerial invalid(NOT_A_PIN, PROBE_PIN1);
    check(!first && first.read() == -1 && first.available() == 0);
    first.begin(9600UL);
    check(first && first.isListening());
    invalid.begin(9600UL);
    check(!invalid && first.isListening());
    SoftwareSerial copy(first);
    check(!copy && first.isListening());
    check(copy.listen() && !first && copy.isListening());
    copy.end();
    check(!copy && !copy.isListening());
    check(first.listen() && first.isListening());
    second = first;
    check(!second && first.isListening());
    second.begin(9600UL);
    check(second && !first);
    check(second.stopListening() && !second.isListening());
    check(second.listen() && second.isListening());
    second.end();
    check(second.write(uint8_t(7)) == 0 && second.getWriteError() != 0);
#elif STCXX_LIBRARY_CASE == 4
    LiquidCrystal first(PROBE_PIN0, PROBE_PIN1, PROBE_PIN2, PROBE_PIN3, PROBE_PIN4, PROBE_PIN5);
    LiquidCrystal invalid(NOT_A_PIN, PROBE_PIN1, PROBE_PIN2, PROBE_PIN3, PROBE_PIN4, PROBE_PIN5);
    check(first && !invalid);
    first.begin(16, 2);
    check(bool(first));
    check(first.write(uint8_t('A')) == 1);
    check(invalid.write(uint8_t('B')) == 0 && invalid.getWriteError() != 0);
    check(first.write(uint8_t('C')) == 1 && first.getWriteError() == 0);
    LiquidCrystal copy(first);
    copy.begin(16, 2);
    check(copy && first);
    copy.clear();
    copy.setCursor(1, 1);
    check(copy.write(uint8_t('D')) == 1);
    first.begin(0, 2);
    check(!first && copy);
    check(copy.write(uint8_t('E')) == 1);
#elif STCXX_LIBRARY_CASE == 5
    Stepper first(200, PROBE_PIN0, PROBE_PIN1);
    Stepper second(200, PROBE_PIN2, PROBE_PIN3, PROBE_PIN4, PROBE_PIN5);
    Stepper invalid(0, PROBE_PIN0, PROBE_PIN1);
    check(bool(first));
    check(bool(second));
    check(!invalid && invalid.status() == STEPPER_STATUS_INVALID_STEPS);
    first.setSpeed(60);
    check(first.status() == STEPPER_STATUS_SUCCESS);
    second.setSpeed(0);
    check(!second && second.status() == STEPPER_STATUS_INVALID_SPEED);
    check(first.status() == STEPPER_STATUS_SUCCESS);
    second.setSpeed(120);
    check(bool(second));
    first.step(1);
    second.step(-1);
    first.release();
    second.release();
    check(first && second);
    Stepper copy(first);
    copy.setSpeed(-1);
    check(!copy && first);
    check(copy.version() == 5);
#elif STCXX_LIBRARY_CASE == 6
    SD.end();
    check(!SD.setPins(NOT_A_PIN, PROBE_PIN1, PROBE_PIN2, PROBE_PIN3));
    check(SD.error() == SD_ERROR_INVALID_PIN);
    File missing = SD.open("MISSING.TXT", FILE_READ);
    check(!missing && missing.read() == -1);
    check(!SD.exists("MISSING.TXT"));
    check(!SD.remove("MISSING.TXT"));
    File copy(missing);
    check(!copy && !missing);
    File moved(static_cast<File &&>(copy));
    check(!moved && !copy);
    check(moved.write(uint8_t(7)) == 0 && moved.getWriteError() != 0);
    check(!moved.seek(0) && moved.position() == 0 && moved.size() == 0);
    File next = moved.openNextFile();
    check(!next && !next.isDirectory());
    moved.close();
    check(moved.available() == 0 && moved.peek() == -1);
    check(!SD.mkdir("DIR") && !SD.rmdir("DIR"));
#endif
}

void setup() {
    Serial_begin(38400UL);
    text("BEGIN library-" PROBE_NAME "\n");
    const uint8_t pins[] = {PROBE_PIN0, PROBE_PIN1, PROBE_PIN2, PROBE_PIN3,
                            PROBE_PIN4, PROBE_PIN5, PROBE_PIN6, PROBE_PIN7};
    for (unsigned char i = 0; i < sizeof(pins); ++i) {
        if (!digitalPinIsValid(pins[i])) { text("FAIL fixture pin\n"); return; }
    }
    libraryChecks();
    text("CHECKS "); decimal(checks); text("\n");
    text(failures || checks != PROBE_CHECKS ? "FAIL library-" : "PASS library-");
    text(PROBE_NAME "\n");
}
void loop() {}
