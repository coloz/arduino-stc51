#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "stc_usb.h"
#include "stc_usb_cdc.h"
#include "USB_backend.h"

static uint8_t regs[4][32], index_reg, events;
static uint8_t incoming[4][256], outgoing[4][256], sent[4][4096];
static unsigned incoming_pos[4], outgoing_len[4], sent_len[4], sends[4], last_size[4];
static unsigned long now;
static int attached, rebooted;
uint8_t usb_hw_fault;
void (*stc_usb_service)(void);
uint8_t stc_usb_active, stc_usb_uart1_active;
unsigned long millis(void) { return now; }
uint8_t usb_hw_start(void) { return 1; }
void usb_hw_stop(void) { attached = 0; }
void usb_hw_attach(void) { attached = 1; }
void usb_hw_reboot(void) { ++rebooted; }
static void transmit(uint8_t ep) {
    unsigned length = outgoing_len[ep];
    assert(sent_len[ep] + length < sizeof(sent[ep]));
    memcpy(sent[ep] + sent_len[ep], outgoing[ep], length);
    sent_len[ep] += length; last_size[ep] = length; ++sends[ep]; outgoing_len[ep] = 0;
}
uint8_t usb_hw_read(uint8_t reg) {
    if (reg >= 32) return incoming[reg - 32][incoming_pos[reg - 32]++];
    if (reg == 6) { uint8_t value = events; events = 0; return value; }
    if (reg == 2 || reg == 4) return 0;
    return regs[index_reg][reg];
}
void usb_hw_write(uint8_t reg, uint8_t value) {
    if (reg == 14) { assert(value < 4); index_reg = value; return; }
    if (reg >= 32) { uint8_t ep = reg - 32; assert(outgoing_len[ep] < 256); outgoing[ep][outgoing_len[ep]++] = value; return; }
    if (reg == 17 && !index_reg) {
        if (value & 0x80) regs[0][17] &= (uint8_t)~16u;
        if (value & 0x40) regs[0][17] &= (uint8_t)~1u;
        if (value & 0x20) regs[0][17] = 4;
        if (value & 2) { transmit(0); regs[0][17] |= 2; }
        if (!value) regs[0][17] = 0;
        return;
    }
    if (reg == 17 && index_reg) {
        if (value == 1) { transmit(index_reg); regs[index_reg][17] = 1; }
        else { regs[index_reg][17] = 0; outgoing_len[index_reg] = 0; }
        return;
    }
    if (reg == 20 && index_reg) { regs[index_reg][20] = 0; return; }
    regs[index_reg][reg] = value;
}
static void ack(uint8_t ep) { regs[ep][17] &= (uint8_t)~(ep ? 1u : 2u); }
static void receive(uint8_t ep, const uint8_t *data, uint8_t count) {
    memcpy(incoming[ep], data, count); incoming_pos[ep] = 0;
    regs[ep][22] = count; regs[ep][ep ? 20 : 17] |= 1;
}
static void host_setup(uint8_t type, uint8_t request, uint16_t value, uint16_t iface, uint16_t length) {
    uint8_t data[] = {type,request,value & 255,value >> 8,iface & 255,iface >> 8,length & 255,length >> 8};
    ack(0); regs[0][17] = 16; sent_len[0] = sends[0] = 0;
    receive(0, data, 8); stc_usb_poll();
}
static void configure(void) { host_setup(0, 9, 1, 0, 0); assert(stc_usb_configured()); }
static void open_port(void) { host_setup(0x21, 0x22, 3, 0, 0); assert(stc_cdc_connected()); }
static void set_baud(uint32_t baud) {
    uint8_t data[] = {baud & 255,(baud >> 8) & 255,(baud >> 16) & 255,(baud >> 24) & 255,0,0,8};
    host_setup(0x21, 0x20, 0, 0, 7); receive(0, data, 7); stc_usb_poll();
    assert(stc_cdc_baud() == baud);
}
static void check_descriptor(int cdc, int hid) {
    unsigned offset, interfaces = 0, endpoints = 0;
    host_setup(0x80,6,0x0100,0,18); assert(sent_len[0] == 18); assert(sent[0][4] == (cdc ? 0xef : 0));
    assert(sent[0][10] == (cdc ? (hid ? 3 : 2) : 1));
    host_setup(0x80,6,0x0200,0,255);
    while (regs[0][17] & 2) { ack(0); stc_usb_poll(); }
    assert(sent_len[0] == (unsigned)(9 + cdc * 66 + hid * 32));
    assert(sent[0][2] == sent_len[0] && sent[0][4] == cdc * 2 + hid);
    for (offset = 9; offset < sent_len[0]; offset += sent[0][offset]) {
        assert(sent[0][offset] >= 2);
        if (sent[0][offset+1] == 4) { assert(sent[0][offset+2] == interfaces); ++interfaces; }
        if (sent[0][offset+1] == 5) ++endpoints;
    }
    assert(offset == sent_len[0] && interfaces == (unsigned)(cdc * 2 + hid));
    assert(endpoints == (unsigned)(cdc * 3 + hid * 2));
}
int main(int argc, char **argv) {
    int cdc = argc < 2 || strcmp(argv[1], "hid") != 0;
    int hid = argc > 1;
    uint8_t packet[200], output[64];
    unsigned i, before;
    if (hid) {
        const uint8_t descriptor[] = {0x85,1,0x75,8,0x95,4,0x81,2};
        assert(stc_usb_append(descriptor, sizeof(descriptor)));
        assert(stc_usb_register_report(1,4));
        assert(stc_usb_register_report(2,8));
    }
    stc_usb_uart1_active = 1;
    if (cdc) assert(stc_cdc_register());
    assert(!stc_usb_begin() && stc_usb_error() == STC_USB_BUSY);
    stc_usb_uart1_active = 0;
    if (cdc) assert(stc_cdc_begin()); else assert(stc_usb_begin());
    assert(attached); check_descriptor(cdc,hid);
    host_setup(0xa1,0x21,0,0,7); assert(regs[0][17] & 4); // unconfigured class request
    configure();
    if (hid) {
        unsigned iface = cdc ? 2 : 0;
        host_setup(0x81,6,0x2200,iface,255); assert(sent_len[0] == 8);
        packet[0]=1; packet[1]=5; packet[2]=6; packet[3]=7;
        assert(stc_usb_send(1,packet,4) == 5);
        host_setup(0xa1,1,0x0101,iface,5);
        assert(sent_len[0] == 5 && sent[0][1] == 1 && sent[0][2] == 0); // relative axes cleared
        host_setup(0x21,9,0x0202,iface,2); packet[0]=2; packet[1]=3; receive(0,packet,2); stc_usb_poll();
        assert(stc_usb_keyboard_leds() == 3);
        packet[0]=3; packet[1]=0x55; receive(1,packet,2); stc_usb_poll();
        assert(stc_usb_receive(output,64) == 2 && output[1] == 0x55);
        assert(!stc_usb_append(packet,2));
        ack(1);
    }
    if (!cdc) { puts("HID regression: PASS"); return 0; }
    assert(!stc_cdc_connected()); open_port();
    host_setup(0xa1,0x21,0,0,7); assert(sent_len[0] == 7 && sent[0][6] == 8);
    host_setup(0xa1,0x21,0,0x100,7); assert(regs[0][17] & 4); // full interface index
    set_baud(9600); assert(stc_cdc_line_format(6) == 8);
    host_setup(0x21,0x20,0,0,7); // invalid data bits must stall, preserving valid settings
    memset(packet,0,7); packet[6]=9; receive(0,packet,7); stc_usb_poll();
    assert((regs[0][17]&4) && stc_cdc_baud()==9600);
    host_setup(0,9,0x100,0,0); assert(regs[0][17]&4); // reject truncated 16-bit values
    host_setup(0x21,0x20,0,0,8); assert(regs[0][17]&4); // wrong control payload length
    // An abandoned OUT control stage must not consume the next SETUP packet.
    host_setup(0x21,0x20,0,0,7); host_setup(0xa1,0x21,0,0,7);
    assert(sent_len[0]==7 && sent[0][0]==0x80 && sent[0][1]==0x25);
    host_setup(0x21,0x23,100,0,0); assert(stc_cdc_read_break() == 100 && stc_cdc_read_break() == -1);
    for (i=0; i<64; ++i) packet[i]=(uint8_t)i;
    receive(2,packet,64); stc_usb_poll(); receive(2,packet,64); stc_usb_poll();
    assert(stc_cdc_available() == 128 && stc_cdc_peek() == 0 && stc_cdc_peek() == 0);
    receive(2,packet,64); stc_usb_poll(); assert(regs[2][20] & 1); // RX ring backpressure
    for (i=0; i<192; ++i) assert(stc_cdc_read() == (int)(i%64));
    assert(stc_cdc_read() == -1);
    receive(2,packet,0); stc_usb_poll(); assert(!(regs[2][20]&1));
    // Hold the IN endpoint busy to test queue capacity, short writes, and a stalled clock.
    regs[2][17]=1; memset(packet,0xa5,sizeof(packet));
    assert(stc_cdc_write(packet,200,0) == 128);
    assert(stc_cdc_write_space() == 0 && !stc_cdc_flush(0));
    ack(2); stc_usb_poll(); assert(last_size[2] == 64);
    ack(2); stc_usb_poll(); assert(last_size[2] == 64);
    ack(2); stc_usb_poll(); assert(last_size[2] == 0); // exact packet multiple ZLP
    ack(2); assert(stc_cdc_flush(0));
    assert(sent_len[2] == 128); for(i=0;i<128;++i) assert(sent[2][i] == 0xa5);
    events=1; stc_usb_poll(); assert(!stc_cdc_connected());
    events=2; stc_usb_poll(); assert(stc_cdc_connected());
    host_setup(2,3,0,0x82,0); before=sends[2]; assert(stc_cdc_write(packet,8,0) == 8); stc_usb_poll(); assert(sends[2]==before);
    host_setup(2,1,0,0x82,0); stc_usb_poll(); assert(sends[2] > before); ack(2);
    events=4; stc_usb_poll(); assert(!stc_cdc_connected() && !stc_cdc_available());
    configure(); open_port(); set_baud(1200);
    host_setup(0x21,0x22,0,0,0); now+=119; stc_usb_poll(); assert(!rebooted);
    open_port(); now+=2; stc_usb_poll(); assert(!rebooted); // transient close cancels reset
    stc_cdc_enable_reboot(0); host_setup(0x21,0x22,0,0,0); now+=200; stc_usb_poll(); assert(!rebooted);
    stc_cdc_enable_reboot(1); open_port(); host_setup(0x21,0x22,0,0,0);
    now+=120; stc_usb_poll(); assert(rebooted==1 && !attached);
    assert(stc_cdc_begin()); configure(); open_port(); stc_cdc_end();
    assert(!stc_cdc_connected() && stc_usb_configured());
    assert(stc_cdc_begin() && stc_cdc_connected());
    puts(hid ? "CDC + HID composite: PASS" : "CDC device protocol: PASS");
    return 0;
}
