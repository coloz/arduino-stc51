#include <Arduino.h>

volatile unsigned result;
struct Base { virtual unsigned value() const = 0; virtual ~Base() {} };
struct Counter : Base {
  unsigned count;
  Counter() : count(7) {}
  unsigned value() const override { return count; }
  unsigned add(unsigned n) { return count += n; }
};
Counter globalCounter;
unsigned invoke(Base &base) { return base.value(); }
void setup() {
  Serial.begin(115200);
  unsigned (Counter::*member)(unsigned) = &Counter::add;
  result = (globalCounter.*member)(3) + invoke(globalCounter);
  String message("native");
  message += String(result);
  Serial.println(message);
  Serial.println(1.25f, 3);
  Counter *allocated = new Counter;
  result += allocated->value();
  delete allocated;
}
void loop() {
  static Counter local;
  result = local.add(1);
}
