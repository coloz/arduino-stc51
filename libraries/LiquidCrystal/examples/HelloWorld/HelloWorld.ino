/* SPDX-License-Identifier: MIT */

#include <Arduino.h>
#include <LiquidCrystal.h>

/* These logical pins exist on all platform models. Check the actual package
 * pinout before wiring, connect R/W to ground, and avoid sharing P3.2/P3.5
 * with Wire/SPI/INT0 while using this example. */
#define LCD_RS P1_3
#define LCD_EN P1_4
#define LCD_D4 P1_5
#define LCD_D5 P1_6
#define LCD_D6 P3_5
#define LCD_D7 P3_2

#if defined(__cplusplus) && defined(STCXX_CPP_CORE) && STCXX_CPP_CORE
LiquidCrystal lcd(LCD_RS, LCD_EN, LCD_D4, LCD_D5, LCD_D6, LCD_D7);
#endif

void setup(void)
{
#if defined(__cplusplus) && defined(STCXX_CPP_CORE) && STCXX_CPP_CORE
    lcd.begin(16u, 2u);
    if (lcd) {
        lcd.print("hello, world!");
        lcd.setCursor(0u, 1u);
        lcd.print("arduino-stc51");
    }
#else
    if (LiquidCrystal.setPins(LCD_RS, LCD_EN, LCD_D4, LCD_D5,
                              LCD_D6, LCD_D7) == LIQUIDCRYSTAL_OK) {
        if (LiquidCrystal.begin(16u, 2u) == LIQUIDCRYSTAL_OK) {
            LiquidCrystal.print("hello, world!");
            LiquidCrystal.setCursor(0u, 1u);
            LiquidCrystal.print("arduino-stc51");
        }
    }
#endif
}

void loop(void)
{
}
