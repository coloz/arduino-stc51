#include "Arduino.h"
#include "stc_sfr.h"

static void (*stc_external_callbacks[2])(void);

static uint8_t stc_interrupt_lock(void)
{
    uint8_t enabled = (uint8_t)(IE & STC_IE_EA);
    IE &= (uint8_t)~STC_IE_EA;
    return enabled;
}

static void stc_interrupt_unlock(uint8_t enabled)
{
    if (enabled != 0u) {
        IE |= STC_IE_EA;
    }
}

void attachInterrupt(uint8_t interrupt_number, void (*callback)(void),
                     int mode) STC_REENTRANT
{
    uint8_t interrupt_state;

    if ((interrupt_number > 1u) || (callback == 0)) {
        return;
    }

    /* The common INT0/INT1 hardware supports low-level and falling-edge
     * triggering.  CHANGE/RISING require family-specific GPIO interrupts and
     * are deliberately rejected instead of silently using the wrong edge. */
    if ((mode != LOW) && (mode != FALLING)) {
        return;
    }

    interrupt_state = stc_interrupt_lock();
    stc_external_callbacks[interrupt_number] = callback;

    if (interrupt_number == 0u) {
        if (mode == FALLING) {
            TCON |= STC_TCON_IT0;
        } else {
            TCON &= (uint8_t)~STC_TCON_IT0;
        }
        TCON &= (uint8_t)~STC_TCON_IE0;
        IE |= STC_IE_EX0;
    } else {
        if (mode == FALLING) {
            TCON |= STC_TCON_IT1;
        } else {
            TCON &= (uint8_t)~STC_TCON_IT1;
        }
        TCON &= (uint8_t)~STC_TCON_IE1;
        IE |= STC_IE_EX1;
    }

    stc_interrupt_unlock(interrupt_state);
}

void detachInterrupt(uint8_t interrupt_number)
{
    uint8_t interrupt_state;

    if (interrupt_number > 1u) {
        return;
    }

    interrupt_state = stc_interrupt_lock();
    if (interrupt_number == 0u) {
        IE &= (uint8_t)~STC_IE_EX0;
    } else {
        IE &= (uint8_t)~STC_IE_EX1;
    }
    stc_external_callbacks[interrupt_number] = 0;
    stc_interrupt_unlock(interrupt_state);
}

#if STC_CORE_HAS_INT0
void stc_external0_isr(void) __interrupt (0)
{
    void (*callback)(void) = stc_external_callbacks[0];
    if (callback != 0) {
        callback();
    }
}
#endif

#if STC_CORE_HAS_INT1
void stc_external1_isr(void) __interrupt (2)
{
    void (*callback)(void) = stc_external_callbacks[1];
    if (callback != 0) {
        callback();
    }
}
#endif
