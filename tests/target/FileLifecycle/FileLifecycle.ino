#include <Arduino.h>
#include "SDClass.h"

// build-file-lifecycle.ps1 copies the production File implementation unchanged.
// The C backend here is a deterministic fault model, not a card driver.
extern "C" void testFailClose(uint8_t fail);
static unsigned failures;
static unsigned checks;
static void check(bool condition) {
  ++checks;
  if (!condition) { ++failures; Serial.print("FAIL "); Serial.println(checks); }
}
static void runChecks() {
  File stale = SD.open("OLD.TXT", FILE_WRITE);
  check(bool(stale));
  bool good = true;
  for (unsigned long i = 0; i < 65536UL; ++i) {
    File fresh = SD.open("NEW.TXT", FILE_WRITE);
    if (!fresh || stale || stale.read() != -1) { good = false; break; }
  }
  check(good);
  File file = SD.open("NEW.TXT", FILE_WRITE);
  stale.close();
  check(bool(file));
  File copy = file;
  File moved(static_cast<File &&>(copy));
  check(!copy && moved && file);
  file.close();
  check(moved && moved.write(uint8_t(42)) == 1);
  testFailClose(1);
  moved.close();
  check(moved && moved.getWriteError() == SD_ERROR_WRITE_REJECTED);
  File refused = SD.open("OTHER.TXT", FILE_WRITE);
  check(!refused && moved);
  testFailClose(0);
  moved.clearWriteError();
  moved.close();
  check(!moved);
  file = SD.open("NEW.TXT");
  check(file && file.read() == 42);
}
void setup() {
  Serial.begin(38400);
  Serial.println("BEGIN file-lifecycle");
  runChecks();
  Serial.print("CHECKS "); Serial.println(checks);
  Serial.println(failures ? "FAIL file-lifecycle" : "PASS file-lifecycle");
}
void loop() {}
