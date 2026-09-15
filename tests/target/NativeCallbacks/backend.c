#include "callbacks.h"
static ResultCallback saved;
static unsigned short native_scalar(unsigned short n) { return n ^ 0x5a5a; }
static void native_result(CallbackPair *out, unsigned short n) {
    out->first = n;
    out->second = n + 1;
}
unsigned short native_invoke_scalar(ScalarCallback callback, unsigned short n) { return callback(n); }
void native_invoke_result(ResultCallback callback, CallbackPair *out, unsigned short n) { callback(out, n); }
ScalarCallback native_scalar_factory(void) { return native_scalar; }
ResultCallback native_result_factory(void) { return native_result; }
void native_save_result(ResultCallback callback) { saved = callback; }
void native_apply_saved(CallbackPair *out, unsigned short n) { saved(out, n); }
