#include <cassert>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <utility>
#include "SD.h"

// A complete FAT16 volume, with two FATs, two root sectors and 4094 clusters.
static unsigned char disk[66600][512];
static bool failWrite;
static unsigned writes;
extern "C" unsigned long millis() { static unsigned long tick; return tick++; }
extern "C" void delay(unsigned long) {}
extern "C" void yield() {}
extern "C" void digitalWrite(uint8_t, uint8_t) {}
extern "C" uint8_t digitalPinIsValid(uint8_t pin) { return pin < 0x80; }
extern "C" uint8_t digitalPinsSharePhysicalPad(uint8_t a, uint8_t b) { return a == b; }
extern "C" void SPI_begin() {}
extern "C" void SPI_end() {}
extern "C" uint8_t SPI_setPinsChecked(uint8_t, uint8_t, uint8_t, uint8_t) { return 0; }
extern "C" uint8_t SPI_beginTransactionChecked(unsigned long, uint8_t, uint8_t) { return 0; }
extern "C" void SPI_endTransaction() {}
extern "C" uint8_t SPI_transfer(uint8_t) { return 0xff; }
static bool failAllocation;
extern "C" void *stcxx_malloc(size_t n) { return failAllocation ? 0 : malloc(n); }
extern "C" void *stcxx_realloc(void *p, size_t n) { return realloc(p, n); }
extern "C" void stcxx_free(void *p) { free(p); }
extern "C" uint8_t STC_SD_testReadBlock(unsigned long sector, uint8_t *buffer) {
    if (sector >= 66600) return 0;
    memcpy(buffer, disk[sector], 512);
    return 1;
}
extern "C" uint8_t STC_SD_testWriteBlock(unsigned long sector, const uint8_t *buffer) {
    if (failWrite || sector >= 66600) return 0;
    memcpy(disk[sector], buffer, 512);
    ++writes;
    return 1;
}
static void le16(unsigned char *p, unsigned value) { p[0] = value; p[1] = value >> 8; }
static void le32(unsigned char *p, unsigned long value) {
    le16(p, value); le16(p + 2, value >> 16);
}
static void mount(bool fat32 = false) {
    SD.end();
    SD_testReset();
    memset(disk, 0, sizeof disk);
    disk[0][0] = 0xeb;
    le16(disk[0] + 11, 512);
    disk[0][13] = 1;
    le16(disk[0] + 14, 1);
    disk[0][16] = 2;
    le16(disk[0] + 17, 32);
    le16(disk[0] + 19, 4129);
    disk[0][21] = 0xf8;
    le16(disk[0] + 22, 16);
    disk[0][510] = 0x55; disk[0][511] = 0xaa;
    le16(disk[1], 0xfff8); le16(disk[1] + 2, 0xffff);
    memcpy(disk[17], disk[1], 512);
    if (fat32) {
        // 65527 data clusters, reserved=32, two FATs of 512 sectors, root=2.
        memset(disk[1], 0, 512); memset(disk[17], 0, 512);
        le16(disk[0] + 14, 32);
        le16(disk[0] + 17, 0);
        le16(disk[0] + 19, 0);
        le16(disk[0] + 22, 0);
        le32(disk[0] + 32, 66583);
        le32(disk[0] + 36, 512);
        le32(disk[0] + 44, 2);
        le32(disk[32], 0x0ffffff8);
        le32(disk[32] + 4, 0x0fffffff);
        le32(disk[32] + 8, 0x0fffffff);
        memcpy(disk[544], disk[32], 512);
    }
    failWrite = false;
    writes = 0;
    assert(SD_testMount());
}
static void roundtrip(bool fat32) {
    mount(fat32);
    unsigned char expected[1300], actual[1300];
    for (unsigned i = 0; i < sizeof expected; ++i) expected[i] = (i * 37u) ^ (i >> 8);
    File f = SD.open("TEST.BIN", FILE_WRITE);
    assert(f && f.write(expected, sizeof expected) == sizeof expected);
    f.flush();
    assert(f.getWriteError() == 0);
    f.close();
    assert(writes && (fat32 ? memcmp(disk[32], disk[544], 512 * 512) == 0
                           : memcmp(disk[1], disk[17], 16 * 512) == 0));
    assert(SD_testMount()); // Re-read committed metadata rather than cached state.
    f = SD.open("TEST.BIN");
    assert(f && f.size() == sizeof expected);
    assert(f.read(actual, sizeof actual) == sizeof actual);
    assert(memcmp(expected, actual, sizeof actual) == 0 && f.read() == -1);
    f.close();
    f = SD.open("TEST.BIN", FILE_WRITE);
    assert(f.position() == sizeof expected && f.write(uint8_t(0x5a)) == 1);
    assert(f.seek(511) && f.write(uint8_t(0x42)) == 1);
    f.close();
    f = SD.open("TEST.BIN");
    assert(f.size() == 1301 && f.seek(511) && f.read() == 0x42);
    assert(f.seek(1300) && f.read() == 0x5a);
    f.close();
    assert(SD.remove("TEST.BIN") && !SD.exists("TEST.BIN"));
    assert(!SD.mkdir("DIR") && SD.error() == SD_ERROR_UNSUPPORTED);
    puts(fat32 ? "PASS: FAT32 multi-cluster write, remount, append, overwrite, read and remove"
               : "PASS: FAT16 multi-cluster write, remount, append, overwrite, read and remove");
}
static void stale_handles() {
    mount();
    File old = SD.open("OLD.TXT", FILE_WRITE);
    assert(old);
    for (unsigned i = 0; i < 2; ++i) {
        File fresh = SD.open("NEW.TXT", FILE_WRITE);
        assert(fresh && !old);
        old.close(); // A stale close must never close the new backend.
        assert(fresh);
    }
    File stale = SD.open("OLD.TXT");
    for (unsigned i = 0; i < 65536; ++i) {
        File fresh = SD.open("NEW.TXT");
        assert(fresh && !stale && stale.read() == -1);
    }
    File f = SD.open("NEW.TXT", FILE_WRITE);
    failAllocation = true;
    File allocationFailure = SD.open("OOM.TXT", FILE_WRITE);
    failAllocation = false;
    assert(!allocationFailure && f && !SD.exists("OOM.TXT"));
    File copy = f;
    File moved = std::move(copy);
    assert(!copy && moved && f);
    f.close();
    assert(moved && moved.write(uint8_t(7)) == 1);
    moved.close();
    // The old 8-bit reference counter silently invalidated copy number 256.
    f = SD.open("NEW.TXT");
    File copies[300];
    for (unsigned i = 0; i < 300; ++i) { copies[i] = f; assert(copies[i]); }
    f.close();
    for (unsigned i = 0; i < 300; ++i) { assert(copies[i]); copies[i].close(); }
    puts("PASS: stale handles across 65536 opens, copy/move and last-owner close");
}
static void close_failure() {
    mount();
    File f = SD.open("RETRY.TXT", FILE_WRITE);
    assert(f && f.write(uint8_t(42)) == 1);
    failWrite = true;
    f.close();
    assert(f && f.getWriteError() == SD_ERROR_WRITE_REJECTED);
    // A failed reopen must leave the original handle available for retry.
    File other = SD.open("OTHER.TXT", FILE_WRITE);
    assert(!other && f);
    failWrite = false;
    f.clearWriteError();
    f.flush();
    assert(f.getWriteError() == 0);
    f.close();
    assert(!f);
    f = SD.open("RETRY.TXT");
    assert(f && f.size() == 1 && f.read() == 42);
    puts("PASS: failed close/reopen preserves data and permits explicit retry");
}
int main(int argc, char **argv) {
    assert(argc == 2);
    if (!strcmp(argv[1], "roundtrip")) roundtrip(false);
    else if (!strcmp(argv[1], "fat32")) roundtrip(true);
    else if (!strcmp(argv[1], "handles")) stale_handles();
    else if (!strcmp(argv[1], "failure")) close_failure();
    else return 2;
}
