/* Exercise the real C facade through its indirect-call table. GPIO and time
 * are modeled; the host's unsigned-long width is supplemented by target tests. */
#include <Stepper.h>
#include <assert.h>
#include <limits.h>
#include <stdio.h>
#include <string.h>

typedef struct { uint8_t kind, pin, value; unsigned long time; } Event;
static Event events[2048];
static unsigned int event_count, writes, delays, yields;
static uint8_t levels[32], modes[32];
static unsigned long now;
static void (*yield_hook)(void);
static void event(uint8_t kind, uint8_t pin, uint8_t value) {
    assert(event_count < sizeof(events) / sizeof(events[0]));
    events[event_count++] = (Event){kind, pin, value, now};
}
unsigned long micros(void) { return now; }
void delayMicroseconds(unsigned int us) {
    assert(us && us <= 60000u);
    now += us; ++delays; event('D', 0, 0);
}
void yield(void) {
    assert(++yields < 2000u);
    if (yield_hook) yield_hook();
}
void pinMode(uint8_t pin, uint8_t mode) {
    assert(digitalPinIsValid(pin)); modes[pin] = mode; event('M', pin, mode);
}
void digitalWrite(uint8_t pin, uint8_t value) {
    assert(digitalPinIsValid(pin)); assert(value <= HIGH);
    levels[pin] = value; ++writes; event('W', pin, value);
}
uint8_t digitalPinIsValid(uint8_t pin) { return pin < 32u; }
uint8_t digitalPinsSharePhysicalPad(uint8_t a, uint8_t b) {
    return (a & 15u) == (b & 15u);
}
void stepper_test_clear(void) { event_count = writes = delays = yields = 0; }
unsigned int stepper_test_writes(void) { return writes; }
uint8_t stepper_test_value(uint8_t pin) { assert(pin < 32u); return levels[pin]; }
void stepper_test_set_hook(void (*hook)(void)) { yield_hook = hook; }

static uint8_t configure(unsigned long steps, uint8_t count, const uint8_t *p) {
    if (count == 2) return Stepper.setPins2(steps, p[0], p[1]);
    if (count == 4) return Stepper.setPins4(steps, p[0], p[1], p[2], p[3]);
    return Stepper.setPins5(steps, p[0], p[1], p[2], p[3], p[4]);
}
static void rejected(STCStepperState *state, unsigned long steps, uint8_t count,
                     const uint8_t *p, uint8_t expected) {
    STCStepperState before = *state;
    stepper_test_clear();
    assert(configure(steps, count, p) == expected);
    assert(memcmp(state, &before, sizeof(before)) == 0);
    assert(event_count == 0);
}
static void validation(void) {
    STCStepperState state = {0};
    STCStepperState *prior = Stepper_selectContext(&state);
    const uint8_t counts[] = {2, 4, 5};
    uint8_t pins[5] = {0, 1, 2, 3, 4};
    assert(Stepper.setSpeed(1) == STEPPER_STATUS_NOT_CONFIGURED);
    assert(!Stepper.isConfigured() && Stepper.pinCount() == 0);
    Stepper.step(LONG_MIN); assert(writes == 0);
    for (unsigned c = 0; c < 3; ++c) {
        uint8_t count = counts[c];
        assert(configure(200, count, pins) == STEPPER_STATUS_SUCCESS);
        assert(Stepper.isConfigured() && Stepper.pinCount() == count);
        assert(Stepper.stepsPerRevolution() == 200);
        rejected(&state, 0, count, pins, STEPPER_STATUS_INVALID_STEPS);
        rejected(&state, 65536UL, count, pins, STEPPER_STATUS_INVALID_STEPS);
        for (unsigned i = 0; i < count; ++i) {
            pins[i] = NOT_A_PIN;
            rejected(&state, 200, count, pins, STEPPER_STATUS_INVALID_PIN);
            pins[i] = (uint8_t)i;
            for (unsigned j = i + 1; j < count; ++j) {
                pins[j] = pins[i];
                rejected(&state, 200, count, pins, STEPPER_STATUS_PIN_CONFLICT);
                pins[j] = pins[i] + 16u;
                rejected(&state, 200, count, pins, STEPPER_STATUS_PIN_CONFLICT);
                pins[j] = (uint8_t)j;
            }
        }
        pins[1] = pins[0]; pins[count - 1] = NOT_A_PIN;
        rejected(&state, 200, count, pins, STEPPER_STATUS_INVALID_PIN);
        for (unsigned i = 0; i < 5; ++i) pins[i] = (uint8_t)i;
        assert(configure(65535UL, count, pins) == STEPPER_STATUS_SUCCESS);
        assert(Stepper.stepsPerRevolution() == 65535UL);
    }
    Stepper_selectContext(prior);
}
static void phases(void) {
    /* Output sequences are the motor winding patterns, starting at phase 1. */
    const uint8_t forward2[] = {3, 1, 0, 2};
    const uint8_t forward4[] = {6, 10, 9, 5};
    const uint8_t forward5[] = {18, 26, 10, 11, 9, 13, 5, 21, 20, 22};
    const uint8_t *patterns[] = {forward2, forward4, forward5};
    const uint8_t counts[] = {2, 4, 5}, periods[] = {4, 4, 10};
    const uint8_t pins[] = {0, 1, 2, 3, 4};
    for (unsigned c = 0; c < 3; ++c) {
        STCStepperState state = {0};
        STCStepperState *prior = Stepper_selectContext(&state);
        stepper_test_clear();
        assert(configure(200, counts[c], pins) == STEPPER_STATUS_SUCCESS);
        assert(event_count == counts[c] * 3u);
        for (unsigned i = 0; i < counts[c]; ++i) {
            assert(events[3*i].kind == 'M' && events[3*i].pin == i && events[3*i].value == OUTPUT_OPEN_DRAIN);
            assert(events[3*i+1].kind == 'W' && events[3*i+1].pin == i && events[3*i+1].value == LOW);
            assert(events[3*i+2].kind == 'M' && events[3*i+2].pin == i && events[3*i+2].value == OUTPUT);
        }
        stepper_test_clear(); Stepper.step(1); assert(writes == 0);
        assert(Stepper.setSpeed(LONG_MAX) == STEPPER_STATUS_SUCCESS);
        assert(state.step_delay_us == 1);
        for (unsigned dir = 0; dir < 2; ++dir) {
            stepper_test_clear(); Stepper.step(dir ? -(long)periods[c] : periods[c]);
            assert(writes == periods[c] * counts[c]);
            unsigned w = 0;
            for (unsigned e = 0; e < event_count; ++e) if (events[e].kind == 'W') {
                unsigned step = w / counts[c], pin = w % counts[c];
                unsigned pattern = dir ? (2u * periods[c] - 2u - step) % periods[c] : step;
                assert(events[e].pin == pin);
                assert(events[e].value == ((patterns[c][pattern] >> pin) & 1u));
                ++w;
            }
            assert(state.phase == 0);
        }
        stepper_test_clear(); Stepper.release(); assert(writes == counts[c]);
        for (unsigned i = 0; i < counts[c]; ++i) assert(levels[i] == LOW && modes[i] == OUTPUT);
        assert(Stepper.isConfigured());
        Stepper_selectContext(prior);
    }
}
static void timing_and_detach(void) {
    STCStepperState state = {0};
    STCStepperState *prior = Stepper_selectContext(&state);
    const uint8_t pins[] = {0, 1, 2, 3, 4}, next[] = {6, 7, 8, 9, 10};
    assert(configure(200, 5, pins) == 0);
    now = ULONG_MAX - 49999UL;
    assert(Stepper.setSpeed(3) == 0 && state.step_delay_us == 100000UL);
    stepper_test_clear(); Stepper.step(1);
    assert(delays == 2 && yields == 3 && now == 50000UL && state.last_step_time == now);
    assert(events[0].kind == 'D' && events[0].time == 10000UL);
    assert(events[1].kind == 'D' && events[1].time == 50000UL);
    assert(Stepper.setSpeed(0) == STEPPER_STATUS_INVALID_SPEED);
    stepper_test_clear(); Stepper.step(LONG_MIN); assert(writes == 0 && delays == 0);
    assert(Stepper.setSpeed(-1) == STEPPER_STATUS_INVALID_SPEED);
    assert(Stepper.setSpeed(60) == 0);
    stepper_test_clear(); Stepper.step(0); assert(event_count == 0);
    stepper_test_clear(); assert(configure(1, 2, next) == 0);
    assert(event_count == 16);
    for (unsigned i = 0; i < 5; ++i) {
        assert(events[i].kind == 'W' && events[i].pin == i && events[i].value == LOW);
        assert(events[i+5].kind == 'M' && events[i+5].pin == i && events[i+5].value == INPUT);
    }
    assert(state.step_delay_us == 0 && state.phase == 0);
    assert(state.pins[2] == NOT_A_PIN && state.pins[3] == NOT_A_PIN && state.pins[4] == NOT_A_PIN);
    Stepper_selectContext(prior);
    assert(Stepper_selectContext(NULL) == prior);
    Stepper_selectContext(prior);
}
void stepper_cpp_checks(void);
int main(void) {
    validation(); phases(); timing_and_detach(); stepper_cpp_checks();
    puts("PASS Stepper: pin validation/aliases, output order, all winding phases/directions, timing wrap/chunks, C table and C++ nested contexts");
}
