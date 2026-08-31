#include <Arduino.h>
#include <SPI.h>

void setup(void)
{
    uint8_t received;

    Serial_begin(9600UL);
    SPI.begin();
    SPI.beginTransaction(100000UL, MSBFIRST, SPI_MODE0);

    digitalWrite(SPI_DEFAULT_SS_PIN, LOW);
    received = SPI.transfer(0x5au);
    digitalWrite(SPI_DEFAULT_SS_PIN, HIGH);

    SPI.endTransaction();
    Serial_write(received);
}

void loop(void)
{
    delay(1000UL);
}
