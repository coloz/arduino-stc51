/* Exercise the six libsdcc members whose native Mac and Linux code differs.
 * Struct-returning C functions remain inside C; only a scalar crosses to C++.
 * Checked arithmetic is called by its library entry to test the installed
 * archive, without header inlining replacing the implementation under test.
 */
#include <stdlib.h>
#include <inttypes.h>

extern _Bool __ckd_add_long(long *, signed long long, signed long long);
extern _Bool __ckd_sub_long(long *, signed long long, signed long long);

unsigned char native_runtime_arithmetic(void) {
    unsigned char failures = 0;
    div_t a;
    ldiv_t b;
    lldiv_t c;
    imaxdiv_t d;
    long result;
    a = div(32767, 2);
    if (a.quot != 16383 || a.rem != 1) failures |= 1;
    a = div(-13, -5);
    if (a.quot != 2 || a.rem != -3) failures |= 1;
    b = ldiv(2147483647L, 2L);
    if (b.quot != 1073741823L || b.rem != 1L) failures |= 2;
    b = ldiv(-2147483647L, 2L);
    if (b.quot != -1073741823L || b.rem != -1L) failures |= 2;
    c = lldiv(9223372036854775807LL, 2LL);
    if (c.quot != 4611686018427387903LL || c.rem != 1LL) failures |= 4;
    c = lldiv(-9223372036854775807LL, 2LL);
    if (c.quot != -4611686018427387903LL || c.rem != -1LL) failures |= 4;
    d = imaxdiv(9223372036854775807LL, -2LL);
    if (d.quot != -4611686018427387903LL || d.rem != 1LL) failures |= 8;
    d = imaxdiv(-13, -5);
    if (d.quot != 2 || d.rem != -3) failures |= 8;
    if (__ckd_add_long(&result, 2147483640LL, 7LL) || result != 2147483647L) failures |= 16;
    if (!__ckd_add_long(&result, 2147483647LL, 1LL)) failures |= 16;
    if (__ckd_add_long(&result, -2147483647LL, -1LL) || result != (-2147483647L - 1L)) failures |= 16;
    if (__ckd_sub_long(&result, -2147483647LL, 1LL) || result != (-2147483647L - 1L)) failures |= 32;
    if (!__ckd_sub_long(&result, -2147483648LL, 1LL)) failures |= 32;
    if (__ckd_sub_long(&result, 2147483646LL, -1LL) || result != 2147483647L) failures |= 32;
    return failures;
}
