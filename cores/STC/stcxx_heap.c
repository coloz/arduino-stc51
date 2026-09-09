/*
 * The stock SDCC malloc archive supplies a 1024-byte XDATA heap.  That is
 * smaller than a single ArduinoJson 7 pool on the 24-bit MCS251 ABI (3328
 * bytes), so C++ profiles provide an explicit board-sized heap instead.  The
 * 4 KiB-XDATA STC32F profile uses a separately marked 3584-byte arena, while
 * constrained MCS51 profiles use a smaller explicit heap.  Both retain the
 * same single-provider/link-audit contract.
 *
 * This translation unit is pulled out of the core archive by the call from
 * main.c.  Defining the two SDCC heap symbols before libc is scanned prevents
 * the archive's _heap.rel fallback from being selected.
 */
#if defined(STCXX_CPP_CORE) && STCXX_CPP_CORE

#include <stddef.h>

#include "cpp/stcxx_allocator.h"

#if !defined(__SDCC_mcs251) && !defined(__SDCC_mcs51)
#error "The STC C++ heap contract requires SDCC MCS51 or MCS251."
#endif

#if !defined(STCXX_HEAP_SIZE)
#error "A board C++ profile must define STCXX_HEAP_SIZE."
#endif

#if defined(STCXX_MCS251_CONSTRAINED_HEAP) && \
    STCXX_MCS251_CONSTRAINED_HEAP != 1
#error "STCXX_MCS251_CONSTRAINED_HEAP must be exactly 1 when defined."
#elif defined(STCXX_MCS251_CONSTRAINED_HEAP) && \
      !defined(__SDCC_mcs251)
#error "The constrained STCXX heap contract is only valid on MCS251."
#elif defined(STCXX_MCS251_CONSTRAINED_HEAP) && \
      STCXX_HEAP_SIZE != 3584UL
#error "The constrained MCS251 STCXX heap must be exactly 3584 bytes."
#elif defined(__SDCC_mcs251) && \
      !defined(STCXX_MCS251_CONSTRAINED_HEAP) && \
      STCXX_HEAP_SIZE < 4096UL
#error "MCS251 STCXX_HEAP_SIZE must fit one ArduinoJson 7 pool."
#elif defined(__SDCC_mcs51) && STCXX_HEAP_SIZE < 512UL
#error "MCS51 STCXX_HEAP_SIZE must be at least 512 bytes for qualified allocator headroom."
#endif

#if STCXX_HEAP_SIZE > 32768UL
#error "STCXX_HEAP_SIZE exceeds the qualified SDCC MCS251 heap bound."
#endif

__xdata unsigned char __sdcc_heap[STCXX_HEAP_SIZE];
#if defined(__SDCC_mcs251)
/* Match the compiler runtime's explicit 32-bit custom-heap contract. */
const unsigned long __sdcc_heap_size32 = STCXX_HEAP_SIZE;
#else
const unsigned int __sdcc_heap_size = STCXX_HEAP_SIZE;
#endif

extern void __sdcc_heap_init(void);

typedef struct stcxx_heap_header __xdata stcxx_heap_header_t;

struct stcxx_heap_header {
    stcxx_heap_header_t *next;
    stcxx_heap_header_t *next_free;
};

#if defined(__SDCC_mcs251)
#define STCXX_HEAP_POINTER_BYTES 3u
#else
#define STCXX_HEAP_POINTER_BYTES 2u
#endif

/*
 * Compile-time ABI checks for the locked SDCC device/lib/malloc.c header.
 * The typedef form remains usable with both qualified SDCC C frontends.
 */
typedef char stcxx_heap_pointer_size_must_match[
    sizeof(stcxx_heap_header_t *) == STCXX_HEAP_POINTER_BYTES ? 1 : -1];
typedef char stcxx_heap_payload_offset_must_match[
    offsetof(struct stcxx_heap_header, next_free) ==
        STCXX_HEAP_POINTER_BYTES ? 1 : -1];
typedef char stcxx_heap_header_size_must_match[
    sizeof(struct stcxx_heap_header) ==
        (2u * STCXX_HEAP_POINTER_BYTES) ? 1 : -1];
typedef char stcxx_heap_telemetry_size_must_match[
    sizeof(stcxx_allocator_telemetry_t) == 12u ? 1 : -1];
typedef char stcxx_heap_telemetry_arena_offset_must_match[
    offsetof(stcxx_allocator_telemetry_t, arena_bytes) == 0u ? 1 : -1];
typedef char stcxx_heap_telemetry_final_offset_must_match[
    offsetof(stcxx_allocator_telemetry_t,
             minimum_largest_free_block_bytes) == 10u ? 1 : -1];

extern stcxx_heap_header_t * __xdata __sdcc_heap_free;

/*
 * These counters live in stcxx_heap_state.c so the explicit heap object's
 * XSEG size remains exactly STCXX_HEAP_SIZE for the single-provider link
 * audit.  They are still XDATA and therefore do not consume the MCS51 IDATA
 * stack guard.
 */
extern __xdata unsigned char __stcxx_heap_telemetry_ready_state;
extern __xdata unsigned char __stcxx_heap_telemetry_valid_state;
extern __xdata unsigned int __stcxx_heap_initial_total_free_state;
extern __xdata unsigned int __stcxx_heap_minimum_total_free_state;
extern __xdata unsigned int __stcxx_heap_minimum_largest_free_state;

#define stcxx_heap_telemetry_ready \
    __stcxx_heap_telemetry_ready_state
#define stcxx_heap_telemetry_valid \
    __stcxx_heap_telemetry_valid_state
#define stcxx_heap_initial_total_free \
    __stcxx_heap_initial_total_free_state
#define stcxx_heap_minimum_total_free \
    __stcxx_heap_minimum_total_free_state
#define stcxx_heap_minimum_largest_free \
    __stcxx_heap_minimum_largest_free_state

/*
 * Match the free-list ABI in the locked SDCC device/lib/malloc.c.  Every
 * pointer must stay inside this board's explicit heap, the address-sorted
 * free list must move strictly forward, and the node limit rejects cycles
 * even if corrupt pointers happen to remain in range.
 */
static unsigned char stcxx_heap_snapshot(
    unsigned int *total_free,
    unsigned int *largest_free)
{
    unsigned char __xdata *const heap_start = &__sdcc_heap[0];
    unsigned char __xdata *const heap_end =
        &__sdcc_heap[STCXX_HEAP_SIZE - 1u];
    stcxx_heap_header_t *header = __sdcc_heap_free;
    unsigned int nodes = 0u;
    const unsigned int maximum_nodes =
        (unsigned int)(STCXX_HEAP_SIZE /
                       sizeof(struct stcxx_heap_header)) + 1u;
    const unsigned int payload_offset =
        (unsigned int)offsetof(struct stcxx_heap_header, next_free);

    *total_free = 0u;
    *largest_free = 0u;
    while (header != (stcxx_heap_header_t *)0) {
        unsigned char __xdata *address =
            (unsigned char __xdata *)header;
        unsigned char __xdata *next_address;
        stcxx_heap_header_t *next_free;
        unsigned int raw_bytes;
        unsigned int payload_bytes;

        ++nodes;
        if (nodes > maximum_nodes || address < heap_start ||
            address >= heap_end ||
            (unsigned int)(heap_end - address) <
                (unsigned int)sizeof(struct stcxx_heap_header)) {
            return 0u;
        }
        next_address = (unsigned char __xdata *)header->next;
        next_free = header->next_free;
        if (next_address <= address || next_address > heap_end ||
            (next_free != (stcxx_heap_header_t *)0 &&
             ((unsigned char __xdata *)next_free <= address ||
              (unsigned char __xdata *)next_free >= heap_end ||
              next_address > (unsigned char __xdata *)next_free))) {
            return 0u;
        }
        raw_bytes = (unsigned int)(next_address - address);
        if (raw_bytes < payload_offset) {
            return 0u;
        }
        payload_bytes = raw_bytes - payload_offset;
        *total_free += payload_bytes;
        if (payload_bytes > *largest_free) {
            *largest_free = payload_bytes;
        }
        header = next_free;
    }
    return 1u;
}

void __stcxx_heap_sample(void)
{
    unsigned int total_free;
    unsigned int largest_free;

    if (!stcxx_heap_telemetry_ready || !stcxx_heap_telemetry_valid ||
        !stcxx_heap_snapshot(&total_free, &largest_free)) {
        stcxx_heap_telemetry_valid = 0u;
        return;
    }
    if (total_free < stcxx_heap_minimum_total_free) {
        stcxx_heap_minimum_total_free = total_free;
    }
    if (largest_free < stcxx_heap_minimum_largest_free) {
        stcxx_heap_minimum_largest_free = largest_free;
    }
}

void __stcxx_heap_init(void)
{
    unsigned int total_free;
    unsigned int largest_free;

    __sdcc_heap_init();
    stcxx_heap_telemetry_ready = 1u;
    stcxx_heap_telemetry_valid =
        stcxx_heap_snapshot(&total_free, &largest_free);
    stcxx_heap_initial_total_free = total_free;
    stcxx_heap_minimum_total_free = total_free;
    stcxx_heap_minimum_largest_free = largest_free;
}

unsigned char __stcxx_heap_read_telemetry(
    stcxx_allocator_telemetry_t *telemetry)
{
    unsigned int total_free;
    unsigned int largest_free;

    if (telemetry == (stcxx_allocator_telemetry_t *)0 ||
        !stcxx_heap_telemetry_ready || !stcxx_heap_telemetry_valid ||
        !stcxx_heap_snapshot(&total_free, &largest_free)) {
        stcxx_heap_telemetry_valid = 0u;
        return 0u;
    }
    telemetry->arena_bytes = (unsigned int)STCXX_HEAP_SIZE;
    telemetry->initial_total_free_bytes =
        stcxx_heap_initial_total_free;
    telemetry->current_total_free_bytes = total_free;
    telemetry->current_largest_free_block_bytes = largest_free;
    telemetry->minimum_total_free_bytes =
        stcxx_heap_minimum_total_free;
    telemetry->minimum_largest_free_block_bytes =
        stcxx_heap_minimum_largest_free;
    return 1u;
}

#endif /* STCXX_CPP_CORE */
