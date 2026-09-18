/* Host-side model of the STC indexed USB registers. */
#include <stdint.h>
extern uint8_t usb_hw_fault;
uint8_t usb_hw_read(uint8_t reg);
void usb_hw_write(uint8_t reg, uint8_t value);
uint8_t usb_hw_start(void);
void usb_hw_stop(void);
void usb_hw_attach(void);
void usb_hw_reboot(void);
