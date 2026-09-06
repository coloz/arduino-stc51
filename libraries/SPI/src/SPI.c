/*
 * SPDX-License-Identifier: MIT
 *
 * Software fallback for targets without a common hardware SPI peripheral.
 * Chip-select remains under sketch control, matching the Arduino SPI model.
 */
#include "SPI.h"

/*
 * The production backend manipulates the common 8051 IE register directly.
 * Native behavior tests replace only this register boundary; all transaction
 * bookkeeping below is the same code that runs on-device.
 */
#if defined(STC_SPI_HOST_INTERRUPT_HOOKS)
uint8_t stc_spi_host_interrupt_state_read(void);
void stc_spi_host_interrupt_state_write(uint8_t value);
# define SPI_INTERRUPT_STATE_READ() stc_spi_host_interrupt_state_read()
# define SPI_INTERRUPT_STATE_WRITE(value) \
    stc_spi_host_interrupt_state_write((uint8_t)(value))
#elif defined(__SDCC)
# include "stc_sfr.h"
# define SPI_INTERRUPT_STATE_READ() ((uint8_t)IE)
# define SPI_INTERRUPT_STATE_WRITE(value) (IE = (uint8_t)(value))
#else
/* Keep freestanding native syntax/link probes deterministic. */
static uint8_t spi_native_interrupt_state;
# define SPI_INTERRUPT_STATE_READ() (spi_native_interrupt_state)
# define SPI_INTERRUPT_STATE_WRITE(value) \
    (spi_native_interrupt_state = (uint8_t)(value))
#endif

#define SPI_INTERRUPT_EA_MASK  0x80u
#define SPI_INTERRUPT_EX1_MASK 0x04u
#define SPI_INTERRUPT_EX0_MASK 0x01u

static uint8_t spi_mosi_pin = SPI_DEFAULT_MOSI_PIN;
static uint8_t spi_miso_pin = SPI_DEFAULT_MISO_PIN;
static uint8_t spi_sck_pin = SPI_DEFAULT_SCK_PIN;
static uint8_t spi_ss_pin = SPI_DEFAULT_SS_PIN;
static uint8_t spi_bit_order = MSBFIRST;
static uint8_t spi_data_mode = SPI_MODE0;
static unsigned int spi_half_period_us;
static uint8_t spi_initialized;
static uint8_t spi_registered_interrupt_mask;
static uint8_t spi_global_interrupt_users;
static uint8_t spi_transaction_interrupt_mask;
static uint8_t spi_saved_interrupt_state;
static uint8_t spi_transaction_active;

static uint8_t spi_interrupt_mask_for_number(uint8_t interrupt_number)
{
    if (interrupt_number == 0u) {
        return SPI_INTERRUPT_EX0_MASK;
    }
    if (interrupt_number == 1u) {
        return SPI_INTERRUPT_EX1_MASK;
    }
    return 0u;
}

static uint8_t spi_lock_registration(void)
{
    uint8_t state = SPI_INTERRUPT_STATE_READ();

    SPI_INTERRUPT_STATE_WRITE(state & (uint8_t)~SPI_INTERRUPT_EA_MASK);
    return (uint8_t)(state & SPI_INTERRUPT_EA_MASK);
}

static void spi_unlock_registration(uint8_t saved_ea)
{
    uint8_t state = SPI_INTERRUPT_STATE_READ();

    SPI_INTERRUPT_STATE_WRITE(
        (state & (uint8_t)~SPI_INTERRUPT_EA_MASK) | saved_ea);
}

static void spi_begin_interrupt_guard(void)
{
    uint8_t state;

    if (spi_global_interrupt_users != 0u) {
        spi_transaction_interrupt_mask = SPI_INTERRUPT_EA_MASK;
    } else {
        spi_transaction_interrupt_mask = spi_registered_interrupt_mask;
    }

    state = SPI_INTERRUPT_STATE_READ();
    spi_saved_interrupt_state =
        (uint8_t)(state & spi_transaction_interrupt_mask);
    SPI_INTERRUPT_STATE_WRITE(
        state & (uint8_t)~spi_transaction_interrupt_mask);
    spi_transaction_active = 1u;
}

static void spi_end_interrupt_guard(void)
{
    uint8_t state;

    if (spi_transaction_active == 0u) {
        return;
    }

    state = SPI_INTERRUPT_STATE_READ();
    SPI_INTERRUPT_STATE_WRITE(
        (state & (uint8_t)~spi_transaction_interrupt_mask) |
        spi_saved_interrupt_state);
    spi_transaction_interrupt_mask = 0u;
    spi_saved_interrupt_state = 0u;
    spi_transaction_active = 0u;
}

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

static void spi_configure_pins(void)
{
    digitalWrite(spi_ss_pin, HIGH);
    pinMode(spi_ss_pin, OUTPUT);
    digitalWrite(spi_sck_pin, spi_idle_level());
    pinMode(spi_sck_pin, OUTPUT);
    digitalWrite(spi_mosi_pin, LOW);
    pinMode(spi_mosi_pin, OUTPUT);
    pinMode(spi_miso_pin, INPUT);
}

static void spi_release_pins(void)
{
    digitalWrite(spi_ss_pin, HIGH);
    pinMode(spi_mosi_pin, INPUT);
    pinMode(spi_miso_pin, INPUT);
    pinMode(spi_sck_pin, INPUT);
    pinMode(spi_ss_pin, INPUT);
}

void SPI_begin(void) STC_SPI_REENTRANT
{
    if (spi_initialized != 0u) {
        if (spi_initialized != 0xffu) {
            ++spi_initialized;
        }
        return;
    }

    if (spi_half_period_us == 0u) {
        spi_set_clock(SPI_DEFAULT_CLOCK_HZ);
    }

    spi_configure_pins();
    spi_initialized = 1u;
}

void SPI_setPins(uint8_t mosi_pin, uint8_t miso_pin, uint8_t sck_pin,
                 uint8_t ss_pin) STC_SPI_REENTRANT
{
    uint8_t restart = spi_initialized;

    if (restart != 0u) {
        spi_end_interrupt_guard();
        spi_release_pins();
    }
    spi_mosi_pin = mosi_pin;
    spi_miso_pin = miso_pin;
    spi_sck_pin = sck_pin;
    spi_ss_pin = ss_pin;
    if (restart != 0u) {
        spi_configure_pins();
    }
}

void SPI_beginTransaction(unsigned long clock_hz, uint8_t bit_order,
                          uint8_t data_mode) STC_SPI_REENTRANT
{
    if (spi_transaction_active == 0u) {
        spi_begin_interrupt_guard();
    }
    SPI_setSettings(clock_hz, bit_order, data_mode);
}

void SPI_setSettings(unsigned long clock_hz, uint8_t bit_order,
                     uint8_t data_mode) STC_SPI_REENTRANT
{
    spi_ensure_initialized();
    spi_set_clock(clock_hz);
    spi_bit_order = (bit_order == LSBFIRST) ? LSBFIRST : MSBFIRST;
    spi_data_mode = (uint8_t)(data_mode & 0x03u);
    digitalWrite(spi_sck_pin, spi_idle_level());
}

void SPI_usingInterrupt(uint8_t interrupt_number) STC_SPI_REENTRANT
{
    uint8_t interrupt_mask = spi_interrupt_mask_for_number(interrupt_number);
    uint8_t saved_ea = spi_lock_registration();

    if (interrupt_mask != 0u) {
        spi_registered_interrupt_mask |= interrupt_mask;
    } else if (spi_global_interrupt_users != 0xffu) {
        ++spi_global_interrupt_users;
    }
    spi_unlock_registration(saved_ea);
}

void SPI_notUsingInterrupt(uint8_t interrupt_number) STC_SPI_REENTRANT
{
    uint8_t interrupt_mask = spi_interrupt_mask_for_number(interrupt_number);
    uint8_t saved_ea = spi_lock_registration();

    if (interrupt_mask != 0u) {
        spi_registered_interrupt_mask &= (uint8_t)~interrupt_mask;
    } else if (spi_global_interrupt_users != 0u) {
        --spi_global_interrupt_users;
    }
    spi_unlock_registration(saved_ea);
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
    spi_end_interrupt_guard();
}

void SPI_end(void) STC_SPI_REENTRANT
{
    if (spi_initialized == 0u) {
        return;
    }
    if (spi_initialized > 1u) {
        --spi_initialized;
        return;
    }
    SPI_endTransaction();
    spi_release_pins();
    spi_initialized = 0u;
}

#if !defined(STCXX_CPP_CORE) || !STCXX_CPP_CORE
const STCSPIClass SPI = {
    SPI_begin,
    SPI_setPins,
    SPI_beginTransaction,
    SPI_transfer,
    SPI_transferBuffer,
    SPI_endTransaction,
    SPI_end,
    SPI_usingInterrupt,
    SPI_notUsingInterrupt,
    SPI_setSettings
};
#endif
