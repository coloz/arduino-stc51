/*
 * SPDX-License-Identifier: MIT
 *
 * Software fallback for targets without a common hardware I2C peripheral.
 * Timing is approximate because it uses the core delayMicroseconds() API.
 */
#include "Wire.h"

#define WIRE_INTERNAL_ACK      0u
#define WIRE_INTERNAL_NACK     1u
#define WIRE_INTERNAL_TIMEOUT  2u

static uint8_t wire_sda_pin = WIRE_DEFAULT_SDA_PIN;
static uint8_t wire_scl_pin = WIRE_DEFAULT_SCL_PIN;
static unsigned int wire_half_period_us;
static unsigned long wire_stretch_timeout_us =
    WIRE_DEFAULT_STRETCH_TIMEOUT_US;
static uint8_t wire_initialized;
static uint8_t wire_bus_held;

static uint8_t wire_tx_address;
static uint8_t wire_tx_buffer[WIRE_BUFFER_LENGTH];
static uint8_t wire_tx_length;
static uint8_t wire_tx_overflow;
static uint8_t wire_transmitting;

static uint8_t wire_rx_buffer[WIRE_BUFFER_LENGTH];
static uint8_t wire_rx_index;
static uint8_t wire_rx_length;

static void wire_delay_half_period(void)
{
    delayMicroseconds(wire_half_period_us);
}

static void wire_drive_sda_low(void)
{
    digitalWrite(wire_sda_pin, LOW);
}

static void wire_release_sda(void)
{
    digitalWrite(wire_sda_pin, HIGH);
}

static void wire_drive_scl_low(void)
{
    digitalWrite(wire_scl_pin, LOW);
}

static void wire_release_scl(void)
{
    digitalWrite(wire_scl_pin, HIGH);
}

static uint8_t wire_wait_for_scl_high(void)
{
    unsigned long started;

    wire_release_scl();
    started = micros();
    while (digitalRead(wire_scl_pin) == LOW) {
        if ((unsigned long)(micros() - started) >= wire_stretch_timeout_us) {
            return 0u;
        }
    }
    return 1u;
}

static void wire_release_bus(void)
{
    wire_release_sda();
    wire_release_scl();
    wire_bus_held = 0u;
}

static void wire_ensure_initialized(void)
{
    if (wire_initialized == 0u) {
        Wire_begin();
    }
}

static uint8_t wire_start_condition(void)
{
    wire_release_sda();
    wire_delay_half_period();

    if (wire_wait_for_scl_high() == 0u) {
        wire_release_bus();
        return WIRE_STATUS_TIMEOUT;
    }
    wire_delay_half_period();

    if (digitalRead(wire_sda_pin) == LOW) {
        wire_release_bus();
        return WIRE_STATUS_OTHER_ERROR;
    }

    wire_drive_sda_low();
    wire_delay_half_period();
    wire_drive_scl_low();
    wire_delay_half_period();
    wire_bus_held = 1u;
    return WIRE_STATUS_SUCCESS;
}

static uint8_t wire_stop_condition(void)
{
    uint8_t status = WIRE_STATUS_SUCCESS;

    wire_drive_sda_low();
    wire_delay_half_period();
    if (wire_wait_for_scl_high() == 0u) {
        status = WIRE_STATUS_TIMEOUT;
    } else {
        wire_delay_half_period();
    }
    wire_release_sda();
    wire_delay_half_period();
    wire_bus_held = 0u;
    return status;
}

static uint8_t wire_write_byte(uint8_t value)
{
    uint8_t mask;
    uint8_t acknowledged;

    for (mask = 0x80u; mask != 0u; mask >>= 1) {
        wire_drive_scl_low();
        if ((value & mask) != 0u) {
            wire_release_sda();
        } else {
            wire_drive_sda_low();
        }
        wire_delay_half_period();
        if (wire_wait_for_scl_high() == 0u) {
            wire_release_sda();
            return WIRE_INTERNAL_TIMEOUT;
        }
        wire_delay_half_period();
        wire_drive_scl_low();
    }

    wire_release_sda();
    wire_delay_half_period();
    if (wire_wait_for_scl_high() == 0u) {
        wire_drive_scl_low();
        return WIRE_INTERNAL_TIMEOUT;
    }
    wire_delay_half_period();
    acknowledged = (digitalRead(wire_sda_pin) == LOW) ? 1u : 0u;
    wire_drive_scl_low();
    wire_delay_half_period();

    return (acknowledged != 0u) ? WIRE_INTERNAL_ACK : WIRE_INTERNAL_NACK;
}

static uint8_t wire_read_byte(uint8_t send_ack, uint8_t *value)
{
    uint8_t mask;
    uint8_t result = 0u;

    wire_release_sda();
    for (mask = 0x80u; mask != 0u; mask >>= 1) {
        wire_drive_scl_low();
        wire_delay_half_period();
        if (wire_wait_for_scl_high() == 0u) {
            wire_drive_scl_low();
            return 0u;
        }
        wire_delay_half_period();
        if (digitalRead(wire_sda_pin) != LOW) {
            result |= mask;
        }
        wire_drive_scl_low();
    }

    if (send_ack != 0u) {
        wire_drive_sda_low();
    } else {
        wire_release_sda();
    }
    wire_delay_half_period();
    if (wire_wait_for_scl_high() == 0u) {
        wire_drive_scl_low();
        wire_release_sda();
        return 0u;
    }
    wire_delay_half_period();
    wire_drive_scl_low();
    wire_release_sda();
    wire_delay_half_period();

    *value = result;
    return 1u;
}

void Wire_begin(void) STC_WIRE_REENTRANT
{
    if (wire_half_period_us == 0u) {
        Wire_setClock(WIRE_DEFAULT_CLOCK_HZ);
    }
    pinMode(wire_sda_pin, OUTPUT_OPEN_DRAIN);
    pinMode(wire_scl_pin, OUTPUT_OPEN_DRAIN);
    wire_release_bus();
    wire_tx_length = 0u;
    wire_tx_overflow = 0u;
    wire_transmitting = 0u;
    wire_rx_index = 0u;
    wire_rx_length = 0u;
    wire_initialized = 1u;
}

void Wire_setPins(uint8_t sda_pin, uint8_t scl_pin) STC_WIRE_REENTRANT
{
    uint8_t restart = wire_initialized;

    if (restart != 0u) {
        wire_release_bus();
        pinMode(wire_sda_pin, INPUT);
        pinMode(wire_scl_pin, INPUT);
    }
    wire_sda_pin = sda_pin;
    wire_scl_pin = scl_pin;
    if (restart != 0u) {
        Wire_begin();
    }
}

void Wire_setClock(unsigned long clock_hz) STC_WIRE_REENTRANT
{
    unsigned long half_period;

    if (clock_hz == 0UL) {
        return;
    }
    if (clock_hz >= 500000UL) {
        half_period = 1UL;
    } else {
        half_period = (500000UL + clock_hz - 1UL) / clock_hz;
    }
    if (half_period > 65535UL) {
        half_period = 65535UL;
    }
    wire_half_period_us = (unsigned int)half_period;
}

void Wire_setClockStretchTimeout(unsigned long timeout_us) STC_WIRE_REENTRANT
{
    wire_stretch_timeout_us = (timeout_us == 0UL) ? 1UL : timeout_us;
}

void Wire_beginTransmission(uint8_t address) STC_WIRE_REENTRANT
{
    wire_tx_address = (uint8_t)(address & 0x7fu);
    wire_tx_length = 0u;
    wire_tx_overflow = 0u;
    wire_transmitting = 1u;
}

size_t Wire_write(uint8_t value) STC_WIRE_REENTRANT
{
    if (wire_transmitting == 0u) {
        return 0u;
    }
    if (wire_tx_length >= WIRE_BUFFER_LENGTH) {
        wire_tx_overflow = 1u;
        return 0u;
    }
    wire_tx_buffer[wire_tx_length++] = value;
    return 1u;
}

uint8_t Wire_endTransmissionStop(uint8_t send_stop) STC_WIRE_REENTRANT
{
    uint8_t index;
    uint8_t byte_status;
    uint8_t status;

    if (wire_transmitting == 0u) {
        return WIRE_STATUS_OTHER_ERROR;
    }
    wire_transmitting = 0u;
    wire_ensure_initialized();

    if (wire_tx_overflow != 0u) {
        wire_tx_length = 0u;
        if (wire_bus_held != 0u) {
            (void)wire_stop_condition();
        }
        return WIRE_STATUS_DATA_TOO_LONG;
    }

    status = wire_start_condition();
    if (status != WIRE_STATUS_SUCCESS) {
        wire_tx_length = 0u;
        return status;
    }

    byte_status = wire_write_byte((uint8_t)(wire_tx_address << 1));
    if (byte_status != WIRE_INTERNAL_ACK) {
        status = (byte_status == WIRE_INTERNAL_TIMEOUT) ?
            WIRE_STATUS_TIMEOUT : WIRE_STATUS_ADDRESS_NACK;
        (void)wire_stop_condition();
        wire_tx_length = 0u;
        return status;
    }

    for (index = 0u; index < wire_tx_length; ++index) {
        byte_status = wire_write_byte(wire_tx_buffer[index]);
        if (byte_status != WIRE_INTERNAL_ACK) {
            status = (byte_status == WIRE_INTERNAL_TIMEOUT) ?
                WIRE_STATUS_TIMEOUT : WIRE_STATUS_DATA_NACK;
            (void)wire_stop_condition();
            wire_tx_length = 0u;
            return status;
        }
    }
    wire_tx_length = 0u;

    if (send_stop != 0u) {
        status = wire_stop_condition();
    } else {
        wire_release_sda();
        wire_bus_held = 1u;
        status = WIRE_STATUS_SUCCESS;
    }
    return status;
}

uint8_t Wire_endTransmission(void) STC_WIRE_REENTRANT
{
    return Wire_endTransmissionStop(1u);
}

uint8_t Wire_requestFromStop(uint8_t address, uint8_t quantity,
                             uint8_t send_stop) STC_WIRE_REENTRANT
{
    uint8_t byte_status;
    uint8_t index;
    uint8_t value;

    wire_ensure_initialized();
    wire_rx_index = 0u;
    wire_rx_length = 0u;
    if (quantity == 0u) {
        return 0u;
    }
    if (quantity > WIRE_BUFFER_LENGTH) {
        quantity = WIRE_BUFFER_LENGTH;
    }

    if (wire_start_condition() != WIRE_STATUS_SUCCESS) {
        return 0u;
    }
    byte_status = wire_write_byte((uint8_t)(((address & 0x7fu) << 1) | 1u));
    if (byte_status != WIRE_INTERNAL_ACK) {
        (void)wire_stop_condition();
        return 0u;
    }

    for (index = 0u; index < quantity; ++index) {
        if (wire_read_byte((index + 1u < quantity) ? 1u : 0u, &value) == 0u) {
            (void)wire_stop_condition();
            return wire_rx_length;
        }
        wire_rx_buffer[wire_rx_length++] = value;
    }

    if (send_stop != 0u) {
        (void)wire_stop_condition();
    } else {
        wire_release_sda();
        wire_bus_held = 1u;
    }
    return wire_rx_length;
}

uint8_t Wire_requestFrom(uint8_t address, uint8_t quantity) STC_WIRE_REENTRANT
{
    return Wire_requestFromStop(address, quantity, 1u);
}

int Wire_available(void) STC_WIRE_REENTRANT
{
    return (int)(wire_rx_length - wire_rx_index);
}

int Wire_peek(void) STC_WIRE_REENTRANT
{
    if (wire_rx_index >= wire_rx_length) {
        return -1;
    }
    return (int)wire_rx_buffer[wire_rx_index];
}

int Wire_read(void) STC_WIRE_REENTRANT
{
    if (wire_rx_index >= wire_rx_length) {
        return -1;
    }
    return (int)wire_rx_buffer[wire_rx_index++];
}

const STCWireClass Wire = {
    Wire_begin,
    Wire_setPins,
    Wire_setClock,
    Wire_setClockStretchTimeout,
    Wire_beginTransmission,
    Wire_write,
    Wire_endTransmission,
    Wire_requestFrom,
    Wire_available,
    Wire_peek,
    Wire_read,
    Wire_endTransmissionStop,
    Wire_requestFromStop
};
