#if defined(STCXX_CPP_CORE) && STCXX_CPP_CORE

#include <stddef.h>
#include <stdlib.h>
#include <string.h>

#if !defined(__SDCC_mcs51) && !defined(__SDCC_mcs251)
# error "stcxx_libc_abi.c requires the SDCC MCS51 or MCS251 target"
#endif

#if !defined(__SDCC_STACK_AUTO)
# error "the C++ libc ABI wrappers require SDCC --stack-auto"
#endif

/*
 * These assertions describe the ABI boundary, rather than merely documenting
 * it.  Classic MCS51 returns malloc-family values as two-byte __xdata
 * pointers, but Clang-generated C++ expects a three-byte generic pointer.
 * MCS251 uses a flat three-byte representation for both pointer classes.
 */
typedef char stcxx_generic_pointer_must_be_24_bit[(sizeof(void *) == 3) ? 1 : -1];
#if defined(__SDCC_mcs51)
typedef char stcxx_xdata_pointer_must_be_16_bit[(sizeof(void __xdata *) == 2) ? 1 : -1];
#else
typedef char stcxx_xdata_pointer_must_be_24_bit[(sizeof(void __xdata *) == 3) ? 1 : -1];
#endif

void *__stcxx_libc_malloc(size_t size)
{
  void __xdata *pointer = malloc(size);
  return pointer;
}

void *__stcxx_libc_calloc(size_t count, size_t size)
{
  void __xdata *pointer = calloc(count, size);
  return pointer;
}

void *__stcxx_libc_realloc(void *memory, size_t size)
{
  void __xdata *pointer = realloc(memory, size);
  return pointer;
}

/* Classic MCS51's native memset takes a byte, not the standard int.  Keep
 * Clang callers on the standard signature and let SDCC marshal the native
 * argument width; otherwise the extra byte shifts the following size_t. */
void *__stcxx_libc_memset(void *memory, int value, size_t size)
{
  return memset(memory, (unsigned char)value, size);
}

/* C requires strchr/strrchr to convert value to unsigned char.  SDCC's
 * classic MCS51 library exposes a char boundary instead of int, so perform
 * that conversion in an SDCC-compiled translation unit. */
char *__stcxx_libc_strchr(const char *text, int value)
{
  unsigned char byte = (unsigned char)value;
  return strchr(text, byte);
}

char *__stcxx_libc_strrchr(const char *text, int value)
{
  unsigned char byte = (unsigned char)value;
  return strrchr(text, byte);
}

#endif
