#include <Arduino.h>

static const uint8_t smokePin = P3_2;
static volatile int smokeAnalog;

#if STC_VARIANT_HAS_ADC != STC_CORE_HAS_ADC
# error "Variant/core ADC capability mismatch"
#endif
#if STC_VARIANT_ADC_LAYOUT != STC_CORE_ADC_LAYOUT
# error "Variant/core ADC layout mismatch"
#endif
#if STC_VARIANT_ADC_NATIVE_BITS != STC_CORE_ADC_NATIVE_BITS
# error "Variant/core ADC resolution mismatch"
#endif
#if STC_VARIANT_PINMUX_PSWX1_BIT0_CLEAR != STC_CORE_PINMUX_PSWX1_BIT0_CLEAR
# error "Variant/core startup pin routing mismatch"
#endif

#if defined(STC32CL8K64)
# if (STC_NUM_LOGICAL_DIGITAL_PINS != 19U) || \
     (STC_NUM_BONDED_DIGITAL_PINS != 17U)
#  error "STC32CL logical/physical GPIO counts are wrong"
# endif
# if !digitalPinsSharePhysicalPad(P1_4, P0_2) || \
     !digitalPinsSharePhysicalPad(P1_5, P0_3)
#  error "STC32CL physical GPIO aliases are missing"
# endif
# if (digitalPinToPhysicalAlias(P1_4) != P0_2) || \
     (digitalPinToPhysicalAlias(P0_3) != P1_5)
#  error "STC32CL physical GPIO alias mapping is wrong"
# endif
#elif defined(AI8051U_34K64)
# if (STC_NUM_LOGICAL_DIGITAL_PINS != 46U) || \
     (STC_NUM_BONDED_DIGITAL_PINS != 45U)
#  error "AI8051U logical/physical GPIO counts are wrong"
# endif
# if !digitalPinsSharePhysicalPad(P4_4, P4_5) || \
     (digitalPinToPhysicalAlias(P4_4) != P4_5)
#  error "AI8051U physical GPIO alias mapping is wrong"
# endif
#endif

#if STC_VARIANT_HAS_ADC
# ifndef A0
#  error "ADC target must expose A0"
# endif
# if NUM_ANALOG_INPUTS < 1
#  error "ADC target must expose analog inputs"
# endif
# if analogInputToDigitalPin(0) != A0
#  error "A0 mapping mismatch"
# endif
# if digitalPinToAnalogInput(A0) != 0
#  error "Digital-to-analog A0 mapping mismatch"
# endif
# if STC_VARIANT_ADC_PIN_TO_CHANNEL(A0) == NOT_AN_ADC_CHANNEL
#  error "A0 has no hardware ADC channel"
# endif
# if analogInputToDigitalPin(NUM_ANALOG_INPUTS - 1) != STC_VARIANT_LAST_ANALOG_PIN
#  error "Last analog alias mapping mismatch"
# endif
# if analogInputToDigitalPin(NUM_ANALOG_INPUTS) != NOT_A_PIN
#  error "Out-of-range analog index accepted"
# endif
#else
# if NUM_ANALOG_INPUTS != 0
#  error "Non-ADC target exposes analog inputs"
# endif
# ifdef A0
#  error "Non-ADC target must not define A0"
# endif
# if analogInputToDigitalPin(0) != NOT_A_PIN
#  error "Non-ADC target accepted an analog index"
# endif
#endif

void setup(void)
{
#if STC_MAXIMUM_CODE_BYTES <= 2048UL
    /* Keep the 2 KiB target focused on ADC. Compact UART has its own smoke test. */
#else
    pinMode(smokePin, OUTPUT);
    Serial_begin(9600UL);
    Serial_write((uint8_t)'S');
#endif

    analogReference(DEFAULT);
    analogReadResolution(10u);
#if STC_VARIANT_HAS_ADC
    smokeAnalog = analogRead(A0);
# if STC_MAXIMUM_CODE_BYTES > 2048UL
    smokeAnalog += analogRead(STC_VARIANT_LAST_ANALOG_PIN);
    smokeAnalog += analogRead(P2_0); /* Valid code, never an ADC route. */
    pinMode(A0, INPUT);             /* ADC-to-digital reuse regression. */
# endif
#else
    smokeAnalog = analogRead(NOT_A_PIN);
#endif
}

void loop(void)
{
#if STC_MAXIMUM_CODE_BYTES <= 2048UL
    yield();
#else
    digitalWrite(smokePin, HIGH);
    delay(100UL);
    digitalWrite(smokePin, LOW);
    delay(100UL);
#endif
}
