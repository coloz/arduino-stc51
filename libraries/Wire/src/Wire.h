/*
 * SPDX-License-Identifier: MIT
 *
 * Arduino-style I2C master with hardware selection and software fallback.
 *
 * The Wire object is a const table of function pointers so a C sketch can use
 * Wire.begin(), Wire.write(), and similar syntax.  The opt-in C++ profile
 * routes this public header to the overloaded TwoWire wrapper.
 */
#ifndef STC_SOFTWARE_WIRE_H
#define STC_SOFTWARE_WIRE_H

#if defined(__cplusplus) && defined(STCXX_CPP_CORE) && STCXX_CPP_CORE

#include <cpp/WireClass.h>

#else

#include <Arduino.h>

#ifdef __cplusplus
extern "C" {
#endif

/* SDCC indirect calls cannot use callee-specific overlay parameter slots. */
#if defined(__SDCC)
# define STC_WIRE_REENTRANT __reentrant
#else
# define STC_WIRE_REENTRANT
#endif

#ifndef WIRE_BUFFER_LENGTH
# define WIRE_BUFFER_LENGTH 32u
#endif
#if (WIRE_BUFFER_LENGTH < 1u) || (WIRE_BUFFER_LENGTH > 255u)
# error "WIRE_BUFFER_LENGTH must be between 1 and 255 bytes"
#endif
#ifndef BUFFER_LENGTH
# define BUFFER_LENGTH WIRE_BUFFER_LENGTH
#endif
#ifndef WIRE_HAS_TIMEOUT
# define WIRE_HAS_TIMEOUT 1
#endif
#ifndef WIRE_HAS_SLAVE
/* No reliable slave mode exists in the portable polling backend. */
# define WIRE_HAS_SLAVE 0
#endif

#ifndef WIRE_DEFAULT_CLOCK_HZ
# define WIRE_DEFAULT_CLOCK_HZ 100000UL
#endif

#ifndef WIRE_DEFAULT_SDA_PIN
# define WIRE_DEFAULT_SDA_PIN PIN_WIRE_SDA
#endif

#ifndef WIRE_DEFAULT_SCL_PIN
# define WIRE_DEFAULT_SCL_PIN PIN_WIRE_SCL
#endif

#ifndef WIRE_DEFAULT_STRETCH_TIMEOUT_US
# define WIRE_DEFAULT_STRETCH_TIMEOUT_US 25000UL
#endif

#define WIRE_STATUS_SUCCESS        0u
#define WIRE_STATUS_DATA_TOO_LONG  1u
#define WIRE_STATUS_ADDRESS_NACK   2u
#define WIRE_STATUS_DATA_NACK      3u
#define WIRE_STATUS_OTHER_ERROR    4u
#define WIRE_STATUS_TIMEOUT        5u

void Wire_begin(void) STC_WIRE_REENTRANT;
#if defined(STCXX_CPP_CORE) && STCXX_CPP_CORE
void Wire_end(void) STC_WIRE_REENTRANT;
#endif
void Wire_setPins(uint8_t sda_pin, uint8_t scl_pin) STC_WIRE_REENTRANT;
uint8_t Wire_setPinsChecked(uint8_t sda_pin, uint8_t scl_pin) STC_WIRE_REENTRANT;
uint8_t Wire_configurationError(void) STC_WIRE_REENTRANT;
uint8_t Wire_lastError(void) STC_WIRE_REENTRANT;
void Wire_setClock(unsigned long clock_hz) STC_WIRE_REENTRANT;
void Wire_setClockStretchTimeout(unsigned long timeout_us) STC_WIRE_REENTRANT;
void Wire_setWireTimeout(uint32_t timeout_us, uint8_t reset_with_timeout)
    STC_WIRE_REENTRANT;
uint8_t Wire_getWireTimeoutFlag(void) STC_WIRE_REENTRANT;
void Wire_clearWireTimeoutFlag(void) STC_WIRE_REENTRANT;
void Wire_beginTransmission(uint8_t address) STC_WIRE_REENTRANT;
size_t Wire_write(uint8_t value) STC_WIRE_REENTRANT;
uint8_t Wire_endTransmission(void) STC_WIRE_REENTRANT;
uint8_t Wire_endTransmissionStop(uint8_t send_stop) STC_WIRE_REENTRANT;
uint8_t Wire_requestFrom(uint8_t address, uint8_t quantity) STC_WIRE_REENTRANT;
uint8_t Wire_requestFromStop(uint8_t address, uint8_t quantity,
                             uint8_t send_stop) STC_WIRE_REENTRANT;
uint8_t Wire_requestFromInternal(uint8_t address, uint8_t quantity,
                                 uint32_t internal_address,
                                 uint8_t internal_address_size,
                                 uint8_t send_stop) STC_WIRE_REENTRANT;
int Wire_available(void) STC_WIRE_REENTRANT;
int Wire_peek(void) STC_WIRE_REENTRANT;
int Wire_read(void) STC_WIRE_REENTRANT;

typedef struct {
    void (*begin)(void) STC_WIRE_REENTRANT;
    void (*setPins)(uint8_t sda_pin, uint8_t scl_pin) STC_WIRE_REENTRANT;
    void (*setClock)(unsigned long clock_hz) STC_WIRE_REENTRANT;
    void (*setClockStretchTimeout)(unsigned long timeout_us) STC_WIRE_REENTRANT;
    void (*beginTransmission)(uint8_t address) STC_WIRE_REENTRANT;
    size_t (*write)(uint8_t value) STC_WIRE_REENTRANT;
    uint8_t (*endTransmission)(void) STC_WIRE_REENTRANT;
    uint8_t (*requestFrom)(uint8_t address, uint8_t quantity) STC_WIRE_REENTRANT;
    int (*available)(void) STC_WIRE_REENTRANT;
    int (*peek)(void) STC_WIRE_REENTRANT;
    int (*read)(void) STC_WIRE_REENTRANT;
    uint8_t (*endTransmissionStop)(uint8_t send_stop) STC_WIRE_REENTRANT;
    uint8_t (*requestFromStop)(uint8_t address, uint8_t quantity,
                               uint8_t send_stop) STC_WIRE_REENTRANT;
    void (*setWireTimeout)(uint32_t timeout_us, uint8_t reset_with_timeout)
        STC_WIRE_REENTRANT;
    uint8_t (*getWireTimeoutFlag)(void) STC_WIRE_REENTRANT;
    void (*clearWireTimeoutFlag)(void) STC_WIRE_REENTRANT;
    uint8_t (*requestFromInternal)(uint8_t address, uint8_t quantity,
                                   uint32_t internal_address,
                                   uint8_t internal_address_size,
                                   uint8_t send_stop) STC_WIRE_REENTRANT;
    uint8_t (*setPinsChecked)(uint8_t sda_pin, uint8_t scl_pin) STC_WIRE_REENTRANT;
    uint8_t (*configurationError)(void) STC_WIRE_REENTRANT;
    uint8_t (*lastError)(void) STC_WIRE_REENTRANT;
} STCWireClass;

extern const STCWireClass Wire;

#ifdef __cplusplus
}
#endif

#endif /* C facade / C++ class routing */

#endif
