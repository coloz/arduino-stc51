/* Test-only queue fixture: seed three bytes across the real RX ring boundary.
 * This tests the native API/storage boundary, not UART wire reception. */
#include <Arduino.h>
#include "HardwareSerial_private.h"
#include "stc_sfr.h"
#if !defined(__SDCC_mcs251) || !STC_CORE_SERIAL_BUFFERED_RX
#error This fixture requires the native buffered MCS251 core
#endif
typedef char ring_must_hold_three_bytes[SERIAL_RX_BUFFER_SIZE >= 4u ? 1 : -1];

uint8_t serial_test_seed_wrapped(void)
{
    uint8_t saved_ea = (uint8_t)(IE & STC_IE_EA);
    if (stc_uart1_started == 0u) return 0u;
    IE &= (uint8_t)~STC_IE_EA;
    stc_uart1_rx_buffer[SERIAL_RX_BUFFER_SIZE - 2u] = 0x31u;
    stc_uart1_rx_buffer[SERIAL_RX_BUFFER_SIZE - 1u] = 0x82u;
    stc_uart1_rx_buffer[0] = 0xe7u;
    stc_uart1_rx_tail = SERIAL_RX_BUFFER_SIZE - 2u;
    stc_uart1_rx_head = 1u;
    stc_uart1_rx_overflow = 1u;
    if (saved_ea != 0u) IE |= STC_IE_EA;
    return 1u;
}

uint8_t serial_test_interrupts_enabled(void)
{
    return (IE & STC_IE_EA) != 0u;
}
