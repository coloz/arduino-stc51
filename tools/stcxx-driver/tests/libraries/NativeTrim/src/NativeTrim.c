#include "NativeTrim.h"
const uint8_t nativeFont[3] = { 1, 2, 3 };
const uint8_t unusedFont[20000] = { 99 };
static uint16_t sharedCounter;
static uint16_t helper(void) { return ++sharedCounter; }
static uint16_t (*callback)(void) = helper;
uint16_t nativeValue(void) { return callback() + nativeFont[0]; }
uint16_t unusedFunction(void) {
  static volatile uint8_t unusedBuffer[18000];
  unusedBuffer[0]++;
  return unusedBuffer[0];
}
