#include <NativeTrim.h>
volatile uint16_t nativeResult;
void setup() { nativeResult = nativeValue() + nativeFont[1]; }
void loop() {}
