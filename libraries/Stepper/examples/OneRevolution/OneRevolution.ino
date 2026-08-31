/* SPDX-License-Identifier: MIT */
#include <Arduino.h>
#include <Stepper.h>

#define MOTOR_STEPS_PER_REVOLUTION 200UL

/* Drive the motor through a suitable transistor/driver stage.  Never connect
 * a motor winding directly to an MCU pin. */

void setup(void)
{
    if (Stepper.setPins4(MOTOR_STEPS_PER_REVOLUTION,
                         P3_0, P3_1, P3_2, P3_3) ==
        STEPPER_STATUS_SUCCESS) {
        (void)Stepper.setSpeed(30L);
    }
}

void loop(void)
{
    long one_revolution;

    if (Stepper.isConfigured() == 0u) {
        delay(1000UL);
        return;
    }

    one_revolution = (long)Stepper.stepsPerRevolution();
    Stepper.step(one_revolution);
    delay(500UL);
    Stepper.step(-one_revolution);
    delay(500UL);
    Stepper.release();
    delay(1000UL);
}
