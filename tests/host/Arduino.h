#ifndef STC_TEST_ARDUINO_H
#define STC_TEST_ARDUINO_H
/* Model only the GPIO/time boundary; compile the real library implementations. */
#include <stddef.h>
#include <stdint.h>
#include <stdbool.h>
#include <string.h>
#define LOW 0u
#define HIGH 1u
#define INPUT 0u
#define OUTPUT 1u
#define INPUT_PULLUP 2u
#define OUTPUT_OPEN_DRAIN 3u
#define LSBFIRST 0u
#define MSBFIRST 1u
#define STC_XDATA_BYTES 8192UL
#define PIN_SPI_MOSI 0x13u
#define PIN_SPI_MISO 0x14u
#define PIN_SPI_SCK 0x15u
#define PIN_SPI_SS 0x12u
#define PIN_WIRE_SDA 0x32u
#define PIN_WIRE_SCL 0x33u
#define STC_VARIANT_PHYSICAL_ALIAS(pin) 0xffu
#ifdef __cplusplus
#include "Stream.h"
extern "C" {
#endif
unsigned long millis(void);
unsigned long micros(void);
void delay(unsigned long ms);
void delayMicroseconds(unsigned int us);
void yield(void);
void pinMode(uint8_t pin, uint8_t mode);
void digitalWrite(uint8_t pin, uint8_t value);
int digitalRead(uint8_t pin);
uint8_t digitalPinIsValid(uint8_t pin);
uint8_t digitalPinsSharePhysicalPad(uint8_t left, uint8_t right);
#ifdef __cplusplus
}
#endif
#endif
