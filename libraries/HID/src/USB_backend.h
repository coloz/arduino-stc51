/* SPDX-License-Identifier: MIT */
#ifndef STC_USB_BACKEND_H
#define STC_USB_BACKEND_H
#include <Arduino.h>
#define STC_USB_OK 0
#define STC_USB_UNSUPPORTED 1
#define STC_USB_INVALID 2
#define STC_USB_NOT_CONFIGURED 3
#define STC_USB_TIMEOUT 4
#define STC_USB_DESCRIPTOR_FULL 5
#define STC_USB_BUSY 6
#define STC_USB_REPORT_IDS 16u
#define STC_USB_PACKET_SIZE 64u
#ifdef __cplusplus
extern "C" {
#endif
uint8_t stc_usb_append(const uint8_t *data, uint16_t size) STC_REENTRANT;
uint8_t stc_usb_begin(void) STC_REENTRANT;
void stc_usb_end(void) STC_REENTRANT;
void stc_usb_poll(void) STC_REENTRANT;
uint8_t stc_usb_configured(void) STC_REENTRANT;
uint8_t stc_usb_error(void) STC_REENTRANT;
int stc_usb_send(uint8_t id, const uint8_t *data, uint8_t size) STC_REENTRANT;
int stc_usb_receive(uint8_t *data, uint8_t size) STC_REENTRANT;
uint8_t stc_usb_available(void) STC_REENTRANT;
uint8_t stc_usb_register_report(uint8_t id, uint8_t size) STC_REENTRANT;
uint8_t stc_usb_keyboard_leds(void) STC_REENTRANT;
#ifdef __cplusplus
}
#endif
#endif
