/*
 * SPDX-License-Identifier: MIT
 *
 * Clean-room plain-C software UART for the unified arduino-stc51 core.
 *
 * The SoftwareSerial object is a const table of function pointers.  It keeps
 * familiar point syntax for the single active port, but it is not the C++
 * Arduino SoftwareSerial class and does not provide constructors or Stream.
 */
#ifndef STC_SOFTWARE_SERIAL_H
#define STC_SOFTWARE_SERIAL_H

#include <Arduino.h>

#ifdef __cplusplus
extern "C" {
#endif

#if defined(__SDCC)
# define STC_SOFTWARE_SERIAL_REENTRANT __reentrant
# define STC_SOFTWARE_SERIAL_CODE __code
#else
# define STC_SOFTWARE_SERIAL_REENTRANT
# define STC_SOFTWARE_SERIAL_CODE
#endif

#ifndef SOFTWARE_SERIAL_RX_BUFFER_SIZE
# define SOFTWARE_SERIAL_RX_BUFFER_SIZE 16u
#endif

#if (SOFTWARE_SERIAL_RX_BUFFER_SIZE < 2) || \
    (SOFTWARE_SERIAL_RX_BUFFER_SIZE > 255)
# error "SOFTWARE_SERIAL_RX_BUFFER_SIZE must be between 2 and 255 bytes"
#endif

/*
 * These conservative request limits keep each bit shorter than one Timer0
 * millisecond and leave time for portable C GPIO on slower targets.  A custom
 * value must be supplied as a build flag so it also reaches SoftwareSerial.c;
 * changing it in only the sketch translation unit has no effect.  Every
 * clock/board/rate combination still needs measurement on real hardware.
 */
#ifndef SOFTWARE_SERIAL_MIN_BIT_PERIOD_US
# define SOFTWARE_SERIAL_MIN_BIT_PERIOD_US 104u
#endif
#ifndef SOFTWARE_SERIAL_MAX_BIT_PERIOD_US
# define SOFTWARE_SERIAL_MAX_BIT_PERIOD_US 834u
#endif

bool SoftwareSerial_setPins(uint8_t receive_pin,
                            uint8_t transmit_pin) STC_SOFTWARE_SERIAL_REENTRANT;
bool SoftwareSerial_setInverseLogic(bool inverse_logic);
bool SoftwareSerial_begin(unsigned long baud);
void SoftwareSerial_end(void);
bool SoftwareSerial_listen(void);
bool SoftwareSerial_stopListening(void);
bool SoftwareSerial_isListening(void);

/* Poll once for a start bit and, when found, synchronously sample one frame. */
size_t SoftwareSerial_poll(void);
/* The accessors below only inspect buffered bytes and never call poll(). */
int SoftwareSerial_available(void);
int SoftwareSerial_availableForWrite(void);
int SoftwareSerial_peek(void);
int SoftwareSerial_read(void);
size_t SoftwareSerial_readBytes(void *buffer,
                                size_t length) STC_SOFTWARE_SERIAL_REENTRANT;
size_t SoftwareSerial_write(uint8_t value);
size_t SoftwareSerial_writeBuffer(const void *buffer,
                                  size_t length) STC_SOFTWARE_SERIAL_REENTRANT;
void SoftwareSerial_flush(void);

/* Sticky receive status; each query returns and clears its flag. */
bool SoftwareSerial_overflow(void);
bool SoftwareSerial_framingError(void);
bool SoftwareSerial_timingError(void);

size_t SoftwareSerial_print(const char *text);
size_t SoftwareSerial_println(const char *text);

typedef struct {
    bool (*setPins)(uint8_t receive_pin,
                    uint8_t transmit_pin) STC_SOFTWARE_SERIAL_REENTRANT;
    bool (*setInverseLogic)(bool inverse_logic);
    bool (*begin)(unsigned long baud);
    void (*end)(void);
    bool (*listen)(void);
    bool (*stopListening)(void);
    bool (*isListening)(void);
    size_t (*poll)(void);
    int (*available)(void);
    int (*availableForWrite)(void);
    int (*peek)(void);
    int (*read)(void);
    size_t (*readBytes)(void *buffer,
                        size_t length) STC_SOFTWARE_SERIAL_REENTRANT;
    size_t (*write)(uint8_t value);
    size_t (*writeBuffer)(const void *buffer,
                          size_t length) STC_SOFTWARE_SERIAL_REENTRANT;
    void (*flush)(void);
    bool (*overflow)(void);
    bool (*framingError)(void);
    bool (*timingError)(void);
    size_t (*print)(const char *text);
    size_t (*println)(const char *text);
} STCSoftwareSerialClass;

extern STC_SOFTWARE_SERIAL_CODE const STCSoftwareSerialClass SoftwareSerial;

#ifdef __cplusplus
}
#endif

#endif
