/* SPDX-License-Identifier: MIT */
#include <Arduino.h>
#include <SoftwareSerial.h>

/* P3.2/P3.3 also serve INT0/INT1 and common Wire/SPI defaults.  Change the
 * pins when those resources are in use.  Cross RX/TX with a TTL-level peer,
 * connect GND, and leave idle gaps between frames: receive is not interrupt
 * driven and bytes arriving during transmit are lost.  Never connect RS-232
 * voltage levels directly to an MCU pin. */
#define SOFT_RX_PIN P3_2
#define SOFT_TX_PIN P3_3

void setup(void)
{
    if (SoftwareSerial.setPins(SOFT_RX_PIN, SOFT_TX_PIN)) {
        (void)SoftwareSerial.begin(9600UL);
    }
}

void loop(void)
{
    int value;

    if (SoftwareSerial.poll() != 0u) {
        value = SoftwareSerial.read();
        if (value >= 0) {
            (void)SoftwareSerial.write((uint8_t)value);
        }
    }
}
