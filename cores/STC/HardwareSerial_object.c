#include "Arduino.h"

__code const HardwareSerialClass Serial = {
    Serial_begin,
    Serial_end,
    Serial_available,
    Serial_availableForWrite,
    Serial_peek,
    Serial_read,
    Serial_readBytes,
    Serial_write,
    Serial_flush,
    Serial_overflow,
    Serial_print,
    Serial_println
#if STC_CORE_SERIAL_BUFFERED_RX
    ,
    Serial_printNumber,
    Serial_printlnNumber
#endif
};
