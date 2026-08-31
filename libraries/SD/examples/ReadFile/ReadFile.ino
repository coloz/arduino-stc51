/* SPDX-License-Identifier: MIT */
#include <Arduino.h>
#include <SD.h>

void setup(void)
{
    uint8_t chunk[16];
    size_t count;

    Serial.begin(115200UL);

    if (SD.setPins(MOSI, MISO, SCK, SS) == 0u || SD.begin(SS) == 0u) {
        Serial.println("SD init or FAT mount failed");
        Serial.printNumber((long)SD.error(), DEC);
        Serial.write((uint8_t)'\n');
        return;
    }

    Serial.print("card=");
    Serial.printNumber((long)SD.cardType(), DEC);
    Serial.print(" fat=");
    Serial.printlnNumber((long)SD.fatType(), DEC);

    if (SD.exists("README.TXT") == 0u ||
        SD.open("README.TXT", FILE_READ) == 0u) {
        Serial.println("README.TXT not found");
        return;
    }

    Serial.print("size=");
    Serial.printlnNumber((long)SD.size(), DEC);
    (void)SD.peek();
    count = SD.readBytes(chunk, sizeof(chunk));
    if (count != 0u) {
        (void)Serial.write(chunk[0]);
    }
    (void)SD.seek(0UL);

    while (SD.available() != 0UL) {
        int value = SD.read();
        if (value < 0) {
            break;
        }
        (void)Serial.write((uint8_t)value);
    }
    Serial.print("\nposition=");
    Serial.printlnNumber((long)SD.position(), DEC);
    SD.close();
}

void loop(void)
{
    delay(1000UL);
}
