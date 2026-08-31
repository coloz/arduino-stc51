/*
 * SPDX-License-Identifier: MIT
 *
 * Pure-C Arduino-style software SPI master.
 *
 * The SPI object is a const table of function pointers so a C sketch can use
 * SPI.begin(), SPI.transfer(), and similar syntax.  It is not source-compatible
 * with the C++ Arduino SPISettings/SPIClass API.
 */
#ifndef STC_SOFTWARE_SPI_H
#define STC_SOFTWARE_SPI_H

#include <Arduino.h>

#ifdef __cplusplus
extern "C" {
#endif

/* SDCC indirect calls cannot use callee-specific overlay parameter slots. */
#if defined(__SDCC)
# define STC_SPI_REENTRANT __reentrant
#else
# define STC_SPI_REENTRANT
#endif

#ifndef SPI_MODE0
# define SPI_MODE0 0x00u
#endif
#ifndef SPI_MODE1
# define SPI_MODE1 0x01u
#endif
#ifndef SPI_MODE2
# define SPI_MODE2 0x02u
#endif
#ifndef SPI_MODE3
# define SPI_MODE3 0x03u
#endif

#ifndef SPI_DEFAULT_CLOCK_HZ
# define SPI_DEFAULT_CLOCK_HZ 100000UL
#endif

#ifndef SPI_DEFAULT_MOSI_PIN
# define SPI_DEFAULT_MOSI_PIN P3_2
#endif
#ifndef SPI_DEFAULT_MISO_PIN
# define SPI_DEFAULT_MISO_PIN P3_3
#endif
#ifndef SPI_DEFAULT_SCK_PIN
# if defined(PIN_VALID_MASK_P3) && ((PIN_VALID_MASK_P3 & 0x30U) == 0x30U)
#  define SPI_DEFAULT_SCK_PIN P3_4
# else
/* STC8G1K08A exposes only P3.0--P3.3; P5.4 is its portable fallback. */
#  define SPI_DEFAULT_SCK_PIN P5_4
# endif
#endif
#ifndef SPI_DEFAULT_SS_PIN
# if defined(PIN_VALID_MASK_P3) && ((PIN_VALID_MASK_P3 & 0x30U) == 0x30U)
#  define SPI_DEFAULT_SS_PIN P3_5
# else
/* Keep SS adjacent to the fallback clock pin on STC8G1K08A. */
#  define SPI_DEFAULT_SS_PIN P5_5
# endif
#endif

void SPI_begin(void) STC_SPI_REENTRANT;
void SPI_setPins(uint8_t mosi_pin, uint8_t miso_pin, uint8_t sck_pin,
                 uint8_t ss_pin) STC_SPI_REENTRANT;
void SPI_beginTransaction(unsigned long clock_hz, uint8_t bit_order,
                          uint8_t data_mode) STC_SPI_REENTRANT;
uint8_t SPI_transfer(uint8_t value) STC_SPI_REENTRANT;
void SPI_transferBuffer(uint8_t *buffer, size_t length) STC_SPI_REENTRANT;
void SPI_endTransaction(void) STC_SPI_REENTRANT;
void SPI_end(void) STC_SPI_REENTRANT;

typedef struct {
    void (*begin)(void) STC_SPI_REENTRANT;
    void (*setPins)(uint8_t mosi_pin, uint8_t miso_pin, uint8_t sck_pin,
                    uint8_t ss_pin) STC_SPI_REENTRANT;
    void (*beginTransaction)(unsigned long clock_hz, uint8_t bit_order,
                             uint8_t data_mode) STC_SPI_REENTRANT;
    uint8_t (*transfer)(uint8_t value) STC_SPI_REENTRANT;
    void (*transferBuffer)(uint8_t *buffer, size_t length) STC_SPI_REENTRANT;
    void (*endTransaction)(void) STC_SPI_REENTRANT;
    void (*end)(void) STC_SPI_REENTRANT;
} STCSPIClass;

extern const STCSPIClass SPI;

#ifdef __cplusplus
}
#endif

#endif
