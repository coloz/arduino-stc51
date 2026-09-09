// Freestanding C++ fixture for the real LLVM-CBE/SDCC bridge, without Arduino
// discovery or library packaging. The runtime supplies main and UART output.
extern "C" {
extern volatile unsigned char full_flash_cpp_result;
void full_flash_cpp_panic(void);
unsigned short __stcxx_bridge_ctor_count(void);
void __stcxx_bridge_invoke_ctor(unsigned short index);
}

static volatile unsigned char constructor_seen;

class FullFlashProbe {
    unsigned char seed;
public:
    FullFlashProbe() : seed(0x21) { ++constructor_seen; }
    virtual unsigned char virtual_value(unsigned char value) {
        return seed + value;
    }
    unsigned char direct(unsigned char value) { return seed ^ value; }
};

static FullFlashProbe global_probe;
typedef unsigned char (FullFlashProbe::*MemberOperation)(unsigned char);

__attribute__((noinline))
static unsigned char call_virtual(FullFlashProbe *probe, unsigned char value) {
    return probe->virtual_value(value);
}

__attribute__((noinline))
static unsigned char call_member(FullFlashProbe *probe,
                                 MemberOperation operation,
                                 unsigned char value) {
    return (probe->*operation)(value);
}

extern "C" void __stcxx_abi_stc_arduino_cxx_v1_mcs251_be_size4_pdiff4_ptr3_fnptr3_guard1_direct(void) {}

extern "C" void stcxx_runtime_panic(unsigned char) {
    full_flash_cpp_panic();
    for (;;) {}
}

extern "C" void __stcxx_run_global_ctors(void) {
    unsigned short count = __stcxx_bridge_ctor_count();
    for (unsigned short index = 0; index < count; ++index)
        __stcxx_bridge_invoke_ctor(index);
}

extern "C" void setup(void) {
    unsigned char passed = constructor_seen == 1 ? 1 : 0;
    passed |= call_virtual(&global_probe, 3) == 0x24 ? 2 : 0;
    passed |= call_member(&global_probe, &FullFlashProbe::direct, 0x12) == 0x33 ? 4 : 0;
    passed |= call_member(&global_probe, &FullFlashProbe::virtual_value, 5) == 0x26 ? 8 : 0;
    full_flash_cpp_result = passed;
}

extern "C" void loop(void) {}
