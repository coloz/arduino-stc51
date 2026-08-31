#include "Arduino.h"

int main(void)
{
    init();
    initVariant();
    setup();

    for (;;) {
        loop();
        yield();
    }
}
