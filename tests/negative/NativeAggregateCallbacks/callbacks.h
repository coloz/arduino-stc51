#ifndef STCXX_BAD_CALLBACK_FIXTURE_H
#define STCXX_BAD_CALLBACK_FIXTURE_H
typedef struct NativePair { unsigned short first, second; } NativePair;
typedef NativePair (*NativePairMaker)(unsigned short);
typedef unsigned short (*NativePairDispatcher)(NativePairMaker);
#ifdef __cplusplus
extern "C" {
#endif
unsigned short native_use_pair(NativePairMaker callback);
NativePairMaker native_pair_factory(void);
unsigned short native_use_table(NativePairMaker *table);
unsigned short native_use_dispatcher(NativePairDispatcher callback);
#ifdef __cplusplus
}
#endif
#endif
