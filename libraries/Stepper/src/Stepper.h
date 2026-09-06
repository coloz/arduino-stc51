/*
 * SPDX-License-Identifier: MIT
 *
 * Plain-C Arduino-style stepper motor control.
 *
 * Plain-C builds expose a const function table named Stepper.  The C++ Arduino
 * Core profile exposes the conventional constructor-based Stepper class.
 * The C facade has a default motor; each C++ object owns its motor context.
 */
#ifndef STC_STEPPER_H
#define STC_STEPPER_H

#include <Arduino.h>

typedef struct {
    uint8_t pins[5];
    uint8_t pin_count, phase;
    unsigned int steps_per_revolution;
    unsigned long step_delay_us, last_step_time;
} STCStepperState;

#ifdef __cplusplus
extern "C" {
#endif

/* SDCC indirect calls cannot use callee-specific overlay parameter slots. */
#if defined(__SDCC)
# define STC_STEPPER_REENTRANT __reentrant
# define STC_STEPPER_CODE __code
#else
# define STC_STEPPER_REENTRANT
# define STC_STEPPER_CODE
#endif

#define STEPPER_STATUS_SUCCESS          0u
#define STEPPER_STATUS_INVALID_STEPS    1u
#define STEPPER_STATUS_INVALID_PIN      2u
#define STEPPER_STATUS_PIN_CONFLICT     3u
#define STEPPER_STATUS_NOT_CONFIGURED   4u
#define STEPPER_STATUS_INVALID_SPEED    5u

#define STEPPER_PIN_COUNT_NONE 0u
#define STEPPER_PIN_COUNT_2    2u
#define STEPPER_PIN_COUNT_4    4u
#define STEPPER_PIN_COUNT_5    5u

STCStepperState *Stepper_selectContext(STCStepperState *context)
    STC_STEPPER_REENTRANT;

/*
 * steps_per_revolution must be in the range 1..65535.  Every pin must exist
 * on the selected variant, and no two pins may name the same physical pad.
 * A failed call leaves the previous configuration unchanged.
 */
uint8_t Stepper_setPins2(unsigned long steps_per_revolution,
                         uint8_t pin1, uint8_t pin2)
                         STC_STEPPER_REENTRANT;
uint8_t Stepper_setPins4(unsigned long steps_per_revolution,
                         uint8_t pin1, uint8_t pin2, uint8_t pin3,
                         uint8_t pin4) STC_STEPPER_REENTRANT;
uint8_t Stepper_setPins5(unsigned long steps_per_revolution,
                         uint8_t pin1, uint8_t pin2, uint8_t pin3,
                         uint8_t pin4, uint8_t pin5)
                         STC_STEPPER_REENTRANT;

/*
 * rpm must be positive.  Zero or a negative value disables motion; delays
 * shorter than one microsecond are clamped to one microsecond.
 */
uint8_t Stepper_setSpeed(long rpm) STC_STEPPER_REENTRANT;

/* Positive and negative values select opposite directions. */
void Stepper_step(long steps_to_move) STC_STEPPER_REENTRANT;

/* De-energizes every configured output without discarding the configuration. */
void Stepper_release(void) STC_STEPPER_REENTRANT;

unsigned long Stepper_stepsPerRevolution(void) STC_STEPPER_REENTRANT;
uint8_t Stepper_pinCount(void) STC_STEPPER_REENTRANT;
uint8_t Stepper_isConfigured(void) STC_STEPPER_REENTRANT;

#if defined(__cplusplus) && defined(STCXX_CPP_CORE) && STCXX_CPP_CORE

} /* extern "C" */

# include "StepperClass.h"

#else

typedef struct {
    uint8_t (*setPins2)(unsigned long steps_per_revolution,
                        uint8_t pin1, uint8_t pin2)
                        STC_STEPPER_REENTRANT;
    uint8_t (*setPins4)(unsigned long steps_per_revolution,
                        uint8_t pin1, uint8_t pin2, uint8_t pin3,
                        uint8_t pin4) STC_STEPPER_REENTRANT;
    uint8_t (*setPins5)(unsigned long steps_per_revolution,
                        uint8_t pin1, uint8_t pin2, uint8_t pin3,
                        uint8_t pin4, uint8_t pin5)
                        STC_STEPPER_REENTRANT;
    uint8_t (*setSpeed)(long rpm) STC_STEPPER_REENTRANT;
    void (*step)(long steps_to_move) STC_STEPPER_REENTRANT;
    void (*release)(void) STC_STEPPER_REENTRANT;
    unsigned long (*stepsPerRevolution)(void) STC_STEPPER_REENTRANT;
    uint8_t (*pinCount)(void) STC_STEPPER_REENTRANT;
    uint8_t (*isConfigured)(void) STC_STEPPER_REENTRANT;
} STCStepperClass;

/* Keep the read-only dispatch table out of scarce 8051 data memory. */
extern STC_STEPPER_CODE const STCStepperClass Stepper;

# ifdef __cplusplus
}
# endif

#endif /* C++ class profile */

#endif
