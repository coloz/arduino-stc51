#include <Arduino.h>

#if !STC_CORE_HAS_UART1
# error "CompactSerialSmoke requires a hardware UART"
#endif

void setup(void)
{
    Serial_begin(9600UL);
    Serial_write((uint8_t)'S');
}

void loop(void)
{
    yield();
}
