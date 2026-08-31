#include "Arduino.h"

size_t Serial_printNumber(long value, uint8_t base) __reentrant
{
    static __code const char digits[] = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ";
    unsigned long magnitude;
    unsigned long place = 1UL;
    size_t count = 0u;

    if ((base < 2u) || (base > 36u)) {
        return 0u;
    }

    if ((value < 0L) && (base == 10u)) {
        if (Serial_write((uint8_t)'-') == 0u) {
            return 0u;
        }
        ++count;
        magnitude = (unsigned long)(-(value + 1L));
        ++magnitude;
    } else {
        magnitude = (unsigned long)value;
    }

    while ((magnitude / place) >= (unsigned long)base) {
        place *= (unsigned long)base;
    }
    do {
        uint8_t digit = (uint8_t)(magnitude / place);

        if (Serial_write((uint8_t)digits[digit]) == 0u) {
            break;
        }
        ++count;
        magnitude %= place;
        place /= (unsigned long)base;
    } while (place != 0UL);

    return count;
}

size_t Serial_printlnNumber(long value, uint8_t base) __reentrant
{
    size_t count = Serial_printNumber(value, base);

    count += Serial_write((uint8_t)'\r');
    count += Serial_write((uint8_t)'\n');
    return count;
}
