#ifndef STC_CORE_DUMMY_VARIABLE_MAIN_H
#define STC_CORE_DUMMY_VARIABLE_MAIN_H

/*
 * The Arduino wrapper force-includes this header when compiling a merged
 * sketch. Keeping a reference in that translation unit makes the linker pull
 * main.c from the core archive.
 */
int main(void);
static int (* const stc_core_main_reference)(void) = main;

#endif
