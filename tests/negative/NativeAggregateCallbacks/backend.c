#include "callbacks.h"
static NativePair native_pair(unsigned short n) {
    NativePair pair;
    pair.first = n;
    pair.second = n + 1;
    return pair;
}
unsigned short native_use_pair(NativePairMaker callback) {
    NativePair pair = callback(41);
    return pair.first + pair.second;
}
NativePairMaker native_pair_factory(void) { return native_pair; }
unsigned short native_use_table(NativePairMaker *table) { return native_use_pair(table[0]); }
unsigned short native_use_dispatcher(NativePairDispatcher callback) { return callback(native_pair); }
