#ifndef STC_CORE_HARDWARE_SERIAL_H
#define STC_CORE_HARDWARE_SERIAL_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#ifndef STC_CORE_SERIAL_BUFFERED_RX
# define STC_CORE_SERIAL_BUFFERED_RX 1
#endif

/*
 * UART1 uses Timer1 while Serial is active and transmit is synchronous.
 * Normal profiles use interrupt-driven buffered receive; the 2 KiB compact
 * profile uses a one-byte polling cache. Serial_readBytes() drains only bytes
 * already available and does not wait for future input.
 */
void Serial_begin(unsigned long baud);
void Serial_end(void);
int Serial_available(void);
int Serial_availableForWrite(void);
int Serial_peek(void);
int Serial_read(void);
size_t Serial_readBytes(void *buffer, size_t length) __reentrant;
size_t Serial_write(uint8_t value);
void Serial_flush(void);

/* Returns the sticky RX-overflow state and clears it. */
bool Serial_overflow(void);

size_t Serial_print(const char *text);
size_t Serial_println(const char *text);
size_t Serial_printNumber(long value, uint8_t base) __reentrant;
size_t Serial_printlnNumber(long value, uint8_t base) __reentrant;

/*
 * Arduino-like object syntax for this plain-C core, for example:
 *
 *     Serial.begin(9600UL);
 *     Serial.println("hello");
 *
 * The object lives in code space so its function-pointer table consumes no
 * scarce 8051 data RAM.
 */
typedef struct {
    void (*begin)(unsigned long baud);
    void (*end)(void);
    int (*available)(void);
    int (*availableForWrite)(void);
    int (*peek)(void);
    int (*read)(void);
    size_t (*readBytes)(void *buffer, size_t length) __reentrant;
    size_t (*write)(uint8_t value);
    void (*flush)(void);
    bool (*overflow)(void);
    size_t (*print)(const char *text);
    size_t (*println)(const char *text);
#if STC_CORE_SERIAL_BUFFERED_RX
    size_t (*printNumber)(long value, uint8_t base) __reentrant;
    size_t (*printlnNumber)(long value, uint8_t base) __reentrant;
#endif
} HardwareSerialClass;

extern __code const HardwareSerialClass Serial;

/* Compatibility with the existing plain-C core API. */
#define HardwareSerial_begin             Serial_begin
#define HardwareSerial_end               Serial_end
#define HardwareSerial_available         Serial_available
#define HardwareSerial_availableForWrite Serial_availableForWrite
#define HardwareSerial_peek              Serial_peek
#define HardwareSerial_read              Serial_read
#define HardwareSerial_readBytes         Serial_readBytes
#define HardwareSerial_write             Serial_write
#define HardwareSerial_flush             Serial_flush
#define HardwareSerial_overflow          Serial_overflow
#define HardwareSerial_print             Serial_print
#define HardwareSerial_println           Serial_println
#define HardwareSerial_printNumber       Serial_printNumber
#define HardwareSerial_printlnNumber     Serial_printlnNumber

#endif
