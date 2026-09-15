#ifndef STC_STEPPER_TEST_ARDUINO_H
#define STC_STEPPER_TEST_ARDUINO_H
#include <stddef.h>
#include <stdint.h>
#define LOW 0u
#define HIGH 1u
#define INPUT 0u
#define OUTPUT 1u
#define OUTPUT_OPEN_DRAIN 3u
#define NOT_A_PIN 255u
#ifdef __cplusplus
extern "C" {
#endif
unsigned long micros(void);
void delayMicroseconds(unsigned int us);
void yield(void);
void pinMode(uint8_t pin, uint8_t mode);
void digitalWrite(uint8_t pin, uint8_t value);
uint8_t digitalPinIsValid(uint8_t pin);
uint8_t digitalPinsSharePhysicalPad(uint8_t left, uint8_t right);
void stepper_test_clear(void);
unsigned int stepper_test_writes(void);
uint8_t stepper_test_value(uint8_t pin);
void stepper_test_set_hook(void (*hook)(void));
#ifdef __cplusplus
}
#endif
#endif
