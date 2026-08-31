/*
 * SPDX-License-Identifier: MIT
 *
 * Small-memory, plain-C SD card support for the arduino-stc51 core.
 *
 * This API deliberately does not expose Arduino's C++ File/Stream classes.
 * It owns one card and one open root-directory file at a time.
 */
#ifndef STC_SD_H
#define STC_SD_H

#include <Arduino.h>
#include <SPI.h>

#ifdef __cplusplus
extern "C" {
#endif

#if !defined(STC_XDATA_BYTES) || (STC_XDATA_BYTES < 1024UL)
# error "The STC SD library requires at least 1024 bytes of XDATA"
#endif

#if defined(__SDCC)
# define STC_SD_REENTRANT __reentrant
# define STC_SD_CODE __code
#else
# define STC_SD_REENTRANT
# define STC_SD_CODE
#endif

#ifndef FILE_READ
# define FILE_READ 0x01u
#endif
#ifndef FILE_WRITE
# define FILE_WRITE 0x17u
#endif

#ifndef SD_DEFAULT_MOSI_PIN
# define SD_DEFAULT_MOSI_PIN SPI_DEFAULT_MOSI_PIN
#endif
#ifndef SD_DEFAULT_MISO_PIN
# define SD_DEFAULT_MISO_PIN SPI_DEFAULT_MISO_PIN
#endif
#ifndef SD_DEFAULT_SCK_PIN
# define SD_DEFAULT_SCK_PIN SPI_DEFAULT_SCK_PIN
#endif
#ifndef SD_DEFAULT_CS_PIN
# define SD_DEFAULT_CS_PIN SPI_DEFAULT_SS_PIN
#endif

#define SD_CARD_NONE 0u
#define SD_CARD_SD1  1u
#define SD_CARD_SD2  2u
#define SD_CARD_SDHC 3u

#define SD_FAT_NONE 0u
#define SD_FAT16    16u
#define SD_FAT32    32u

/* Sticky result from the most recent operation. */
#define SD_ERROR_NONE               0u
#define SD_ERROR_INVALID_PIN        1u
#define SD_ERROR_PIN_CONFLICT       2u
#define SD_ERROR_CARD_TIMEOUT       3u
#define SD_ERROR_CARD_RESPONSE      4u
#define SD_ERROR_CARD_UNSUPPORTED   5u
#define SD_ERROR_ADDRESS_OVERFLOW   6u
#define SD_ERROR_READ_TOKEN         7u
#define SD_ERROR_WRITE_REJECTED     8u
#define SD_ERROR_WRITE_STATUS       9u
#define SD_ERROR_INVALID_ARGUMENT  10u
#define SD_ERROR_NOT_INITIALIZED   11u
#define SD_ERROR_BAD_VOLUME        12u
#define SD_ERROR_FAT12_UNSUPPORTED 13u
#define SD_ERROR_NOT_FOUND         14u
#define SD_ERROR_NOT_A_FILE        15u
#define SD_ERROR_READ_ONLY         16u
#define SD_ERROR_BAD_CLUSTER       17u

/*
 * Select all four software-SPI pins. A failed call preserves the current
 * configuration. No two logical names may resolve to the same package pad.
 */
uint8_t SD_setPins(uint8_t mosi_pin, uint8_t miso_pin, uint8_t sck_pin,
                   uint8_t cs_pin) STC_SD_REENTRANT;

/* begin() retains the configured MOSI/MISO/SCK pins and selects cs_pin. */
uint8_t SD_begin(uint8_t cs_pin) STC_SD_REENTRANT;

/* Uses the current pin tuple, which initially contains the SPI defaults. */
uint8_t SD_beginDefault(void) STC_SD_REENTRANT;
void SD_end(void) STC_SD_REENTRANT;

uint8_t SD_cardType(void) STC_SD_REENTRANT;
uint8_t SD_fatType(void) STC_SD_REENTRANT;
uint8_t SD_error(void) STC_SD_REENTRANT;

/* Raw 512-byte sectors. writeBlock() can corrupt a mounted filesystem. */
uint8_t SD_readBlock(unsigned long sector, uint8_t *buffer)
                     STC_SD_REENTRANT;
uint8_t SD_writeBlock(unsigned long sector, const uint8_t *buffer)
                      STC_SD_REENTRANT;

/* Root directory only; ASCII short 8.3 names, optionally prefixed by '/'. */
uint8_t SD_exists(const char *name) STC_SD_REENTRANT;
uint8_t SD_open(const char *name, uint8_t mode) STC_SD_REENTRANT;
int SD_read(void) STC_SD_REENTRANT;
size_t SD_readBytes(uint8_t *buffer, size_t length) STC_SD_REENTRANT;
int SD_peek(void) STC_SD_REENTRANT;
unsigned long SD_available(void) STC_SD_REENTRANT;
uint8_t SD_seek(unsigned long position) STC_SD_REENTRANT;
unsigned long SD_position(void) STC_SD_REENTRANT;
unsigned long SD_size(void) STC_SD_REENTRANT;
void SD_close(void) STC_SD_REENTRANT;

typedef struct {
    uint8_t (*setPins)(uint8_t mosi_pin, uint8_t miso_pin,
                       uint8_t sck_pin, uint8_t cs_pin)
                       STC_SD_REENTRANT;
    uint8_t (*begin)(uint8_t cs_pin) STC_SD_REENTRANT;
    uint8_t (*beginDefault)(void) STC_SD_REENTRANT;
    void (*end)(void) STC_SD_REENTRANT;
    uint8_t (*cardType)(void) STC_SD_REENTRANT;
    uint8_t (*fatType)(void) STC_SD_REENTRANT;
    uint8_t (*error)(void) STC_SD_REENTRANT;
    uint8_t (*readBlock)(unsigned long sector, uint8_t *buffer)
                         STC_SD_REENTRANT;
    uint8_t (*writeBlock)(unsigned long sector, const uint8_t *buffer)
                          STC_SD_REENTRANT;
    uint8_t (*exists)(const char *name) STC_SD_REENTRANT;
    uint8_t (*open)(const char *name, uint8_t mode) STC_SD_REENTRANT;
    int (*read)(void) STC_SD_REENTRANT;
    size_t (*readBytes)(uint8_t *buffer, size_t length)
                        STC_SD_REENTRANT;
    int (*peek)(void) STC_SD_REENTRANT;
    unsigned long (*available)(void) STC_SD_REENTRANT;
    uint8_t (*seek)(unsigned long position) STC_SD_REENTRANT;
    unsigned long (*position)(void) STC_SD_REENTRANT;
    unsigned long (*size)(void) STC_SD_REENTRANT;
    void (*close)(void) STC_SD_REENTRANT;
} STCSDClass;

extern STC_SD_CODE const STCSDClass SD;

#ifdef __cplusplus
}
#endif

#endif
