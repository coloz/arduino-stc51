#include <U8x8lib.h>
U8X8_SSD1306_128X64_NONAME_SW_I2C display(2, 3, U8X8_PIN_NONE);
void setup() {
  display.begin();
  display.setFont(u8x8_font_chroma48medium8_r);
  display.drawString(0, 0, "Native STC");
}
void loop() {}
