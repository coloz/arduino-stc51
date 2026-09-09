#ifndef STC_CORE_FAMILY_H
#define STC_CORE_FAMILY_H

#define STC_ADC_LAYOUT_NONE                    0
#define STC_ADC_LAYOUT_STC12C2052AD_C5_8BIT    1
#define STC_ADC_LAYOUT_LEGACY_BC_10BIT_AUXR1   2
#define STC_ADC_LAYOUT_LEGACY_BC_10BIT_CLKDIV  3
#define STC_ADC_LAYOUT_MODERN_BC_ADCCFG         4

/*
 * C++ translation units are lowered by the Clang STC frontend and then
 * rebuilt by SDCC at the bridge boundary.  Distinguish that frontend target
 * from the native SDCC predefined macros while accepting either as evidence
 * of the selected machine model.
 */
#if defined(__SDCC_mcs51) || defined(__STC_MCS51__)
# define STC_CORE_COMPILER_TARGET_MCS51 1
#else
# define STC_CORE_COMPILER_TARGET_MCS51 0
#endif
#if defined(__SDCC_mcs251) || defined(__STC_MCS251__)
# define STC_CORE_COMPILER_TARGET_MCS251 1
#else
# define STC_CORE_COMPILER_TARGET_MCS251 0
#endif

#if STC_CORE_COMPILER_TARGET_MCS51 && STC_CORE_COMPILER_TARGET_MCS251
# error "Select only one compiler machine target"
#endif

/*
 * Generated board definitions select the core family and hardware
 * capabilities explicitly.  Model-name macros remain available to SDK
 * headers and sketches, but the core never needs a per-model allow-list.
 */

#if (defined(STC_CORE_FAMILY_89) + \
     defined(STC_CORE_FAMILY_12) + \
     defined(STC_CORE_FAMILY_15) + \
     defined(STC_CORE_FAMILY_16) + \
     defined(STC_CORE_FAMILY_8) + \
     defined(STC_CORE_FAMILY_32) + \
     defined(STC_CORE_FAMILY_AI8051U)) != 1
# error "Select exactly one STC core family"
#endif

#if !defined(STC_CORE_HAS_PORT0) || !defined(STC_CORE_HAS_PORT1) || \
    !defined(STC_CORE_HAS_PORT2) || !defined(STC_CORE_HAS_PORT3) || \
    !defined(STC_CORE_HAS_PORT4) || !defined(STC_CORE_HAS_PORT5) || \
    !defined(STC_CORE_HAS_PORT6) || !defined(STC_CORE_HAS_PORT7) || \
    !defined(STC_CORE_HAS_PORT8) || !defined(STC_CORE_HAS_PORT9) || \
    !defined(STC_CORE_HAS_PORTA) || !defined(STC_CORE_HAS_PORTB) || \
    !defined(STC_CORE_HAS_PORT_MODE) || !defined(STC_CORE_TIMER1_IS_1T) || \
    !defined(STC_CORE_HAS_UART1) || !defined(STC_CORE_SERIAL_BUFFERED_RX) || \
    !defined(STC_CORE_HAS_ADC) || !defined(STC_CORE_ADC_LAYOUT) || \
    !defined(STC_CORE_HAS_SEPARATE_PULLUP) || \
    !defined(STC_CORE_PINMUX_PSWX1_BIT0_CLEAR) || \
    !defined(STC_CORE_ADC_NATIVE_BITS)
# error "Selected board is missing generated STC core capability flags"
#endif

#if (STC_CORE_HAS_PORT0 != 1) || (STC_CORE_HAS_PORT1 != 1) || \
    (STC_CORE_HAS_PORT2 != 1) || (STC_CORE_HAS_PORT3 != 1)
# error "The current STC core requires ports P0 through P3"
#endif

#if ((STC_CORE_HAS_PORT4 != 0) && (STC_CORE_HAS_PORT4 != 1)) || \
    ((STC_CORE_HAS_PORT5 != 0) && (STC_CORE_HAS_PORT5 != 1)) || \
    ((STC_CORE_HAS_PORT6 != 0) && (STC_CORE_HAS_PORT6 != 1)) || \
    ((STC_CORE_HAS_PORT7 != 0) && (STC_CORE_HAS_PORT7 != 1)) || \
    ((STC_CORE_HAS_PORT8 != 0) && (STC_CORE_HAS_PORT8 != 1)) || \
    ((STC_CORE_HAS_PORT9 != 0) && (STC_CORE_HAS_PORT9 != 1)) || \
    ((STC_CORE_HAS_PORTA != 0) && (STC_CORE_HAS_PORTA != 1)) || \
    ((STC_CORE_HAS_PORTB != 0) && (STC_CORE_HAS_PORTB != 1)) || \
    ((STC_CORE_HAS_PORT_MODE != 0) && (STC_CORE_HAS_PORT_MODE != 1)) || \
    ((STC_CORE_TIMER1_IS_1T != 0) && (STC_CORE_TIMER1_IS_1T != 1)) || \
    ((STC_CORE_HAS_UART1 != 0) && (STC_CORE_HAS_UART1 != 1)) || \
    ((STC_CORE_HAS_ADC != 0) && (STC_CORE_HAS_ADC != 1)) || \
    ((STC_CORE_HAS_SEPARATE_PULLUP != 0) && \
     (STC_CORE_HAS_SEPARATE_PULLUP != 1)) || \
    ((STC_CORE_PINMUX_PSWX1_BIT0_CLEAR != 0) && \
     (STC_CORE_PINMUX_PSWX1_BIT0_CLEAR != 1)) || \
    ((STC_CORE_SERIAL_BUFFERED_RX != 0) && \
     (STC_CORE_SERIAL_BUFFERED_RX != 1))
# error "STC core capability flags must be 0 or 1"
#endif

#if STC_CORE_HAS_SEPARATE_PULLUP && !STC_CORE_HAS_PORT_MODE
# error "Separate pull-up control requires configurable port modes"
#endif

#if (STC_CORE_HAS_PORT8 || STC_CORE_HAS_PORT9 || STC_CORE_HAS_PORTA || \
     STC_CORE_HAS_PORTB) && !defined(STC_CORE_FAMILY_32)
# error "Extended P8/P9/PA/PB ports are only supported on STC32 targets"
#endif

#if !STC_CORE_HAS_UART1 && STC_CORE_SERIAL_BUFFERED_RX
# error "Buffered UART receive requires UART1"
#endif

#if !STC_CORE_HAS_ADC
# if (STC_CORE_ADC_LAYOUT != STC_ADC_LAYOUT_NONE) || \
     (STC_CORE_ADC_NATIVE_BITS != 0)
#  error "A target without ADC must select layout NONE and zero native bits"
# endif
#elif STC_CORE_ADC_LAYOUT == STC_ADC_LAYOUT_STC12C2052AD_C5_8BIT
# if !defined(STC_CORE_FAMILY_12) || (STC_CORE_ADC_NATIVE_BITS != 8)
#  error "The STC12C2052AD ADC layout requires an 8-bit STC12 target"
# endif
#elif STC_CORE_ADC_LAYOUT == STC_ADC_LAYOUT_LEGACY_BC_10BIT_AUXR1
# if !defined(STC_CORE_FAMILY_12) || (STC_CORE_ADC_NATIVE_BITS != 10)
#  error "The AUXR1 ADC layout requires a 10-bit STC12 target"
# endif
#elif STC_CORE_ADC_LAYOUT == STC_ADC_LAYOUT_LEGACY_BC_10BIT_CLKDIV
# if !defined(STC_CORE_FAMILY_15) || (STC_CORE_ADC_NATIVE_BITS != 10)
#  error "The CLK_DIV ADC layout requires a 10-bit STC15 target"
# endif
#elif STC_CORE_ADC_LAYOUT == STC_ADC_LAYOUT_MODERN_BC_ADCCFG
# if (!defined(STC_CORE_FAMILY_8) && !defined(STC_CORE_FAMILY_32) && \
      !defined(STC_CORE_FAMILY_AI8051U)) || \
     ((STC_CORE_ADC_NATIVE_BITS != 10) && (STC_CORE_ADC_NATIVE_BITS != 12))
#  error "The modern ADC layout requires a 10/12-bit STC8/STC32/AI target"
# endif
#else
# error "Unsupported STC ADC register layout"
#endif

#if STC_CORE_PINMUX_PSWX1_BIT0_CLEAR && \
    (!defined(STC_CORE_FAMILY_8) || \
     (STC_CORE_ADC_LAYOUT != STC_ADC_LAYOUT_MODERN_BC_ADCCFG))
# error "P_SWX1 pin routing is only valid on the selected modern AI8 targets"
#endif

#if (STC_CORE_ADC_LAYOUT == STC_ADC_LAYOUT_LEGACY_BC_10BIT_AUXR1) || \
    (STC_CORE_ADC_LAYOUT == STC_ADC_LAYOUT_LEGACY_BC_10BIT_CLKDIV)
# define STC_CORE_ADC_USES_P1ASF 1
#else
# define STC_CORE_ADC_USES_P1ASF 0
#endif

#if defined(STC_EXECUTION_MODE_MCS51) && defined(STC_EXECUTION_MODE_MCS251)
# error "Select only one STC execution mode"
#endif

#if defined(STC_CORE_FAMILY_16) || defined(STC_CORE_FAMILY_32)
# define STC_CORE_USES_MCS251 1
#elif defined(STC_CORE_FAMILY_AI8051U)
/* AI8051U supports its documented MCS-51 compatibility execution mode. */
# if defined(STC_EXECUTION_MODE_MCS251)
#  define STC_CORE_USES_MCS251 1
# elif defined(STC_EXECUTION_MODE_MCS51)
#  define STC_CORE_USES_MCS251 0
# elif STC_CORE_COMPILER_TARGET_MCS251
#  define STC_CORE_USES_MCS251 1
# else
#  define STC_CORE_USES_MCS251 0
# endif
#else
# define STC_CORE_USES_MCS251 0
#endif

/*
 * Timer mode 0 is the STC 16-bit auto-reload mode on STC15/STC16 and newer
 * families. STC89 and STC12 retain the classic 8051 timer layout, so the
 * core uses mode 1 and reloads Timer0 in software on those devices.
 */
#if defined(STC_CORE_FAMILY_15) || defined(STC_CORE_FAMILY_16) || \
    defined(STC_CORE_FAMILY_8) || \
    defined(STC_CORE_FAMILY_32) || defined(STC_CORE_FAMILY_AI8051U)
# define STC_CORE_HAS_TIMER01_16BIT_AUTO_RELOAD 1
# define STC_CORE_HAS_MODERN_UART1_BRT 1
#else
# define STC_CORE_HAS_TIMER01_16BIT_AUTO_RELOAD 0
# define STC_CORE_HAS_MODERN_UART1_BRT 0
#endif

/* The classic INT0/INT1 pins and vectors are common to every target. */
#define STC_CORE_HAS_INT0 1
#define STC_CORE_HAS_INT1 1

#if defined(STC_EXECUTION_MODE_MCS51) && !STC_CORE_COMPILER_TARGET_MCS51
# error "STC_EXECUTION_MODE_MCS51 requires an MCS51 compiler target"
#elif defined(STC_EXECUTION_MODE_MCS251) && !STC_CORE_COMPILER_TARGET_MCS251
# error "STC_EXECUTION_MODE_MCS251 requires an MCS251 compiler target"
#elif STC_CORE_USES_MCS251
# if !STC_CORE_COMPILER_TARGET_MCS251
#  error "STC16/STC32/AI8051U targets require an MCS251 compiler target"
# endif
#elif STC_CORE_COMPILER_TARGET_MCS251
# error "STC8 targets require an MCS51 compiler target"
#endif

#endif
