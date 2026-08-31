#include <Arduino.h>

#if (STC_MAXIMUM_CODE_BYTES > 4096UL) && !defined(__SDCC_MODEL_SMALL)
#define CORE_API_SMOKE_FULL 1
#else
#define CORE_API_SMOKE_FULL 0
#endif

/*
 * Compile/link smoke test for the Wiring-C API.  P3.2 and P3.3 are bonded on
 * every generated variant, including the six-pin STC15F104W package.
 */
static const uint8_t dataPin = P3_2;
static const uint8_t clockPin = P3_3;

static volatile unsigned long apiResult;
#if CORE_API_SMOKE_FULL
static volatile uint8_t interruptCount;

static void onExternalInterrupt(void)
{
    ++interruptCount;
}
#endif

void setup(void)
{
#if (STC_MAXIMUM_CODE_BYTES > 2048UL) && STC_VARIANT_HAS_UART1
    uint8_t serialByte = 0u;
#endif
#if CORE_API_SMOKE_FULL
    int analogValue;
#endif

#if STC_MAXIMUM_CODE_BYTES <= 2048UL
    /* Keep the 2 KiB profile bounded while still linking GPIO + timekeeping. */
    apiResult += (unsigned long)digitalPinIsValid(dataPin);
    pinMode(dataPin, OUTPUT);
    digitalWrite(dataPin, HIGH);
    apiResult += (unsigned long)digitalRead(dataPin);
    apiResult ^= millis();
    yield();
#else

    /* GPIO validity, modes, input pull-up control, and digital I/O. */
    apiResult += (unsigned long)digitalPinIsValid(dataPin);
    apiResult += (unsigned long)digitalPinIsValid(NOT_A_PIN);
    pinMode(dataPin, INPUT);
    digitalWrite(dataPin, HIGH);
    digitalWrite(dataPin, LOW);
    pinMode(dataPin, INPUT_PULLUP);
    apiResult += (unsigned long)digitalRead(dataPin);
    pinMode(dataPin, OUTPUT_QUASI);
    pinMode(dataPin, OUTPUT_OPEN_DRAIN);
    pinMode(dataPin, OUTPUT);
    digitalWrite(dataPin, LOW);

    /* Timekeeping and global interrupt control. */
    apiResult ^= millis();
    apiResult ^= micros();
    delay(1UL);
    delayMicroseconds(2u);
    noInterrupts();
    interrupts();
    yield();

#if CORE_API_SMOKE_FULL
    /* The common core deliberately supports only INT0/INT1 LOW/FALLING. */
    pinMode(dataPin, INPUT_PULLUP);
    attachInterrupt(digitalPinToInterrupt(dataPin),
                    onExternalInterrupt, FALLING);
    detachInterrupt(digitalPinToInterrupt(dataPin));

    /* Software shift helpers and bounded pulse measurements. */
    pinMode(dataPin, OUTPUT);
    pinMode(clockPin, OUTPUT);
    shiftOut(dataPin, clockPin, MSBFIRST, 0xa5u);
    pinMode(dataPin, INPUT_PULLUP);
    apiResult += (unsigned long)shiftIn(dataPin, clockPin, LSBFIRST);
    apiResult += pulseIn(dataPin, HIGH, 8UL);
    apiResult += pulseInLong(dataPin, LOW, 8UL);

    /* Math helpers and the documented non-PWM analog fallback. */
    randomSeed(0x51UL);
    apiResult += (unsigned long)random(16L);
    apiResult += (unsigned long)random_minmax(4L, 12L);
    apiResult += (unsigned long)map(5L, 0L, 10L, 0L, 100L);
    analogReference(DEFAULT);
    analogReadResolution(10u);
    analogValue = analogRead(dataPin);
    apiResult += (unsigned long)(analogValue + 1);
    analogWrite(clockPin, 128);
#endif

#if STC_MAXIMUM_CODE_BYTES > 2048UL
    /*
     * Exercise every member of the plain-C object facade.  The split serial
     * implementation keeps this linkable on STC15F104W, where these methods
     * resolve to safe UART-less stubs.
     */
    Serial.begin(9600UL);
#if STC_VARIANT_HAS_UART1
    apiResult += (unsigned long)Serial.available();
    apiResult += (unsigned long)Serial.availableForWrite();
    apiResult += (unsigned long)(Serial.peek() + 1);
    apiResult += (unsigned long)(Serial.read() + 1);
    apiResult += (unsigned long)Serial.readBytes(&serialByte, 1u);
    if (Serial.availableForWrite() > 0) {
        apiResult += (unsigned long)Serial.write((uint8_t)'A');
        apiResult += (unsigned long)Serial.print("PI=");
        apiResult += (unsigned long)Serial.printNumber(0x51L, HEX);
        apiResult += (unsigned long)Serial.println(" smoke");
        apiResult += (unsigned long)Serial.printlnNumber(314L, DEC);
    }
    Serial.flush();
    apiResult += Serial.overflow() ? 1UL : 0UL;
#else
    /* Referencing the object also verifies that its no-UART stubs link. */
    apiResult += (unsigned long)Serial.available();
#endif
    Serial.end();
#endif
#endif
}

void loop(void)
{
    /* Deliberately non-blocking: this example exists for compile/link QA. */
    yield();
}
