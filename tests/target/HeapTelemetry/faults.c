/* Test-only corruption of the locked SDCC free-list ABI. Never link this file
 * into product firmware. All allocations are released before each injection. */
#include <stdint.h>
#if !defined(__SDCC_mcs251)
#error This fixture requires the native MCS251 C compiler
#endif
typedef struct test_heap_header __xdata header_t;
struct test_heap_header { header_t *next; header_t *next_free; };
typedef char pointer_size_check[sizeof(header_t *) == 3u ? 1 : -1];
typedef char header_size_check[sizeof(struct test_heap_header) == 6u ? 1 : -1];
extern __xdata unsigned char __sdcc_heap[];
extern const unsigned long __sdcc_heap_size32;
extern header_t * __xdata __sdcc_heap_free;
extern void __sdcc_heap_init(void);
extern void __stcxx_heap_init(void);

void heap_test_reset(void) { __stcxx_heap_init(); }
void heap_test_repair_list(void) { __sdcc_heap_init(); }
uint8_t heap_test_corrupt(uint8_t kind) {
    unsigned char __xdata *start = __sdcc_heap;
    unsigned char __xdata *end = start + (__sdcc_heap_size32 - 1UL);
    header_t *first = __sdcc_heap_free;
    switch (kind) {
    case 1: __sdcc_heap_free = (header_t *)(end + 1); break;
    case 2: first->next = first; break;
    case 3: first->next = (header_t *)(end + 1); break;
    case 4: first->next_free = first; break;
    case 5: __sdcc_heap_free = (header_t *)(end - 2); break;
    case 6:
        first->next = (header_t *)(start + 12);
        first->next_free = (header_t *)(start + 6);
        break;
    case 7: first->next_free = (header_t *)end; break;
    default: return 0;
    }
    return 1;
}
