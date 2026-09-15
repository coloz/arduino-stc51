/* Execute the actual C serial APIs and ISR against byte-sized host SFRs.
 * This models register values and receive queues, not UART electrical timing. */
#include <stdio.h>
#include <stdlib.h>
#include "Arduino.h"
#include "HardwareSerial_private.h"
#include "stc_sfr.h"

uint8_t __stc_digital_input_pins[12];
static unsigned int checks;
#define CHECK(condition) do { \
    ++checks; \
    if (!(condition)) { fprintf(stderr, "FAIL serial line %d: %s\n", __LINE__, #condition); exit(1); } \
} while (0)

#if STC_CORE_HAS_UART1 && STC_CORE_SERIAL_BUFFERED_RX
extern void stc_uart1_isr(void);
#endif

static void empty(void)
{
    uint8_t value = 0xa5u;
    CHECK(Serial_available() == 0);
    CHECK(Serial_peek() == -1);
    CHECK(Serial_read() == -1);
    CHECK(Serial_readBytes(&value, 1u) == 0u && value == 0xa5u);
    CHECK(Serial_readBytes(NULL, 1u) == 0u);
}

#if STC_CORE_HAS_UART1
static void receive(uint8_t value)
{
    SBUF = value;
    SCON |= STC_SCON_RI;
# if STC_CORE_SERIAL_BUFFERED_RX
    stc_uart1_isr();
# endif
}
#endif

int main(void)
{
    unsigned int round;
    (void)round;
    empty();
    CHECK(!Serial_overflow());
    Serial_begin(38400UL);
#if !STC_CORE_HAS_UART1
    empty();
    CHECK(Serial_availableForWrite() == 0);
    CHECK(Serial_write(9u) == 0u);
    Serial_flush();
    Serial_end();
    empty();
#else
    CHECK(stc_uart1_started == 1u);
    CHECK(Serial_availableForWrite() == 1);
    empty();
# if STC_CORE_SERIAL_BUFFERED_RX
    for (round = 0u; round < 3u; ++round) {
        uint8_t buffer[SERIAL_RX_BUFFER_SIZE + 1u];
        unsigned int i;
        const unsigned int capacity = SERIAL_RX_BUFFER_SIZE - 1u;
        for (i = 0u; i < sizeof(buffer); ++i) buffer[i] = 0xa5u;
        for (i = 0u; i < capacity; ++i) receive((uint8_t)(i * 37u + 19u));
        CHECK(Serial_available() == (int)capacity);
        CHECK(Serial_peek() == 19 && Serial_peek() == 19);
        CHECK(Serial_readBytes(NULL, capacity) == 0u);
        CHECK(Serial_readBytes(buffer, 0u) == 0u);
        CHECK(Serial_available() == (int)capacity);
        receive(0xeeu);
        CHECK(Serial_available() == (int)capacity);
        IE = round == 1u ? 0x12u : 0x92u;
        {
            uint8_t saved = IE;
            CHECK(Serial_overflow());
            CHECK(IE == saved);
            CHECK(!Serial_overflow());
            CHECK(IE == saved);
        }
        CHECK(Serial_readBytes(buffer, capacity + 1u) == capacity);
        for (i = 0u; i < capacity; ++i) CHECK(buffer[i] == (uint8_t)(i * 37u + 19u));
        CHECK(buffer[capacity] == 0xa5u && buffer[capacity + 1u] == 0xa5u);
        empty();
    }
    /* Exercise one-byte transfers across every ring index, with RX and TX
     * flags set together to check that servicing TI does not drop RX. */
    for (round = 0u; round < SERIAL_RX_BUFFER_SIZE * 2u + 3u; ++round) {
        stc_uart1_tx_complete = 0u;
        SCON |= STC_SCON_TI;
        receive((uint8_t)round);
        CHECK(stc_uart1_tx_complete == 1u);
        CHECK((SCON & (STC_SCON_RI | STC_SCON_TI)) == 0u);
        CHECK(Serial_available() == 1 && Serial_peek() == (int)(uint8_t)round);
        CHECK(Serial_read() == (int)(uint8_t)round);
        CHECK(Serial_available() == 0);
    }
# else
    /* A peeked byte and a later hardware byte must preserve their order. */
    receive(0x23u);
    CHECK(Serial_peek() == 0x23 && Serial_peek() == 0x23);
    CHECK((SCON & STC_SCON_RI) == 0u);
    receive(0xb7u);
    CHECK(Serial_available() == 1 && Serial_peek() == 0x23);
    CHECK(Serial_read() == 0x23);
    CHECK(Serial_read() == 0xb7);
    empty();
    receive(0xe1u);
    {
        uint8_t buffer[2] = {0xa5u, 0x5au};
        CHECK(Serial_readBytes(buffer, 0u) == 0u);
        CHECK(Serial_readBytes(NULL, 1u) == 0u);
        CHECK(Serial_readBytes(buffer, 2u) == 1u);
        CHECK(buffer[0] == 0xe1u && buffer[1] == 0x5au);
    }
    CHECK(!Serial_overflow());
# endif
    receive(0x91u);
    CHECK(Serial_peek() == 0x91);
    Serial_end();
    CHECK(stc_uart1_started == 0u);
    empty();
    Serial_end();
    Serial_begin(38400UL);
    empty();  /* No stale queue or polling lookahead may survive restart. */
    receive(0x4eu);
    CHECK(Serial_peek() == 0x4e && Serial_read() == 0x4e);
    empty();
    Serial_begin(38400UL); /* Reconfigure an already started port. */
    empty();
    Serial_end();
#endif
    printf("PASS serial receive: uart=%u buffered=%u size=%u checks=%u\n",
           (unsigned)STC_CORE_HAS_UART1, (unsigned)STC_CORE_SERIAL_BUFFERED_RX,
           (unsigned)SERIAL_RX_BUFFER_SIZE, checks);
    return 0;
}
