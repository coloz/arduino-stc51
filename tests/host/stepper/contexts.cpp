#include <Stepper.h>
#include <cassert>

static Stepper *nested;
static unsigned calls;
static void interleave() {
    stepper_test_set_hook(nullptr);
    ++calls;
    nested->step(-1);
}
extern "C" void stepper_cpp_checks() {
    STCStepperState sentinel = {};
    STCStepperState *prior = Stepper_selectContext(&sentinel);
    Stepper first(200, 0, 1), second(200, 6, 7);
    Stepper four(200, 8, 9, 10, 11), five(200, 2, 3, 4, 5, 12);
    Stepper bad(0, 0, 1);
    assert(first && second && four && five && !bad);
    first.setSpeed(3); second.setSpeed(60);
    nested = &second; stepper_test_set_hook(interleave);
    stepper_test_clear(); first.step(1);
    assert(calls == 1 && stepper_test_writes() == 4);
    assert(stepper_test_value(0) == HIGH && stepper_test_value(1) == HIGH);
    assert(stepper_test_value(6) == LOW && stepper_test_value(7) == LOW);
    assert(Stepper_selectContext(&sentinel) == &sentinel);
    Stepper copy(first); copy.setSpeed(0);
    assert(!copy && first);
    stepper_test_clear(); copy.step(1); assert(stepper_test_writes() == 0);
    copy.setSpeed(60); copy.step(1);
    assert(stepper_test_value(0) == HIGH && stepper_test_value(1) == LOW);
    first.step(-1);
    assert(stepper_test_value(0) == LOW && stepper_test_value(1) == HIGH);
    first.release(); assert(first && first.version() == 5);
    assert(stepper_test_value(0) == LOW && stepper_test_value(1) == LOW);
    assert(Stepper_selectContext(prior) == &sentinel);
}
