/*
 * SPDX-License-Identifier: MIT
 *
 * Software fallback for targets without a common hardware SPI peripheral.
 * Chip-select remains under sketch control, matching the Arduino SPI model.
 */
#include "SPI.h"

static uint8_t spi_mosi_pin = SPI_DEFAULT_MOSI_PIN;
static uint8_t spi_miso_pin = SPI_DEFAULT_MISO_PIN;
static uint8_t spi_sck_pin = SPI_DEFAULT_SCK_PIN;
static uint8_t spi_ss_pin = SPI_DEFAULT_SS_PIN;
static uint8_t spi_bit_order = MSBFIRST;
static uint8_t spi_data_mode = SPI_MODE0;
static unsigned int spi_half_period_us;
static uint8_t spi_initialized;

static uint8_t spi_idle_level(void)
{
    return ((spi_data_mode & 0x02u) != 0u) ? HIGH : LOW;
}

static uint8_t spi_active_level(void)
{
    return (spi_idle_level() == LOW) ? HIGH : LOW;
}

static void spi_delay_half_period(void)
{
    delayMicroseconds(spi_half_period_us);
}

static void spi_set_clock(unsigned long clock_hz)
{
    unsigned long half_period;

    if (clock_hz == 0UL) {
        clock_hz = SPI_DEFAULT_CLOCK_HZ;
    }
    if (clock_hz >= 500000UL) {
        half_period = 1UL;
    } else {
        half_period = (500000UL + clock_hz - 1UL) / clock_hz;
    }
    if (half_period > 65535UL) {
        half_period = 65535UL;
    }
    spi_half_period_us = (unsigned int)half_period;
}

static void spi_ensure_initialized(void)
{
    if (spi_initialized == 0u) {
        SPI_begin();
    }
}

void SPI_begin(void) STC_SPI_REENTRANT
{
    if (spi_half_period_us == 0u) {
        spi_set_clock(SPI_DEFAULT_CLOCK_HZ);
    }

    digitalWrite(spi_ss_pin, HIGH);
    pinMode(spi_ss_pin, OUTPUT);
    digitalWrite(spi_sck_pin, spi_idle_level());
    pinMode(spi_sck_pin, OUTPUT);
    digitalWrite(spi_mosi_pin, LOW);
    pinMode(spi_mosi_pin, OUTPUT);
    pinMode(spi_miso_pin, INPUT);

    spi_initialized = 1u;
}

void SPI_setPins(uint8_t mosi_pin, uint8_t miso_pin, uint8_t sck_pin,
                 uint8_t ss_pin) STC_SPI_REENTRANT
{
    uint8_t restart = spi_initialized;

    if (restart != 0u) {
        SPI_end();
    }
    spi_mosi_pin = mosi_pin;
    spi_miso_pin = miso_pin;
    spi_sck_pin = sck_pin;
    spi_ss_pin = ss_pin;
    if (restart != 0u) {
        SPI_begin();
    }
}

void SPI_beginTransaction(unsigned long clock_hz, uint8_t bit_order,
                          uint8_t data_mode) STC_SPI_REENTRANT
{
    spi_ensure_initialized();
    spi_set_clock(clock_hz);
    spi_bit_order = (bit_order == LSBFIRST) ? LSBFIRST : MSBFIRST;
    spi_data_mode = (uint8_t)(data_mode & 0x03u);
    digitalWrite(spi_sck_pin, spi_idle_level());
}

uint8_t SPI_transfer(uint8_t value) STC_SPI_REENTRANT
{
    uint8_t mask;
    uint8_t received = 0u;
    uint8_t idle;
    uint8_t active;
    uint8_t phase;

    spi_ensure_initialized();
    idle = spi_idle_level();
    active = spi_active_level();
    phase = (uint8_t)(spi_data_mode & 0x01u);
    mask = (spi_bit_order == LSBFIRST) ? 0x01u : 0x80u;

    while (mask != 0u) {
        if (phase == 0u) {
            digitalWrite(spi_mosi_pin, ((value & mask) != 0u) ? HIGH : LOW);
            spi_delay_half_period();
            digitalWrite(spi_sck_pin, active);
            if (digitalRead(spi_miso_pin) != LOW) {
                received |= mask;
            }
            spi_delay_half_period();
            digitalWrite(spi_sck_pin, idle);
        } else {
            digitalWrite(spi_sck_pin, active);
            digitalWrite(spi_mosi_pin, ((value & mask) != 0u) ? HIGH : LOW);
            spi_delay_half_period();
            digitalWrite(spi_sck_pin, idle);
            if (digitalRead(spi_miso_pin) != LOW) {
                received |= mask;
            }
            spi_delay_half_period();
        }

        if (spi_bit_order == LSBFIRST) {
            mask <<= 1;
        } else {
            mask >>= 1;
        }
    }

    digitalWrite(spi_sck_pin, idle);
    return received;
}

void SPI_transferBuffer(uint8_t *buffer, size_t length) STC_SPI_REENTRANT
{
    size_t index;

    if (buffer == NULL) {
        return;
    }
    for (index = 0u; index < length; ++index) {
        buffer[index] = SPI_transfer(buffer[index]);
    }
}

void SPI_endTransaction(void) STC_SPI_REENTRANT
{
    if (spi_initialized != 0u) {
        digitalWrite(spi_sck_pin, spi_idle_level());
    }
}

void SPI_end(void) STC_SPI_REENTRANT
{
    if (spi_initialized == 0u) {
        return;
    }
    SPI_endTransaction();
    digitalWrite(spi_ss_pin, HIGH);
    pinMode(spi_mosi_pin, INPUT);
    pinMode(spi_miso_pin, INPUT);
    pinMode(spi_sck_pin, INPUT);
    pinMode(spi_ss_pin, INPUT);
    spi_initialized = 0u;
}

const STCSPIClass SPI = {
    SPI_begin,
    SPI_setPins,
    SPI_beginTransaction,
    SPI_transfer,
    SPI_transferBuffer,
    SPI_endTransaction,
    SPI_end
};
