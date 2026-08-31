#include "Arduino.h"

size_t Serial_print(const char *text)
{
    size_t count = 0u;

    if (text == (const char *)0) {
        return 0u;
    }
    while (*text != '\0') {
        if (Serial_write((uint8_t)*text) == 0u) {
            break;
        }
        ++text;
        ++count;
    }
    return count;
}

size_t Serial_println(const char *text)
{
    size_t count = Serial_print(text);

    count += Serial_write((uint8_t)'\r');
    count += Serial_write((uint8_t)'\n');
    return count;
}
