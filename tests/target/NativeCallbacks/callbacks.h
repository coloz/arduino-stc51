#ifndef STCXX_NATIVE_CALLBACK_FIXTURE_H
#define STCXX_NATIVE_CALLBACK_FIXTURE_H
typedef struct CallbackPair { unsigned short first, second; } CallbackPair;
typedef unsigned short (*ScalarCallback)(unsigned short);
typedef void (*ResultCallback)(CallbackPair *, unsigned short);
#ifdef __cplusplus
extern "C" {
#endif
unsigned short native_invoke_scalar(ScalarCallback callback, unsigned short n);
void native_invoke_result(ResultCallback callback, CallbackPair *out, unsigned short n);
ScalarCallback native_scalar_factory(void);
ResultCallback native_result_factory(void);
void native_save_result(ResultCallback callback);
void native_apply_saved(CallbackPair *out, unsigned short n);
#ifdef __cplusplus
}
#endif
#endif
