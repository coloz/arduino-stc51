#include <Arduino.h>
#include <SD.h>

// No card is required. Target checks cover String, Stream, virtual dispatch
// and the SD File facade's invalid/copy/move paths. FAT I/O has a host model.
static unsigned failures;
static unsigned checks;
static void check(bool condition) {
  ++checks;
  if (!condition) { ++failures; Serial.print("FAIL "); Serial.println(checks); }
}
class TextInput : public Stream {
  const char *cursor;
public:
  TextInput(const char *text) : cursor(text) { setTimeout(0); }
  int available() { return *cursor != 0; }
  int peek() { return *cursor ? (uint8_t)*cursor : -1; }
  int read() { int c = peek(); if (c >= 0) ++cursor; return c; }
  void flush() {}
  size_t write(uint8_t) { return 1; }
};
static void stringChecks() {
  String text("abcabc-tail");
  text.replace(String("abc"), String("x"));
  check(text == "xx-tail");
  text.replace(String("x"), String("123"));
  check(text == "123123-tail");
  text.replace(String("123"), String(""));
  check(text == "-tail");
  text = text.c_str() + 1;
  check(text == "tail");
  check(text.concat(text.c_str() + 1) && text == "tailail");
  check(!text.reserve(65535u) && text == "tailail");
  TextInput minValue("-2147483648!");
  check(minValue.parseInt() == (-2147483647L - 1L) && minValue.read() == '!');
  TextInput overlap("ababababac!");
  check(overlap.find("ababac") && overlap.read() == '!');
}
static void fileChecks() {
  File empty;
  check(!empty && empty.read() == -1);
  File copy(empty);
  File moved(static_cast<File &&>(copy));
  check(!copy && !moved);
  empty = moved;
  empty.close();
  check(!empty && empty.available() == 0);
  check(empty.write(uint8_t(1)) == 0 && empty.getWriteError() != 0);
}
void setup() {
  Serial.begin(38400);
  Serial.println("BEGIN production-smoke");
  stringChecks();
  fileChecks();
  Serial.print("CHECKS "); Serial.println(checks);
  Serial.println(failures ? "FAIL production-smoke" : "PASS production-smoke");
}
void loop() {}
