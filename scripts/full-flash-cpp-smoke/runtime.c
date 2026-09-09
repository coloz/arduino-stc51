#ifndef FULL_FLASH_CPP_BLOB_BYTES
#define FULL_FLASH_CPP_BLOB_BYTES 50000UL
#endif
#ifndef FULL_FLASH_CPP_BLOB_COUNT
#define FULL_FLASH_CPP_BLOB_COUNT 2
#endif

__sfr __at (0x99) SBUF;
volatile unsigned char full_flash_cpp_result;
static volatile unsigned short flash_index;

extern void __stcxx_run_global_ctors(void);
extern void setup(void);
extern void loop(void);

const __code unsigned char cpp_flash_blob0[FULL_FLASH_CPP_BLOB_BYTES] = {
    [0] = 0x10, [FULL_FLASH_CPP_BLOB_BYTES - 1] = 0xa0,
};
const __code unsigned char cpp_flash_blob1[FULL_FLASH_CPP_BLOB_BYTES] = {
    [0] = 0x11, [FULL_FLASH_CPP_BLOB_BYTES - 1] = 0xa1,
};
#if FULL_FLASH_CPP_BLOB_COUNT == 4
const __code unsigned char cpp_flash_blob2[FULL_FLASH_CPP_BLOB_BYTES] = {
    [0] = 0x12, [FULL_FLASH_CPP_BLOB_BYTES - 1] = 0xa2,
};
const __code unsigned char cpp_flash_blob3[FULL_FLASH_CPP_BLOB_BYTES] = {
    [0] = 0x13, [FULL_FLASH_CPP_BLOB_BYTES - 1] = 0xa3,
};
#endif

static void print_text(const char *text) {
    while (*text) SBUF = *text++;
}

static void print_hex(unsigned char value) {
    unsigned char digit = value >> 4;
    SBUF = digit < 10 ? '0' + digit : 'A' + digit - 10;
    digit = value & 15;
    SBUF = digit < 10 ? '0' + digit : 'A' + digit - 10;
}

void full_flash_cpp_panic(void) {
    print_text("CPP_FULL_FLASH_PANIC\n");
    for (;;) {}
}

int main(void) {
    unsigned char passed;
    __stcxx_run_global_ctors();
    setup();
    loop();
    passed = full_flash_cpp_result == 0x0f;
    flash_index = 0;
    passed &= cpp_flash_blob0[flash_index] == 0x10;
    passed &= cpp_flash_blob1[flash_index] == 0x11;
    flash_index = FULL_FLASH_CPP_BLOB_BYTES - 1;
    passed &= cpp_flash_blob0[flash_index] == 0xa0;
    passed &= cpp_flash_blob1[flash_index] == 0xa1;
#if FULL_FLASH_CPP_BLOB_COUNT == 4
    flash_index = 0;
    passed &= cpp_flash_blob2[flash_index] == 0x12;
    passed &= cpp_flash_blob3[flash_index] == 0x13;
    flash_index = FULL_FLASH_CPP_BLOB_BYTES - 1;
    passed &= cpp_flash_blob2[flash_index] == 0xa2;
    passed &= cpp_flash_blob3[flash_index] == 0xa3;
#endif
    if (!passed) {
        print_text("CPP_MASK=");
        print_hex(full_flash_cpp_result);
        SBUF = '\n';
        flash_index = 0;
        print_hex(cpp_flash_blob0[flash_index]);
        print_hex(cpp_flash_blob1[flash_index]);
        flash_index = FULL_FLASH_CPP_BLOB_BYTES - 1;
        print_hex(cpp_flash_blob0[flash_index]);
        print_hex(cpp_flash_blob1[flash_index]);
        SBUF = '\n';
    }
    print_text(passed ? "CPP_FULL_FLASH_PASS\n" : "CPP_FULL_FLASH_FAIL\n");
    for (;;) {}
}
