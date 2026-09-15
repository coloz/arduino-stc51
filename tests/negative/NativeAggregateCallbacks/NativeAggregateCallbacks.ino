#include <Arduino.h>
#include "callbacks.h"
#ifndef STCXX_CALLBACK_BAD_CASE
#define STCXX_CALLBACK_BAD_CASE 1
#endif
static NativePair make_pair(unsigned short n) {
    NativePair pair = {n, static_cast<unsigned short>(n + 1u)};
    return pair;
}
static __attribute__((noinline)) unsigned short dispatch_pair(NativePairMaker callback) {
    NativePair pair = callback(41);
    return pair.first + pair.second;
}
void setup() {
    Serial.begin(38400);
    Serial.println("BEGIN unsafe-native-callback");
    unsigned short observed;
#if STCXX_CALLBACK_BAD_CASE == 1
    observed = native_use_pair(make_pair);
#elif STCXX_CALLBACK_BAD_CASE == 2
    NativePair pair = native_pair_factory()(41);
    observed = pair.first + pair.second;
#elif STCXX_CALLBACK_BAD_CASE == 3
    NativePairMaker table[1] = {make_pair};
    observed = native_use_table(table);
#elif STCXX_CALLBACK_BAD_CASE == 4
    // Its internal caller supplies a compatible callback, but native C may
    // supply another one through the same ordinary scalar/pointer signature.
    volatile unsigned short internal_result = dispatch_pair(make_pair);
    observed = internal_result == 83 ? native_use_dispatcher(dispatch_pair) : 0;
#else
#error Invalid callback fixture case
#endif
    Serial.println(observed);
    Serial.println(observed == 83 ? "PASS unsafe-native-callback" : "FAIL unsafe-native-callback");
}
void loop() {}
