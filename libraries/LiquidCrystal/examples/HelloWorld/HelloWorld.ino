/* SPDX-License-Identifier: MIT */

#include <Arduino.h>
#include <LiquidCrystal.h>

/* Connect R/W to ground.  Change these pins to match the target board. */
#define LCD_RS P1_0
#define LCD_EN P1_1
#define LCD_D4 P1_2
#define LCD_D5 P1_3
#define LCD_D6 P1_4
#define LCD_D7 P1_5

void setup(void)
{
    if (LiquidCrystal.setPins(LCD_RS, LCD_EN, LCD_D4, LCD_D5,
                              LCD_D6, LCD_D7) == LIQUIDCRYSTAL_OK) {
        if (LiquidCrystal.begin(16u, 2u) == LIQUIDCRYSTAL_OK) {
            LiquidCrystal.print("hello, world!");
            LiquidCrystal.setCursor(0u, 1u);
            LiquidCrystal.print("arduino-stc51");
        }
    }
}

void loop(void)
{
}
