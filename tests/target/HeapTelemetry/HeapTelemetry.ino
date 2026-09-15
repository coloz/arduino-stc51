#include <Arduino.h>
#include <cpp/stc_c_hal.h>
#include <cpp/stcxx_allocator.h>

extern "C" void heap_test_reset(void);
extern "C" void heap_test_repair_list(void);
extern "C" uint8_t heap_test_corrupt(uint8_t kind);

static uint8_t *boot_memory;
static uint16_t boot_initial;
static bool boot_ok;
struct BeforeSetup {
    BeforeSetup() {
        stcxx_allocator_telemetry_t before = {}, after = {};
        boot_ok = stcxx_allocator_read_telemetry(&before) != 0;
        boot_initial = before.initial_total_free_bytes;
        boot_memory = static_cast<uint8_t *>(stcxx_malloc(13));
        if (boot_memory) {
            boot_memory[0] = 0x31;
            boot_memory[12] = 0x79;
        }
        boot_ok = boot_ok && boot_memory &&
            stcxx_allocator_read_telemetry(&after) &&
            before.current_total_free_bytes == boot_initial &&
            after.current_total_free_bytes < boot_initial &&
            after.minimum_total_free_bytes == after.current_total_free_bytes;
    }
};
static BeforeSetup before_setup;
static unsigned char checks, failures;
static void text(const char *s) {
    while (*s) Serial_write(static_cast<uint8_t>(*s++));
}
static void decimal(unsigned char n) {
    if (n >= 10) Serial_write(static_cast<uint8_t>('0' + n / 10));
    Serial_write(static_cast<uint8_t>('0' + n % 10));
}
static void check(bool condition) {
    ++checks;
    if (!condition) {
        ++failures;
        text("FAIL check "); decimal(checks); text("\n");
    }
}

void setup() {
    Serial_begin(38400UL);
    text("BEGIN heap-telemetry\n");
    stcxx_allocator_telemetry_t t = {};
    check(boot_ok);
    check(stcxx_allocator_read_telemetry(&t) != 0);
    check(t.initial_total_free_bytes == boot_initial &&
          t.current_total_free_bytes < boot_initial &&
          t.minimum_total_free_bytes <= t.current_total_free_bytes);
    check(boot_memory && boot_memory[0] == 0x31 && boot_memory[12] == 0x79);
    stcxx_free(boot_memory); boot_memory = 0;
    check(stcxx_allocator_read_telemetry(&t) != 0);
    check(t.current_total_free_bytes == boot_initial &&
          t.current_largest_free_block_bytes == boot_initial);

    uint8_t *a = static_cast<uint8_t *>(stcxx_malloc(64));
    void *b = stcxx_malloc(96);
    check(a && b && a != b);
    if (a) for (uint8_t i = 0; i < 64; ++i) a[i] = i ^ 0x5a;
    uint8_t *grown = a ? static_cast<uint8_t *>(stcxx_realloc(a, 160)) : 0;
    check(grown != 0);
    if (grown) a = grown;
    bool preserved = a != 0;
    if (a) for (uint8_t i = 0; i < 64; ++i) preserved = preserved && a[i] == (i ^ 0x5a);
    check(preserved);
    check(stcxx_allocator_read_telemetry(&t) != 0);
    check(t.current_total_free_bytes < boot_initial &&
          t.minimum_total_free_bytes <= t.current_total_free_bytes &&
          t.minimum_largest_free_block_bytes <= t.current_largest_free_block_bytes);
    stcxx_free(b); stcxx_free(a);
    check(stcxx_allocator_read_telemetry(&t) != 0);
    check(t.current_total_free_bytes == boot_initial &&
          t.current_largest_free_block_bytes == boot_initial);

    // Exhaustion must stay exhausted; a subsequent request cannot reinitialize
    // the arena and alias a live allocation. Low-water marks must remain zero.
    uint16_t extent = t.current_largest_free_block_bytes;
    uint8_t *whole = static_cast<uint8_t *>(stcxx_malloc(extent));
    check(whole != 0);
    if (whole) { whole[0] = 0x67; whole[extent - 1] = 0xab; }
    check(stcxx_allocator_read_telemetry(&t) != 0);
    check(t.current_total_free_bytes == 0 && t.current_largest_free_block_bytes == 0);
    void *extra = stcxx_malloc(8);
    check(extra == 0);
    check(whole && whole[0] == 0x67 && whole[extent - 1] == 0xab);
    stcxx_free(extra); stcxx_free(whole);
    check(stcxx_allocator_read_telemetry(&t) != 0);
    check(t.current_total_free_bytes == boot_initial &&
          t.minimum_total_free_bytes == 0 && t.minimum_largest_free_block_bytes == 0);

    // Every injection starts with no live allocations. Corrupt free-list
    // pointers must be rejected before dereference; failure remains sticky
    // even after repairing the list, until the full telemetry reset.
    for (uint8_t kind = 1; kind <= 7; ++kind) {
        heap_test_reset();
        check(stcxx_allocator_read_telemetry(&t) != 0);
        check(heap_test_corrupt(kind) != 0);
        t.arena_bytes = 0xabcd;
        check(stcxx_allocator_read_telemetry(&t) == 0);
        check(t.arena_bytes == 0xabcd);
        heap_test_repair_list();
        check(stcxx_allocator_read_telemetry(&t) == 0);
    }
    heap_test_reset();
    check(stcxx_allocator_read_telemetry(&t) != 0);
    check(t.current_total_free_bytes == boot_initial &&
          t.minimum_total_free_bytes == boot_initial);
    text("CHECKS "); decimal(checks); text("\n");
    text(failures || checks != 57 ? "FAIL heap-telemetry\n" : "PASS heap-telemetry\n");
}
void loop() {}
