#include <Arduino.h>
#include "identity.h"

static unsigned failures, checks;
static void check(bool condition) {
    ++checks;
    if (!condition) { ++failures; Serial.print("FAIL "); Serial.println(checks); }
}
static void runChecks() {
    Identity direct = makeIdentity(17);
    check(direct.valid() && direct.value == 17);
    Identity forwarded = forwardIdentity(23);
    check(forwarded.valid() && forwarded.value == 23);
    Identity (*factory)(unsigned) = identityFactory();
    Identity indirect = factory(31);
    check(indirect.valid() && indirect.value == 31);
    Identity copy(direct);
    check(copy.valid() && copy.value == 17 && direct.valid());
    Identity moved(static_cast<Identity &&>(copy));
    check(moved.valid() && moved.value == 17 && copy.valid() && copy.value == 0);
    bool good = true;
    for (unsigned i = 0; i < 1000; ++i) {
        Identity next = forwardIdentity(i);
        if (!next.valid() || next.value != i) { good = false; break; }
    }
    check(good && direct.valid() && forwarded.valid() && indirect.valid());
}
void setup() {
    Serial.begin(38400);
    Serial.println("BEGIN return-identity");
    runChecks();
    Serial.print("CHECKS "); Serial.println(checks);
    Serial.println(failures ? "FAIL return-identity" : "PASS return-identity");
}
void loop() {}
