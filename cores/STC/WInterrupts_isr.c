#include "Arduino.h"
#include "stc_isr_context.h"

#include "WInterrupts_private.h"

/*
 * Keep the ISR bodies and their callback state in a dedicated archive member.
 * main.c always references the available interrupt vectors, but sketches that
 * do not use attachInterrupt() must not also pull the configuration API.
 */
void (*stc_external_callbacks[2])(void);

#if STC_CORE_HAS_INT0
void stc_external0_isr(void) __interrupt (0)
{
    void (*callback)(void);

    STC_ISR_CONTEXT_ENTER();
    callback = stc_external_callbacks[0];
    if (callback != 0) {
        callback();
    }
    STC_ISR_CONTEXT_LEAVE();
}
#endif

#if STC_CORE_HAS_INT1
void stc_external1_isr(void) __interrupt (2)
{
    void (*callback)(void);

    STC_ISR_CONTEXT_ENTER();
    callback = stc_external_callbacks[1];
    if (callback != 0) {
        callback();
    }
    STC_ISR_CONTEXT_LEAVE();
}
#endif
