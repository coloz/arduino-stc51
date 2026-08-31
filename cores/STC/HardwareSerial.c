#include "Arduino.h"
#include "stc_sfr.h"

#ifndef STC_CORE_SERIAL_BUFFERED_RX
# define STC_CORE_SERIAL_BUFFERED_RX 1
#endif

#if (STC_CORE_SERIAL_BUFFERED_RX != 0) && \
    (STC_CORE_SERIAL_BUFFERED_RX != 1)
# error "STC_CORE_SERIAL_BUFFERED_RX must be 0 or 1"
#endif

#ifndef SERIAL_RX_BUFFER_SIZE
# ifdef SERIAL_BUFFER_SIZE
#  define SERIAL_RX_BUFFER_SIZE SERIAL_BUFFER_SIZE
# else
#  define SERIAL_RX_BUFFER_SIZE 16u
# endif
#endif

#if STC_CORE_SERIAL_BUFFERED_RX && \
    ((SERIAL_RX_BUFFER_SIZE < 2) || (SERIAL_RX_BUFFER_SIZE > 255))
# error "SERIAL_RX_BUFFER_SIZE must be between 2 and 255 bytes"
#endif

/*
 * STC89 parts can be configured by the ISP for a non-default machine-cycle
 * rate. Boards use the documented 12T default; installations selecting a
 * different mode can override this compile-time divider.
 */
#ifndef STC_SERIAL_TIMER1_CLOCK_DIVIDER
# if STC_CORE_TIMER1_IS_1T
#  define STC_SERIAL_TIMER1_CLOCK_DIVIDER 1UL
# else
#  define STC_SERIAL_TIMER1_CLOCK_DIVIDER 12UL
# endif
#endif

#if (STC_SERIAL_TIMER1_CLOCK_DIVIDER != 1UL) && \
    (STC_SERIAL_TIMER1_CLOCK_DIVIDER != 6UL) && \
    (STC_SERIAL_TIMER1_CLOCK_DIVIDER != 12UL)
# error "STC_SERIAL_TIMER1_CLOCK_DIVIDER must be 1, 6, or 12"
#endif

#define STC_SERIAL_T1_CLOCK_OUTPUT 0x02u
#define STC_SERIAL_UART1_ROUTE     0xc0u
#define STC_SERIAL_TF1             0x80u

#if STC_CORE_HAS_UART1

/* INTCLKO/WAKE_CLKO is common at 0x8f from STC12 onward. */
# if !defined(STC_CORE_FAMILY_89)
__sfr __at (0x8f) STC_SERIAL_INTCLKO;
# endif

static volatile uint8_t serial_started;

# if STC_CORE_SERIAL_BUFFERED_RX

#  if defined(STC_XDATA_BYTES) && (STC_XDATA_BYTES > 0)
static __xdata uint8_t serial_rx_buffer[SERIAL_RX_BUFFER_SIZE];
#  else
static uint8_t serial_rx_buffer[SERIAL_RX_BUFFER_SIZE];
#  endif
static volatile uint8_t serial_rx_head;
static volatile uint8_t serial_rx_tail;
static volatile uint8_t serial_rx_overflow;
static volatile uint8_t serial_tx_complete = 1u;

/* Timer1 and UART1 routing state temporarily owned by buffered Serial. */
static uint8_t serial_saved_tmod;
static uint8_t serial_saved_th1;
static uint8_t serial_saved_tl1;
static uint8_t serial_saved_tr1;
static uint8_t serial_saved_tf1;
static uint8_t serial_saved_et1;
#  if !defined(STC_CORE_FAMILY_89)
static uint8_t serial_saved_auxr;
static uint8_t serial_saved_intclko;
#  endif
#  if STC_CORE_HAS_MODERN_UART1_BRT
static uint8_t serial_saved_p_sw1;
#  else
static uint8_t serial_saved_smod;
#  endif

static uint8_t stc_serial_rounded_divisor(unsigned long clock,
                                          unsigned long denominator,
                                          unsigned long *result) __reentrant
{
    unsigned long divisor;
    unsigned long remainder;
    unsigned long round_threshold;

    if (denominator == 0UL) {
        return 0u;
    }

    divisor = clock / denominator;
    remainder = clock % denominator;
    round_threshold = (denominator / 2UL) + (denominator & 1UL);
    if (remainder >= round_threshold) {
        ++divisor;
    }
    *result = divisor;
    return 1u;
}

static uint8_t stc_serial_baud_error_is_acceptable(unsigned long clock,
                                                    unsigned long denominator,
                                                    unsigned long divisor) __reentrant
{
    unsigned long generated_ticks = denominator * divisor;
    unsigned long difference;
    unsigned long allowed;

    if (clock >= generated_ticks) {
        difference = clock - generated_ticks;
    } else {
        difference = generated_ticks - clock;
    }

    /* Reject configurations whose baud error exceeds three percent. */
    allowed = (generated_ticks / 100UL) * 3UL;
    allowed += (((generated_ticks % 100UL) * 3UL) + 99UL) / 100UL;
    return (difference <= allowed) ? 1u : 0u;
}

static uint8_t stc_serial_calculate_reload(unsigned long baud,
                                           uint16_t *reload,
                                           uint8_t *double_baud) __reentrant
{
    unsigned long denominator;
    unsigned long divisor;

    if (baud == 0UL) {
        return 0u;
    }

#  if STC_CORE_HAS_MODERN_UART1_BRT
    /* Official STC SDK formula: baud = F_CPU / (4 * Timer1 period). */
    if (baud > (0xffffffffUL / 4UL)) {
        return 0u;
    }
    denominator = baud * 4UL;
    if (stc_serial_rounded_divisor((unsigned long)F_CPU,
                                   denominator, &divisor) == 0u) {
        return 0u;
    }
    if ((divisor == 0UL) || (divisor >= 65536UL) ||
        (stc_serial_baud_error_is_acceptable((unsigned long)F_CPU,
                                             denominator, divisor) == 0u)) {
        return 0u;
    }
    *reload = (uint16_t)(65536UL - divisor);
    *double_baud = 0u;
#  else
    unsigned long timer_clock = (unsigned long)F_CPU /
                                STC_SERIAL_TIMER1_CLOCK_DIVIDER;

    /* Prefer SMOD=1 for the finer classic 8-bit reload resolution. */
    if (baud <= (0xffffffffUL / 16UL)) {
        denominator = baud * 16UL;
        (void)stc_serial_rounded_divisor(timer_clock, denominator, &divisor);
        if ((divisor != 0UL) && (divisor <= 256UL) &&
            (stc_serial_baud_error_is_acceptable(timer_clock, denominator,
                                                 divisor) != 0u)) {
            *reload = (uint16_t)(256UL - divisor);
            *double_baud = 1u;
            return 1u;
        }
    }

    if (baud > (0xffffffffUL / 32UL)) {
        return 0u;
    }
    denominator = baud * 32UL;
    (void)stc_serial_rounded_divisor(timer_clock, denominator, &divisor);
    if ((divisor == 0UL) || (divisor > 256UL) ||
        (stc_serial_baud_error_is_acceptable(timer_clock, denominator,
                                             divisor) == 0u)) {
        return 0u;
    }
    *reload = (uint16_t)(256UL - divisor);
    *double_baud = 0u;
#  endif
    return 1u;
}

static void stc_serial_reset_rx(void)
{
    serial_rx_head = 0u;
    serial_rx_tail = 0u;
    serial_rx_overflow = 0u;
}

static void stc_serial_wait_for_tx(void)
{
    while (serial_tx_complete == 0u) {
        /* Also service TI by polling so writes work with EA disabled. */
        if ((SCON & STC_SCON_TI) != 0u) {
            SCON &= (uint8_t)~STC_SCON_TI;
            serial_tx_complete = 1u;
        }
    }
}

void stc_uart1_isr(void) __interrupt (4)
{
    uint8_t status = SCON;

    if ((status & STC_SCON_RI) != 0u) {
        uint8_t value = SBUF;
        uint8_t next;

        SCON &= (uint8_t)~STC_SCON_RI;
        if (serial_started != 0u) {
            next = (uint8_t)(serial_rx_head + 1u);
            if (next >= (uint8_t)SERIAL_RX_BUFFER_SIZE) {
                next = 0u;
            }
            if (next == serial_rx_tail) {
                serial_rx_overflow = 1u;
            } else {
                serial_rx_buffer[serial_rx_head] = value;
                serial_rx_head = next;
            }
        }
    }

    if ((status & STC_SCON_TI) != 0u) {
        SCON &= (uint8_t)~STC_SCON_TI;
        serial_tx_complete = 1u;
    }
}

# else /* compact polling RX */

static uint8_t serial_peek_valid;
static uint8_t serial_peek_value;

/*
 * The <=2 KiB profile accepts the common rates below. Every reload expression
 * is a compile-time constant, avoiding the 32-bit divide runtime that would
 * otherwise consume a material fraction of a 2 KiB device.
 */
#  if STC_CORE_HAS_MODERN_UART1_BRT
#   define STC_SERIAL_COMPACT_DIVISOR(rate) \
        (((unsigned long)F_CPU + ((unsigned long)(rate) * 2UL)) / \
         ((unsigned long)(rate) * 4UL))
#   define STC_SERIAL_COMPACT_GENERATED(rate) \
        ((unsigned long)(rate) * 4UL * STC_SERIAL_COMPACT_DIVISOR(rate))
#   define STC_SERIAL_COMPACT_TOLERANCE(generated)                    \
        ((((generated) / 100UL) * 3UL) +                              \
         (((((generated) % 100UL) * 3UL) + 99UL) / 100UL))
#   define STC_SERIAL_COMPACT_ERROR_OK(generated)                     \
        (((unsigned long)F_CPU >= (generated))                        \
             ? (((unsigned long)F_CPU - (generated)) <=               \
                STC_SERIAL_COMPACT_TOLERANCE(generated))              \
             : (((generated) - (unsigned long)F_CPU) <=               \
                STC_SERIAL_COMPACT_TOLERANCE(generated)))
#   define STC_SERIAL_COMPACT_CASE(rate)                              \
        case (rate):                                                  \
            divisor = STC_SERIAL_COMPACT_DIVISOR(rate);               \
            if (!STC_SERIAL_COMPACT_ERROR_OK(                         \
                    STC_SERIAL_COMPACT_GENERATED(rate))) {            \
                return 0u;                                            \
            }                                                         \
            break
#  else
#   define STC_SERIAL_COMPACT_CLOCK \
        ((unsigned long)F_CPU / STC_SERIAL_TIMER1_CLOCK_DIVIDER)
#   define STC_SERIAL_COMPACT_DIVISOR_2X(rate) \
        ((STC_SERIAL_COMPACT_CLOCK + ((unsigned long)(rate) * 8UL)) / \
         ((unsigned long)(rate) * 16UL))
#   define STC_SERIAL_COMPACT_DIVISOR_1X(rate) \
        ((STC_SERIAL_COMPACT_CLOCK + ((unsigned long)(rate) * 16UL)) / \
         ((unsigned long)(rate) * 32UL))
#   define STC_SERIAL_COMPACT_GENERATED_2X(rate) \
        ((unsigned long)(rate) * 16UL * \
         STC_SERIAL_COMPACT_DIVISOR_2X(rate))
#   define STC_SERIAL_COMPACT_GENERATED_1X(rate) \
        ((unsigned long)(rate) * 32UL * \
         STC_SERIAL_COMPACT_DIVISOR_1X(rate))
#   define STC_SERIAL_COMPACT_TOLERANCE(generated)                    \
        ((((generated) / 100UL) * 3UL) +                              \
         (((((generated) % 100UL) * 3UL) + 99UL) / 100UL))
#   define STC_SERIAL_COMPACT_ERROR_OK(generated)                     \
        ((STC_SERIAL_COMPACT_CLOCK >= (generated))                    \
             ? ((STC_SERIAL_COMPACT_CLOCK - (generated)) <=          \
                STC_SERIAL_COMPACT_TOLERANCE(generated))              \
             : (((generated) - STC_SERIAL_COMPACT_CLOCK) <=          \
                STC_SERIAL_COMPACT_TOLERANCE(generated)))
#   define STC_SERIAL_COMPACT_CASE(rate)                         \
        case (rate):                                             \
            divisor = STC_SERIAL_COMPACT_DIVISOR_2X(rate);       \
            if (divisor <= 256UL) {                              \
                *double_baud = 1u;                               \
                if (!STC_SERIAL_COMPACT_ERROR_OK(                \
                        STC_SERIAL_COMPACT_GENERATED_2X(rate))) { \
                    return 0u;                                   \
                }                                                \
            } else {                                             \
                divisor = STC_SERIAL_COMPACT_DIVISOR_1X(rate);   \
                *double_baud = 0u;                               \
                if (!STC_SERIAL_COMPACT_ERROR_OK(                \
                        STC_SERIAL_COMPACT_GENERATED_1X(rate))) { \
                    return 0u;                                   \
                }                                                \
            }                                                    \
            break
#  endif

static uint8_t stc_serial_calculate_reload(unsigned long baud,
                                           uint16_t *reload,
                                           uint8_t *double_baud) __reentrant
{
    unsigned long divisor;

    switch (baud) {
    STC_SERIAL_COMPACT_CASE(4800UL);
    STC_SERIAL_COMPACT_CASE(9600UL);
    STC_SERIAL_COMPACT_CASE(19200UL);
    STC_SERIAL_COMPACT_CASE(38400UL);
    STC_SERIAL_COMPACT_CASE(57600UL);
    STC_SERIAL_COMPACT_CASE(115200UL);
    default:
        return 0u;
    }

#  if STC_CORE_HAS_MODERN_UART1_BRT
    *double_baud = 0u;
    if ((divisor == 0UL) || (divisor >= 65536UL)) {
        return 0u;
    }
    *reload = (uint16_t)(65536UL - divisor);
#  else
    if ((divisor == 0UL) || (divisor > 256UL)) {
        return 0u;
    }
    *reload = (uint16_t)(256UL - divisor);
#  endif
    return 1u;
}

#  undef STC_SERIAL_COMPACT_CASE
#  if STC_CORE_HAS_MODERN_UART1_BRT
#   undef STC_SERIAL_COMPACT_ERROR_OK
#   undef STC_SERIAL_COMPACT_TOLERANCE
#   undef STC_SERIAL_COMPACT_GENERATED
#   undef STC_SERIAL_COMPACT_DIVISOR
#  else
#   undef STC_SERIAL_COMPACT_ERROR_OK
#   undef STC_SERIAL_COMPACT_TOLERANCE
#   undef STC_SERIAL_COMPACT_GENERATED_1X
#   undef STC_SERIAL_COMPACT_GENERATED_2X
#   undef STC_SERIAL_COMPACT_DIVISOR_1X
#   undef STC_SERIAL_COMPACT_DIVISOR_2X
#   undef STC_SERIAL_COMPACT_CLOCK
#  endif

# endif /* STC_CORE_SERIAL_BUFFERED_RX */
#endif /* STC_CORE_HAS_UART1 */

void Serial_begin(unsigned long baud)
{
#if STC_CORE_HAS_UART1
    uint16_t reload;
    uint8_t double_baud;

    if (stc_serial_calculate_reload(baud, &reload, &double_baud) == 0u) {
        return;
    }

    if (serial_started != 0u) {
        Serial_end();
    }

# if STC_CORE_SERIAL_BUFFERED_RX
    serial_saved_tmod = TMOD;
    serial_saved_th1 = TH1;
    serial_saved_tl1 = TL1;
    serial_saved_tr1 = (uint8_t)(TCON & STC_TCON_TR1);
    serial_saved_tf1 = (uint8_t)(TCON & STC_SERIAL_TF1);
    serial_saved_et1 = (uint8_t)(IE & STC_IE_ET1);
#  if !defined(STC_CORE_FAMILY_89)
    serial_saved_auxr = AUXR;
    serial_saved_intclko = STC_SERIAL_INTCLKO;
#  endif
#  if STC_CORE_HAS_MODERN_UART1_BRT
    serial_saved_p_sw1 = P_SW1;
#  else
    serial_saved_smod = (uint8_t)(PCON & STC_PCON_SMOD);
#  endif
# endif

    IE &= (uint8_t)~STC_IE_ES;
    TCON &= (uint8_t)~(STC_TCON_TR1 | STC_SERIAL_TF1);
    IE &= (uint8_t)~STC_IE_ET1;

# if !defined(STC_CORE_FAMILY_89)
    /* Select Timer1 rather than Timer2 and disable Timer1 clock output. */
    AUXR &= (uint8_t)~STC_AUXR_S1_BRT_T2;
#  if STC_CORE_TIMER1_IS_1T
    AUXR |= STC_AUXR_T1_1T;
#  else
    AUXR &= (uint8_t)~STC_AUXR_T1_1T;
#  endif
    STC_SERIAL_INTCLKO &= (uint8_t)~STC_SERIAL_T1_CLOCK_OUTPUT;
# endif

# if STC_CORE_HAS_MODERN_UART1_BRT
    /* A2 is P_SW1 only on STC15 and newer. Do not emit this access for
     * STC12, where A2 is AUXR1 and bits 7:6 control unrelated hardware. */
    P_SW1 &= (uint8_t)~STC_SERIAL_UART1_ROUTE;
    TMOD &= 0x0fu;             /* Timer1, 16-bit auto reload, not gated. */
    TH1 = (uint8_t)(reload >> 8);
    TL1 = (uint8_t)reload;
# else
    TMOD = (uint8_t)((TMOD & 0x0fu) | 0x20u); /* Classic 8-bit auto reload. */
    if (double_baud != 0u) {
        PCON |= STC_PCON_SMOD;
    } else {
        PCON &= (uint8_t)~STC_PCON_SMOD;
    }
    TH1 = (uint8_t)reload;
    TL1 = (uint8_t)reload;
# endif

# if STC_CORE_SERIAL_BUFFERED_RX
    pinMode(STC_PIN(3u, 0u), INPUT_PULLUP);
    pinMode(STC_PIN(3u, 1u), OUTPUT);
    stc_serial_reset_rx();
    serial_tx_complete = 1u;
# else
    /* Compact profile: avoid pulling the complete digital-I/O translation
     * unit into a 2 KiB image. RXD is quasi-input, TXD is push-pull. */
    P3 |= 0x03u;
#  if STC_CORE_HAS_PORT_MODE
    P3M1 &= (uint8_t)~0x03u;
    P3M0 = (uint8_t)((P3M0 & (uint8_t)~0x03u) | 0x02u);
#  endif
    serial_peek_valid = 0u;
# endif
    SCON = STC_SCON_MODE1 | STC_SCON_REN;
    serial_started = 1u;
# if STC_CORE_SERIAL_BUFFERED_RX
    IE |= STC_IE_ES;
# endif
    TCON |= STC_TCON_TR1;
#else
    (void)baud;
#endif
}

void Serial_end(void)
{
#if STC_CORE_HAS_UART1
    if (serial_started == 0u) {
        return;
    }

# if STC_CORE_SERIAL_BUFFERED_RX
    stc_serial_wait_for_tx();
# endif
    IE &= (uint8_t)~STC_IE_ES;
    TCON &= (uint8_t)~(STC_TCON_TR1 | STC_SERIAL_TF1);
    SCON &= (uint8_t)~(STC_SCON_REN | STC_SCON_RI | STC_SCON_TI);
    serial_started = 0u;

# if STC_CORE_SERIAL_BUFFERED_RX
    stc_serial_reset_rx();
    serial_tx_complete = 1u;

    TMOD = (uint8_t)((TMOD & 0x0fu) | (serial_saved_tmod & 0xf0u));
    TH1 = serial_saved_th1;
    TL1 = serial_saved_tl1;
#  if !defined(STC_CORE_FAMILY_89)
    AUXR = (uint8_t)((AUXR &
                      (uint8_t)~(STC_AUXR_T1_1T | STC_AUXR_S1_BRT_T2)) |
                     (serial_saved_auxr &
                      (STC_AUXR_T1_1T | STC_AUXR_S1_BRT_T2)));
    STC_SERIAL_INTCLKO =
        (uint8_t)((STC_SERIAL_INTCLKO &
                   (uint8_t)~STC_SERIAL_T1_CLOCK_OUTPUT) |
                  (serial_saved_intclko & STC_SERIAL_T1_CLOCK_OUTPUT));
#  endif
#  if STC_CORE_HAS_MODERN_UART1_BRT
    P_SW1 = (uint8_t)((P_SW1 & (uint8_t)~STC_SERIAL_UART1_ROUTE) |
                      (serial_saved_p_sw1 & STC_SERIAL_UART1_ROUTE));
#  else
    PCON = (uint8_t)((PCON & (uint8_t)~STC_PCON_SMOD) |
                     serial_saved_smod);
#  endif
    IE = (uint8_t)((IE & (uint8_t)~STC_IE_ET1) | serial_saved_et1);
    TCON = (uint8_t)((TCON &
                      (uint8_t)~(STC_TCON_TR1 | STC_SERIAL_TF1)) |
                     serial_saved_tr1 | serial_saved_tf1);
# else
    serial_peek_valid = 0u;
# endif
#endif
}

int Serial_available(void)
{
#if STC_CORE_HAS_UART1
    if (serial_started == 0u) {
        return 0;
    }
# if STC_CORE_SERIAL_BUFFERED_RX
    {
        uint8_t head = serial_rx_head;
        uint8_t tail = serial_rx_tail;

        if (head >= tail) {
            return (int)(head - tail);
        }
        return (int)((uint8_t)SERIAL_RX_BUFFER_SIZE - tail + head);
    }
# else
    if (serial_peek_valid != 0u) {
        return 1;
    }
    if ((SCON & STC_SCON_RI) != 0u) {
        serial_peek_value = SBUF;
        SCON &= (uint8_t)~STC_SCON_RI;
        serial_peek_valid = 1u;
        return 1;
    }
    return 0;
# endif
#else
    return 0;
#endif
}

int Serial_availableForWrite(void)
{
#if STC_CORE_HAS_UART1
# if STC_CORE_SERIAL_BUFFERED_RX
    return ((serial_started != 0u) && (serial_tx_complete != 0u)) ? 1 : 0;
# else
    return (serial_started != 0u) ? 1 : 0;
# endif
#else
    return 0;
#endif
}

int Serial_peek(void)
{
#if STC_CORE_HAS_UART1
# if STC_CORE_SERIAL_BUFFERED_RX
    if ((serial_started == 0u) || (serial_rx_head == serial_rx_tail)) {
        return -1;
    }
    return (int)serial_rx_buffer[serial_rx_tail];
# else
    if (Serial_available() == 0) {
        return -1;
    }
    return (int)serial_peek_value;
# endif
#else
    return -1;
#endif
}

int Serial_read(void)
{
#if STC_CORE_HAS_UART1
# if STC_CORE_SERIAL_BUFFERED_RX
    uint8_t tail;
    uint8_t value;

    if ((serial_started == 0u) || (serial_rx_head == serial_rx_tail)) {
        return -1;
    }
    tail = serial_rx_tail;
    value = serial_rx_buffer[tail];
    ++tail;
    if (tail >= (uint8_t)SERIAL_RX_BUFFER_SIZE) {
        tail = 0u;
    }
    serial_rx_tail = tail;
    return (int)value;
# else
    if (serial_started == 0u) {
        return -1;
    }
    if (serial_peek_valid != 0u) {
        serial_peek_valid = 0u;
        return (int)serial_peek_value;
    }
    if ((SCON & STC_SCON_RI) != 0u) {
        uint8_t value = SBUF;

        SCON &= (uint8_t)~STC_SCON_RI;
        return (int)value;
    }
    return -1;
# endif
#else
    return -1;
#endif
}

size_t Serial_readBytes(void *buffer, size_t length) __reentrant
{
    uint8_t *destination = (uint8_t *)buffer;
    size_t count = 0u;
    int value;

    if (destination == (uint8_t *)0) {
        return 0u;
    }
    while (count < length) {
        value = Serial_read();
        if (value < 0) {
            break;
        }
        destination[count++] = (uint8_t)value;
    }
    return count;
}

size_t Serial_write(uint8_t value)
{
#if STC_CORE_HAS_UART1
    if (serial_started == 0u) {
        return 0u;
    }
# if STC_CORE_SERIAL_BUFFERED_RX
    stc_serial_wait_for_tx();
    serial_tx_complete = 0u;
    SCON &= (uint8_t)~STC_SCON_TI;
    SBUF = value;
    stc_serial_wait_for_tx();
# else
    SCON &= (uint8_t)~STC_SCON_TI;
    SBUF = value;
    while ((SCON & STC_SCON_TI) == 0u) {
    }
    SCON &= (uint8_t)~STC_SCON_TI;
# endif
    return 1u;
#else
    (void)value;
    return 0u;
#endif
}

void Serial_flush(void)
{
#if STC_CORE_HAS_UART1 && STC_CORE_SERIAL_BUFFERED_RX
    if (serial_started != 0u) {
        stc_serial_wait_for_tx();
    }
#endif
}

bool Serial_overflow(void)
{
#if STC_CORE_HAS_UART1 && STC_CORE_SERIAL_BUFFERED_RX
    uint8_t saved_ea = (uint8_t)(IE & STC_IE_EA);
    uint8_t result;

    IE &= (uint8_t)~STC_IE_EA;
    result = serial_rx_overflow;
    serial_rx_overflow = 0u;
    if (saved_ea != 0u) {
        IE |= STC_IE_EA;
    }
    return (result != 0u);
#else
    return false;
#endif
}
