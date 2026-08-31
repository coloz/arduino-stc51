/*
 * SPDX-License-Identifier: MIT
 *
 * Blocking, software-timed stepper motor control for the STC plain-C core.
 */
#include "Stepper.h"

#define STEPPER_MICROSECONDS_PER_MINUTE 60000000UL
#define STEPPER_MAX_STEPS_PER_REVOLUTION 65535UL
#define STEPPER_WAIT_CHUNK_US 60000u

static uint8_t stepper_pins[STEPPER_PIN_COUNT_5];
static uint8_t stepper_pin_count;
static uint8_t stepper_phase;
static unsigned int stepper_steps_per_revolution;
static unsigned long stepper_step_delay_us;
static unsigned long stepper_last_step_time;

static uint8_t stepper_pins_conflict(uint8_t left, uint8_t right)
{
    if (left == right) {
        return 1u;
    }
    return (digitalPinsSharePhysicalPad(left, right) != 0) ? 1u : 0u;
}

static uint8_t stepper_validate_configuration(
    unsigned long steps_per_revolution, uint8_t pin_count,
    uint8_t pin1, uint8_t pin2, uint8_t pin3, uint8_t pin4, uint8_t pin5)
    STC_STEPPER_REENTRANT
{
    if ((steps_per_revolution == 0UL) ||
        (steps_per_revolution > STEPPER_MAX_STEPS_PER_REVOLUTION)) {
        return STEPPER_STATUS_INVALID_STEPS;
    }

    if ((digitalPinIsValid(pin1) == 0u) ||
        (digitalPinIsValid(pin2) == 0u) ||
        ((pin_count >= STEPPER_PIN_COUNT_4) &&
         ((digitalPinIsValid(pin3) == 0u) ||
          (digitalPinIsValid(pin4) == 0u))) ||
        ((pin_count == STEPPER_PIN_COUNT_5) &&
         (digitalPinIsValid(pin5) == 0u))) {
        return STEPPER_STATUS_INVALID_PIN;
    }

    if (stepper_pins_conflict(pin1, pin2) != 0u) {
        return STEPPER_STATUS_PIN_CONFLICT;
    }
    if (pin_count >= STEPPER_PIN_COUNT_4) {
        if ((stepper_pins_conflict(pin1, pin3) != 0u) ||
            (stepper_pins_conflict(pin1, pin4) != 0u) ||
            (stepper_pins_conflict(pin2, pin3) != 0u) ||
            (stepper_pins_conflict(pin2, pin4) != 0u) ||
            (stepper_pins_conflict(pin3, pin4) != 0u)) {
            return STEPPER_STATUS_PIN_CONFLICT;
        }
    }
    if (pin_count == STEPPER_PIN_COUNT_5) {
        if ((stepper_pins_conflict(pin1, pin5) != 0u) ||
            (stepper_pins_conflict(pin2, pin5) != 0u) ||
            (stepper_pins_conflict(pin3, pin5) != 0u) ||
            (stepper_pins_conflict(pin4, pin5) != 0u)) {
            return STEPPER_STATUS_PIN_CONFLICT;
        }
    }

    return STEPPER_STATUS_SUCCESS;
}

static void stepper_detach_current_pins(void)
{
    uint8_t index;

    if (stepper_pin_count == STEPPER_PIN_COUNT_NONE) {
        return;
    }
    Stepper_release();
    for (index = 0u; index < stepper_pin_count; ++index) {
        pinMode(stepper_pins[index], INPUT);
    }
}

static uint8_t stepper_configure(
    unsigned long steps_per_revolution, uint8_t pin_count,
    uint8_t pin1, uint8_t pin2, uint8_t pin3, uint8_t pin4, uint8_t pin5)
    STC_STEPPER_REENTRANT
{
    uint8_t index;
    uint8_t status;

    status = stepper_validate_configuration(steps_per_revolution, pin_count,
                                             pin1, pin2, pin3, pin4, pin5);
    if (status != STEPPER_STATUS_SUCCESS) {
        return status;
    }

    stepper_detach_current_pins();

    stepper_pins[0] = pin1;
    stepper_pins[1] = pin2;
    stepper_pins[2] = pin3;
    stepper_pins[3] = pin4;
    stepper_pins[4] = pin5;
    stepper_pin_count = pin_count;
    stepper_phase = 0u;
    stepper_steps_per_revolution = (unsigned int)steps_per_revolution;

    /* Motion stays disabled until the sketch explicitly selects a speed. */
    stepper_step_delay_us = 0UL;

    for (index = 0u; index < stepper_pin_count; ++index) {
        /* Preload LOW through the released/open-drain state before enabling
         * push-pull output, so a reset-high latch cannot create a drive pulse. */
        pinMode(stepper_pins[index], OUTPUT_OPEN_DRAIN);
        digitalWrite(stepper_pins[index], LOW);
        pinMode(stepper_pins[index], OUTPUT);
    }
    stepper_last_step_time = micros();
    return STEPPER_STATUS_SUCCESS;
}

static uint8_t stepper_phase_count(void)
{
    return (stepper_pin_count == STEPPER_PIN_COUNT_5) ? 10u : 4u;
}

static uint8_t stepper_phase_mask(uint8_t phase)
{
    if (stepper_pin_count == STEPPER_PIN_COUNT_2) {
        switch (phase) {
        case 0u: return 0x02u;
        case 1u: return 0x03u;
        case 2u: return 0x01u;
        default: return 0x00u;
        }
    }

    if (stepper_pin_count == STEPPER_PIN_COUNT_4) {
        switch (phase) {
        case 0u: return 0x05u;
        case 1u: return 0x06u;
        case 2u: return 0x0au;
        default: return 0x09u;
        }
    }

    /* Ten half-phases for a five-phase motor, packed one bit per output. */
    switch (phase) {
    case 0u: return 0x16u;
    case 1u: return 0x12u;
    case 2u: return 0x1au;
    case 3u: return 0x0au;
    case 4u: return 0x0bu;
    case 5u: return 0x09u;
    case 6u: return 0x0du;
    case 7u: return 0x05u;
    case 8u: return 0x15u;
    default: return 0x14u;
    }
}

static void stepper_write_phase(uint8_t phase)
{
    uint8_t index;
    uint8_t mask = stepper_phase_mask(phase);

    for (index = 0u; index < stepper_pin_count; ++index) {
        digitalWrite(stepper_pins[index],
                     ((mask & (uint8_t)(1u << index)) != 0u) ? HIGH : LOW);
    }
}

static void stepper_wait_for_next_step(void)
{
    unsigned long now;
    unsigned long elapsed;
    unsigned long remaining;
    unsigned int chunk;

    for (;;) {
        now = micros();
        elapsed = (unsigned long)(now - stepper_last_step_time);
        if (elapsed >= stepper_step_delay_us) {
            break;
        }

        remaining = stepper_step_delay_us - elapsed;
        chunk = (remaining > (unsigned long)STEPPER_WAIT_CHUNK_US) ?
            STEPPER_WAIT_CHUNK_US : (unsigned int)remaining;
        delayMicroseconds(chunk);
        yield();
    }
    stepper_last_step_time = now;
}

uint8_t Stepper_setPins2(unsigned long steps_per_revolution,
                         uint8_t pin1, uint8_t pin2)
                         STC_STEPPER_REENTRANT
{
    return stepper_configure(steps_per_revolution, STEPPER_PIN_COUNT_2,
                             pin1, pin2, NOT_A_PIN, NOT_A_PIN, NOT_A_PIN);
}

uint8_t Stepper_setPins4(unsigned long steps_per_revolution,
                         uint8_t pin1, uint8_t pin2, uint8_t pin3,
                         uint8_t pin4) STC_STEPPER_REENTRANT
{
    return stepper_configure(steps_per_revolution, STEPPER_PIN_COUNT_4,
                             pin1, pin2, pin3, pin4, NOT_A_PIN);
}

uint8_t Stepper_setPins5(unsigned long steps_per_revolution,
                         uint8_t pin1, uint8_t pin2, uint8_t pin3,
                         uint8_t pin4, uint8_t pin5)
                         STC_STEPPER_REENTRANT
{
    return stepper_configure(steps_per_revolution, STEPPER_PIN_COUNT_5,
                             pin1, pin2, pin3, pin4, pin5);
}

uint8_t Stepper_setSpeed(long rpm) STC_STEPPER_REENTRANT
{
    unsigned long delay_us;

    if (rpm <= 0L) {
        stepper_step_delay_us = 0UL;
        return STEPPER_STATUS_INVALID_SPEED;
    }
    if (stepper_pin_count == STEPPER_PIN_COUNT_NONE) {
        return STEPPER_STATUS_NOT_CONFIGURED;
    }

    /* Divide in two stages so steps * rpm can never overflow. */
    delay_us = STEPPER_MICROSECONDS_PER_MINUTE /
        (unsigned long)stepper_steps_per_revolution;
    delay_us /= (unsigned long)rpm;
    stepper_step_delay_us = (delay_us == 0UL) ? 1UL : delay_us;
    stepper_last_step_time = micros();
    return STEPPER_STATUS_SUCCESS;
}

void Stepper_step(long steps_to_move) STC_STEPPER_REENTRANT
{
    unsigned long remaining_steps;
    uint8_t phase_count;
    uint8_t reverse;

    if ((stepper_pin_count == STEPPER_PIN_COUNT_NONE) ||
        (stepper_step_delay_us == 0UL) ||
        (steps_to_move == 0L)) {
        return;
    }

    if (steps_to_move < 0L) {
        /* This form is defined even for the most-negative signed long. */
        remaining_steps = (unsigned long)(-(steps_to_move + 1L)) + 1UL;
        reverse = 1u;
    } else {
        remaining_steps = (unsigned long)steps_to_move;
        reverse = 0u;
    }
    phase_count = stepper_phase_count();

    while (remaining_steps != 0UL) {
        stepper_wait_for_next_step();
        if (reverse == 0u) {
            ++stepper_phase;
            if (stepper_phase >= phase_count) {
                stepper_phase = 0u;
            }
        } else if (stepper_phase == 0u) {
            stepper_phase = (uint8_t)(phase_count - 1u);
        } else {
            --stepper_phase;
        }

        stepper_write_phase(stepper_phase);
        --remaining_steps;
        yield();
    }
}

void Stepper_release(void) STC_STEPPER_REENTRANT
{
    uint8_t index;

    for (index = 0u; index < stepper_pin_count; ++index) {
        digitalWrite(stepper_pins[index], LOW);
    }
}

unsigned long Stepper_stepsPerRevolution(void) STC_STEPPER_REENTRANT
{
    return (unsigned long)stepper_steps_per_revolution;
}

uint8_t Stepper_pinCount(void) STC_STEPPER_REENTRANT
{
    return stepper_pin_count;
}

uint8_t Stepper_isConfigured(void) STC_STEPPER_REENTRANT
{
    return (stepper_pin_count == STEPPER_PIN_COUNT_NONE) ? 0u : 1u;
}

STC_STEPPER_CODE const STCStepperClass Stepper = {
    Stepper_setPins2,
    Stepper_setPins4,
    Stepper_setPins5,
    Stepper_setSpeed,
    Stepper_step,
    Stepper_release,
    Stepper_stepsPerRevolution,
    Stepper_pinCount,
    Stepper_isConfigured
};
