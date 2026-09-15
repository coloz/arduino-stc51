#if defined(STCXX_CPP_CORE) && STCXX_CPP_CORE
#if !defined(__SDCC_mcs251)
# error "The STC C++ native runtime requires SDCC MCS251"
#endif


#include <stddef.h>
#include <stdlib.h>
#include <string.h>


#if !defined(__SDCC_STACK_AUTO)
# error "the C++ libc ABI wrappers require SDCC --stack-auto"
#endif

/* MCS251 uses the same flat 24-bit representation for generic/XDATA pointers. */
typedef char stcxx_generic_pointer_must_be_24_bit[(sizeof(void *) == 3) ? 1 : -1];
typedef char stcxx_xdata_pointer_must_be_24_bit[(sizeof(void __xdata *) == 3) ? 1 : -1];

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

/* Preserve the public C signature and normalize the native byte argument. */
void *__stcxx_libc_memset(void *memory, int value, size_t size)
{
  return memset(memory, (unsigned char)value, size);
}

/* C requires strchr/strrchr to convert the search value to unsigned char. */
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
