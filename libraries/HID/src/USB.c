/* SPDX-License-Identifier: MIT
 * STC full-speed SIE, one HID interface, interrupt IN/OUT endpoint 1.
 * Setup fields and descriptors are serialized bytewise for the MCS251 ABI.
 */
#include "USB_backend.h"
#include <stc_usb_service.h>
#include "USBHardware.h"

#ifndef USB_VID
#define USB_VID 0x1209u
#endif
#ifndef USB_PID
#define USB_PID 0x0001u
#endif
#define DESCRIPTOR_CAPACITY 512u
static uint8_t error;
static uint8_t report_descriptor[DESCRIPTOR_CAPACITY];
static uint16_t descriptor_length;
static uint8_t started;
static uint8_t registered_size[STC_USB_REPORT_IDS];
static uint8_t keyboard_leds;

#if STC_CORE_USB_LAYOUT
static const uint8_t device_descriptor[] = {
    18,1,0x00,0x02,0,0,0,64,
    USB_VID & 255u,USB_VID >> 8,USB_PID & 255u,USB_PID >> 8,
    0x00,0x01,1,2,0,1
};
static uint8_t config_descriptor[] = {
    9,2,41,0,1,1,0,0x80,50,
    9,4,0,0,2,3,0,0,0,
    9,0x21,0x11,0x01,0,1,0x22,0,0,
    7,5,0x81,3,64,0,1,
    7,5,0x01,3,64,0,1
};
static const uint8_t language[] = {4,3,9,4};
static const uint8_t manufacturer[] = {22,3,'S',0,'T',0,'C',0,' ',0,'M',0,'C',0,'S',0,'2',0,'5',0,'1',0};
static const uint8_t product[] = {16,3,'S',0,'T',0,'C',0,' ',0,'H',0,'I',0,'D',0};
static uint8_t configuration, suspended, halted_in, halted_out, polling;
static uint8_t setup_data[8], reply[64], output[64], output_length;
static uint8_t last_report[STC_USB_REPORT_IDS][64], report_length[STC_USB_REPORT_IDS];
static uint8_t idle[STC_USB_REPORT_IDS], idle_cursor;
static unsigned long last_sent[STC_USB_REPORT_IDS];
static const uint8_t *control_data;
static uint16_t control_left, host_length;
static uint8_t control_state, control_zlp, output_expected, output_id;
/* control_state: 0=SETUP/status, 1=IN data, 2=SET_REPORT data. */

static void reset_endpoints(void)
{
    usb_hw_write(14, 1);
    usb_hw_write(16, 8); usb_hw_write(17, 0x48); usb_hw_write(18, 0x20);
    usb_hw_write(19, 8); usb_hw_write(20, 0x90); usb_hw_write(21, 0);
    usb_hw_write(14, 0);
    halted_in = halted_out = output_length = 0;
}
static void bus_reset(void)
{
    uint8_t i;
    usb_hw_write(0, 0); configuration = suspended = control_state = 0;
    reset_endpoints();
    memset(last_report, 0, sizeof(last_report)); keyboard_leds = 0;
    for (i = 0; i < STC_USB_REPORT_IDS; ++i) {
        idle[i] = 0; report_length[i] = registered_size[i]; last_report[i][0] = i;
    }
}
static void stall(void) { control_state = 0; usb_hw_write(17, 0x60); }
static void status(void) { control_state = 0; usb_hw_write(17, 0x48); }
static void control_in(void)
{
    uint8_t n, i;
    if (usb_hw_read(17) & 2u) return;
    n = control_left > 64u ? 64u : (uint8_t)control_left;
    for (i = 0; i < n; ++i) usb_hw_write(32, *control_data++);
    control_left -= n;
    if (!control_left && (!control_zlp || !n)) {
        usb_hw_write(17, 0x0a); control_state = 0;
    } else usb_hw_write(17, 2);
}
static void respond(const uint8_t *data, uint16_t length)
{
    control_data = data;
    control_zlp = length < host_length && (length % 64u) == 0u;
    control_left = length < host_length ? length : host_length;
    control_state = 1; usb_hw_write(17, 0x40); control_in();
}
static void request(void)
{
    uint8_t type = setup_data[0], req = setup_data[1], id = setup_data[2], kind = setup_data[3];
    uint16_t value = (uint16_t)setup_data[2] | ((uint16_t)setup_data[3] << 8);
    uint16_t index = (uint16_t)setup_data[4] | ((uint16_t)setup_data[5] << 8);
    uint8_t i;
    host_length = (uint16_t)setup_data[6] | ((uint16_t)setup_data[7] << 8);
    if (req == 6 && ((type == 0x80u && index == 0u) ||
        (type == 0x80u && kind == 3u && index == 0x0409u) ||
        (type == 0x81u && index == 0u))) {
        if (type == 0x80u && kind == 1u && id == 0u) { respond(device_descriptor, sizeof(device_descriptor)); return; }
        if (type == 0x80u && kind == 2u && id == 0u) { respond(config_descriptor, sizeof(config_descriptor)); return; }
        if (type == 0x80u && kind == 3u) {
            if (id == 0) { respond(language, sizeof(language)); return; }
            if (id == 1) { respond(manufacturer, sizeof(manufacturer)); return; }
            if (id == 2) { respond(product, sizeof(product)); return; }
        }
        if (type == 0x81u && id == 0u && kind == 0x21u) { respond(config_descriptor + 18, 9); return; }
        if (type == 0x81u && id == 0u && kind == 0x22u) { respond(report_descriptor, descriptor_length); return; }
    }
    if (type == 0 && req == 5 && value < 128u && !index && !host_length && !configuration) {
        /* SIE defers FADDR update until the status stage has completed. */
        usb_hw_write(0, (uint8_t)value); status(); return;
    }
    if (type == 0 && req == 9 && value <= 1u && !index && !host_length) {
        reset_endpoints(); configuration = (uint8_t)value; status(); return;
    }
    if (type == 0x80u && req == 8 && !value && !index && host_length == 1u) {
        reply[0] = configuration; respond(reply, 1); return;
    }
    if (req == 0 && !value && host_length == 2u) {
        reply[0] = reply[1] = 0;
        if (type == 0x80u && !index) { respond(reply, 2); return; }
        if (type == 0x81u && !index && configuration) { respond(reply, 2); return; }
        if (type == 0x82u && (index == 0 || index == 0x80u)) { respond(reply, 2); return; }
        if (type == 0x82u && configuration && (index == 1u || index == 0x81u)) {
            reply[0] = index == 1u ? halted_out : halted_in; respond(reply, 2); return;
        }
    }
    if (configuration && type == 2u && (req == 1u || req == 3u) && !value && !host_length && (index == 1u || index == 0x81u)) {
        usb_hw_write(14, 1);
        if (index == 0x81u) { halted_in = req == 3u; usb_hw_write(17, halted_in ? 0x10u : 0x48u); }
        else { halted_out = req == 3u; usb_hw_write(20, halted_out ? 0x20u : 0x90u); }
        usb_hw_write(14, 0); status(); return;
    }
    if (configuration && !index && !value && type == 0x81u && req == 10u && host_length == 1u) {
        reply[0] = 0; respond(reply, 1); return;
    }
    if (configuration && !index && !value && type == 1u && req == 11u && !host_length) { status(); return; }
    if (configuration && !index && (type == 0x21u || type == 0xa1u) && id < STC_USB_REPORT_IDS) {
        if (type == 0xa1u && req == 1u && kind == 1u && id && report_length[id]) {
            respond(last_report[id], report_length[id]); return;
        }
        if (type == 0xa1u && req == 2u && !kind && host_length == 1u) { reply[0] = idle[id]; respond(reply, 1); return; }
        if (type == 0x21u && req == 10u && !host_length) {
            if (!id) for (i = 0; i < STC_USB_REPORT_IDS; ++i) idle[i] = kind;
            else idle[id] = kind;
            status(); return;
        }
        if (type == 0x21u && req == 9u && kind == 2u && host_length && host_length <= 64u &&
            (id == 2u ? host_length == 2u : !output_length)) {
            output_id = id; output_expected = (uint8_t)host_length;
            control_state = 2; usb_hw_write(17, 0x40); return;
        }
        /* This interface declares report protocol only, never boot protocol. */
    }
    stall();
}
static void endpoint_zero(void)
{
    uint8_t csr, n, i;
    usb_hw_write(14, 0); csr = usb_hw_read(17);
    if (csr & 4u) { usb_hw_write(17, 0); control_state = 0; }
    if (csr & 16u) { usb_hw_write(17, 0x80); control_state = 0; }
    if (control_state == 1) { control_in(); return; }
    if (!(csr & 1u)) return;
    n = usb_hw_read(22);
    if (control_state == 2) {
        if (n != output_expected) { stall(); return; }
        for (i = 0; i < n; ++i) reply[i] = usb_hw_read(32);
        if (reply[0] != output_id) { stall(); return; }
        if (output_id == 2u) keyboard_leds = reply[1] & 31u;
        else { memcpy(output, reply, n); output_length = n; }
        status(); return;
    }
    if (!n) { usb_hw_write(17, 0x40); return; } /* OUT status stage */
    if (n != 8u) { stall(); return; }
    for (i = 0; i < 8; ++i) setup_data[i] = usb_hw_read(32);
    request();
}
static uint8_t tx_ready(void)
{
    usb_hw_write(14, 1);
    return !(usb_hw_read(17) & 1u) && !halted_in;
}
static void send_packet(const uint8_t *data, uint8_t length)
{
    uint8_t i;
    for (i = 0; i < length; ++i) usb_hw_write(33, data[i]);
    usb_hw_write(17, 1);
}
#endif

uint8_t stc_usb_append(const uint8_t *data, uint16_t size) STC_REENTRANT
{
    uint16_t i;
    if (started) { error = STC_USB_BUSY; return 0; }
    if (!data || !size) { error = STC_USB_INVALID; return 0; }
    if (size > DESCRIPTOR_CAPACITY - descriptor_length) { error = STC_USB_DESCRIPTOR_FULL; return 0; }
    for (i = 0; i < size; ++i) report_descriptor[descriptor_length++] = data[i];
    error = STC_USB_OK; return 1;
}
uint8_t stc_usb_begin(void) STC_REENTRANT
{
#if STC_CORE_USB_LAYOUT
    if (started) return 1;
    if (!descriptor_length) { error = STC_USB_INVALID; return 0; }
    if (!usb_hw_start()) { error = STC_USB_TIMEOUT; return 0; }
    config_descriptor[25] = (uint8_t)descriptor_length;
    config_descriptor[26] = (uint8_t)(descriptor_length >> 8);
    bus_reset();
    /* Enable SIE event latches; the CPU EUSB interrupt remains disabled. */
    usb_hw_write(7, 3); usb_hw_write(9, 2); usb_hw_write(11, 7);
    usb_hw_write(1, 1); /* Suspend detection enabled; CPU keeps running. */
    (void)usb_hw_read(6); (void)usb_hw_read(2); (void)usb_hw_read(4);
    started = 1; stc_usb_service = stc_usb_poll; usb_hw_attach(); error = STC_USB_OK; return 1;
#else
    error = STC_USB_UNSUPPORTED; return 0;
#endif
}
void stc_usb_end(void) STC_REENTRANT
{
    stc_usb_service = 0;
#if STC_CORE_USB_LAYOUT
    if (started) usb_hw_stop();
    configuration = output_length = control_state = 0;
#endif
    started = 0;
}
void stc_usb_poll(void) STC_REENTRANT
{
#if STC_CORE_USB_LAYOUT
    uint8_t events, n, i;
    unsigned long now;
    if (!started || polling) return;
    polling = 1;
    events = usb_hw_read(6);
    (void)usb_hw_read(2); (void)usb_hw_read(4);
    if (events & 4u) bus_reset();
    if (events & 1u) suspended = 1;
    if (events & 2u) suspended = 0;
    endpoint_zero();
    if (configuration && !suspended) {
        usb_hw_write(14, 1);
        if (!halted_out && !output_length && (usb_hw_read(20) & 1u)) {
            n = usb_hw_read(22);
            if (n <= 64u) {
                for (i = 0; i < n; ++i) output[i] = usb_hw_read(33);
                if (n == 2u && output[0] == 2u) keyboard_leds = output[1] & 31u;
                else output_length = n;
            }
            else { for (i = 0; i < n; ++i) (void)usb_hw_read(33); error = STC_USB_INVALID; }
            usb_hw_write(20, 0);
        }
        if (++idle_cursor >= STC_USB_REPORT_IDS) idle_cursor = 1;
        now = millis();
        if (idle[idle_cursor] && report_length[idle_cursor] &&
            now - last_sent[idle_cursor] >= (unsigned long)idle[idle_cursor] * 4UL && tx_ready()) {
            send_packet(last_report[idle_cursor], report_length[idle_cursor]); last_sent[idle_cursor] = now;
        }
    }
#if defined(__SDCC)
    if (usb_hw_fault) { error = STC_USB_TIMEOUT; stc_usb_end(); }
#endif
    polling = 0;
#endif
}
uint8_t stc_usb_configured(void) STC_REENTRANT
{
    stc_usb_poll();
#if STC_CORE_USB_LAYOUT
    return started && configuration && !suspended;
#else
    return 0;
#endif
}
uint8_t stc_usb_error(void) STC_REENTRANT { return error; }
uint8_t stc_usb_register_report(uint8_t id, uint8_t size) STC_REENTRANT
{
    if (started || !id || id >= STC_USB_REPORT_IDS || size > 63u) { error = STC_USB_INVALID; return 0; }
    registered_size[id] = size + 1u; return 1;
}
uint8_t stc_usb_keyboard_leds(void) STC_REENTRANT { stc_usb_poll(); return keyboard_leds; }
int stc_usb_send(uint8_t id, const uint8_t *data, uint8_t size) STC_REENTRANT
{
#if STC_CORE_USB_LAYOUT
    uint8_t i;
    uint16_t budget = 60000u;
    unsigned long start = millis();
    if (!id || id >= STC_USB_REPORT_IDS || size > 63u || (!data && size)) { error = STC_USB_INVALID; return -STC_USB_INVALID; }
    if (registered_size[id] && size + 1u != registered_size[id]) { error = STC_USB_INVALID; return -STC_USB_INVALID; }
    if (!stc_usb_configured()) { error = STC_USB_NOT_CONFIGURED; return -STC_USB_NOT_CONFIGURED; }
    while (!tx_ready()) {
        stc_usb_poll();
        if (!configuration || suspended) { error = STC_USB_NOT_CONFIGURED; return -STC_USB_NOT_CONFIGURED; }
        if (!--budget || millis() - start >= 100UL) { error = STC_USB_TIMEOUT; return -STC_USB_TIMEOUT; }
    }
    last_report[id][0] = id;
    for (i = 0; i < size; ++i) last_report[id][i + 1u] = data[i];
    report_length[id] = size + 1u;
    send_packet(last_report[id], size + 1u); last_sent[id] = millis();
    /* Mouse relative movement must never be repeated by GET_REPORT/idle. */
    if (id == 1 && size == 4) last_report[id][2] = last_report[id][3] = last_report[id][4] = 0;
    error = STC_USB_OK; return size + 1;
#else
    (void)id; (void)data; (void)size; error = STC_USB_UNSUPPORTED; return -STC_USB_UNSUPPORTED;
#endif
}
uint8_t stc_usb_available(void) STC_REENTRANT
{
    stc_usb_poll();
#if STC_CORE_USB_LAYOUT
    return output_length;
#else
    return 0;
#endif
}
int stc_usb_receive(uint8_t *data, uint8_t size) STC_REENTRANT
{
#if STC_CORE_USB_LAYOUT
    uint8_t i, n;
    stc_usb_poll(); n = output_length;
    if (!n) return 0;
    if (!data || size < n) { error = STC_USB_INVALID; return -STC_USB_INVALID; }
    for (i = 0; i < n; ++i) data[i] = output[i];
    output_length = 0; return n;
#else
    (void)data; (void)size; return 0;
#endif
}
