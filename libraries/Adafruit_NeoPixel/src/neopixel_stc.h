#ifndef STC_NEOPIXEL_BACKEND_H
#define STC_NEOPIXEL_BACKEND_H
#include <stdint.h>

#if !defined(STC32G144K246) || (F_CPU != 12000000UL && F_CPU != 48000000UL)
# error "The STC NeoPixel backend currently requires STC32G144K246 at 12 or 48 MHz"
#endif

#ifdef __cplusplus
extern "C" {
#endif
/* 800 kHz only, valid GPIOs P0..P7. pixels[count] must be allocated (sentinel). */
uint8_t stc_neopixel_supported(int16_t pin, uint8_t is800);
uint8_t stc_neopixel_show(const uint8_t *pixels, uint16_t count, int16_t pin, uint8_t is800);
#ifdef __cplusplus
}
#endif
#endif
