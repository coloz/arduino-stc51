#include <Arduino.h>
#include "callbacks.h"
static unsigned failures, checks;
static void check(bool condition) {
    ++checks;
    if (!condition) { ++failures; Serial.print("FAIL "); Serial.println(checks); }
}
static unsigned short cpp_scalar(unsigned short n) { return n * 3u + 1u; }
static void cpp_result(CallbackPair *out, unsigned short n) {
    out->first = n + 3u;
    out->second = n ^ 0x55aau;
}
static CallbackPair internal_pair(unsigned short n) {
    CallbackPair result = {n, static_cast<unsigned short>(n + 1u)};
    return result;
}
void setup() {
    Serial.begin(38400);
    Serial.println("BEGIN native-callbacks");
    CallbackPair pair;
    check(native_invoke_scalar(cpp_scalar, 7) == 22);
    native_invoke_result(cpp_result, &pair, 13);
    check(pair.first == 16 && pair.second == (13u ^ 0x55aau));
    check(native_scalar_factory()(0x1234) == (0x1234u ^ 0x5a5au));
    native_result_factory()(&pair, 19);
    check(pair.first == 19 && pair.second == 20);
    native_save_result(cpp_result);
    native_apply_saved(&pair, 21);
    check(pair.first == 24 && pair.second == (21u ^ 0x55aau));
    CallbackPair (*volatile factory)(unsigned short) = internal_pair;
    CallbackPair internal = factory(33);
    check(internal.first == 33 && internal.second == 34);
    Serial.print("CHECKS "); Serial.println(checks);
    Serial.println(failures ? "FAIL native-callbacks" : "PASS native-callbacks");
}
void loop() {}
