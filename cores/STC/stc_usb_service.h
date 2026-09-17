/* SPDX-License-Identifier: MIT */
#ifndef STC_USB_SERVICE_H
#define STC_USB_SERVICE_H
#include "Arduino.h"
/* Installed by USB.begin(). Serviced from loop()/delay()/Stream waits. */
extern void (*stc_usb_service)(void) STC_REENTRANT;
#endif
