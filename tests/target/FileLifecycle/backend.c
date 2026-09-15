#include <Arduino.h>
static uint8_t opened, failure, error, value;
void testFailClose(uint8_t fail) { failure = fail; }
uint8_t SD_error(void) { return error; }
void SD_close(void) {
    if (opened && failure) { error = 8u; return; }
    opened = 0; error = 0;
}
uint8_t SD_open(const char *name, uint8_t mode) {
    (void)name; (void)mode;
    SD_close(); if (error) return 0;
    opened = 1; return 1;
}
int SD_read(void) { return opened ? value : -1; }
int SD_peek(void) { return SD_read(); }
size_t SD_readBytes(uint8_t *buffer, size_t length) {
    if (!opened || !length) return 0;
    *buffer = value; return 1;
}
size_t SD_writeBytes(const uint8_t *buffer, size_t length) {
    if (!opened || !length) return 0;
    value = *buffer; return 1;
}
uint8_t SD_flush(void) { error = failure ? 8u : 0u; return !error; }
unsigned long SD_available(void) { return opened ? 1UL : 0UL; }
unsigned long SD_position(void) { return 0UL; }
unsigned long SD_size(void) { return 1UL; }
uint8_t SD_seek(unsigned long position) { return position == 0; }
uint8_t SD_begin(uint8_t select) { (void)select; return 1; }
uint8_t SD_beginDefault(void) { return 1; }
uint8_t SD_beginClock(unsigned long clock, uint8_t select) { (void)clock; (void)select; return 1; }
void SD_end(void) { SD_close(); }
uint8_t SD_setPins(uint8_t a, uint8_t b, uint8_t c, uint8_t d) {
    (void)a; (void)b; (void)c; (void)d; SD_close(); return !error;
}
uint8_t SD_exists(const char *name) { (void)name; return 1; }
uint8_t SD_remove(const char *name) { (void)name; SD_close(); return !error; }
uint8_t SD_mkdir(const char *name) { (void)name; error = 20; return 0; }
uint8_t SD_rmdir(const char *name) { return SD_mkdir(name); }
