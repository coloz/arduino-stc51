#ifndef STC_CORE_SFR_H
#define STC_CORE_SFR_H

#include "stc_family.h"

#if !defined(__SDCC)
# error "The arduino-stc51 core currently requires SDCC"
#endif

/* Common 8051/STC special-function registers used by this minimal core. */
#define STC_SFR(name, address) __sfr __at (address) name

STC_SFR(P0,   0x80);
STC_SFR(PCON, 0x87);
STC_SFR(TCON, 0x88);
STC_SFR(TMOD, 0x89);
STC_SFR(TL0,  0x8a);
STC_SFR(TL1,  0x8b);
STC_SFR(TH0,  0x8c);
STC_SFR(TH1,  0x8d);
#if defined(STC_CORE_FAMILY_16)
/* STC16F relocates AUXR; 0x8e is CKCON on this family. */
STC_SFR(AUXR, 0x93);
#else
STC_SFR(AUXR, 0x8e);
#endif
STC_SFR(P1,   0x90);
STC_SFR(SCON, 0x98);
STC_SFR(SBUF, 0x99);
STC_SFR(P2,   0xa0);
STC_SFR(IE,   0xa8);
STC_SFR(P3,   0xb0);

#if STC_CORE_HAS_PORT4
# if defined(STC_CORE_FAMILY_89)
/* STC89C5xRC/RD+: P4 is 0xe8 and XICON is 0xc0. */
STC_SFR(P4, 0xe8);
# else
STC_SFR(P4, 0xc0);
# endif
#endif
#if STC_CORE_HAS_PORT5
STC_SFR(P5, 0xc8);
#endif
#if STC_CORE_HAS_PORT6
STC_SFR(P6, 0xe8);
#endif
#if STC_CORE_HAS_PORT7
STC_SFR(P7, 0xf8);
#endif

/*
 * STC32G144K246 maps P8/P9/PA/PB into the 24-bit XFR address space.
 * The mcs251 backend emits DPX-assisted accesses for these lvalues.
 */
#define STC_XFR8(address) \
    (*(volatile __xdata unsigned char *)(address))

#if STC_CORE_HAS_PORT8
# define P8OUT  STC_XFR8(0x7ef700UL)
# define P8IN   STC_XFR8(0x7ef708UL)
# define P8M0   STC_XFR8(0x7ef710UL)
# define P8M1   STC_XFR8(0x7ef718UL)
# define P8SETB STC_XFR8(0x7ef720UL)
# define P8CLRB STC_XFR8(0x7ef728UL)
#endif
#if STC_CORE_HAS_PORT9
# define P9OUT  STC_XFR8(0x7ef701UL)
# define P9IN   STC_XFR8(0x7ef709UL)
# define P9M0   STC_XFR8(0x7ef711UL)
# define P9M1   STC_XFR8(0x7ef719UL)
# define P9SETB STC_XFR8(0x7ef721UL)
# define P9CLRB STC_XFR8(0x7ef729UL)
#endif
#if STC_CORE_HAS_PORTA
# define PAOUT  STC_XFR8(0x7ef702UL)
# define PAIN   STC_XFR8(0x7ef70aUL)
# define PAM0   STC_XFR8(0x7ef712UL)
# define PAM1   STC_XFR8(0x7ef71aUL)
# define PASETB STC_XFR8(0x7ef722UL)
# define PACLRB STC_XFR8(0x7ef72aUL)
#endif
#if STC_CORE_HAS_PORTB
# define PBOUT  STC_XFR8(0x7ef703UL)
# define PBIN   STC_XFR8(0x7ef70bUL)
# define PBM0   STC_XFR8(0x7ef713UL)
# define PBM1   STC_XFR8(0x7ef71bUL)
# define PBSETB STC_XFR8(0x7ef723UL)
# define PBCLRB STC_XFR8(0x7ef72bUL)
#endif

#if STC_CORE_HAS_MODERN_UART1_BRT
# if defined(STC_CORE_FAMILY_16)
STC_SFR(P_SW1, 0x9a);
# else
STC_SFR(P_SW1, 0xa2);
# endif
#endif

#if (STC_CORE_HAS_ADC && \
     (STC_CORE_ADC_LAYOUT == STC_ADC_LAYOUT_MODERN_BC_ADCCFG)) || \
    STC_CORE_HAS_PORT8 || STC_CORE_HAS_PORT9 || \
    STC_CORE_HAS_PORTA || STC_CORE_HAS_PORTB
# if defined(STC_CORE_FAMILY_16)
STC_SFR(P_SW2, 0x9b);
# else
STC_SFR(P_SW2, 0xba);
# endif
#endif

#if STC_CORE_HAS_PORT8 || STC_CORE_HAS_PORT9 || \
    STC_CORE_HAS_PORTA || STC_CORE_HAS_PORTB
STC_SFR(WTST,  0xe9);
STC_SFR(CKCON, 0xea);
# define TM0PS STC_XFR8(0x7efea0UL)
#endif

#if STC_CORE_HAS_SEPARATE_PULLUP
/* P0-P7 and P8-PB use two XFR banks for their pull-up enables. */
# define P0PU STC_XFR8(0x7efe10UL)
# define P1PU STC_XFR8(0x7efe11UL)
# define P2PU STC_XFR8(0x7efe12UL)
# define P3PU STC_XFR8(0x7efe13UL)
# define P4PU STC_XFR8(0x7efe14UL)
# define P5PU STC_XFR8(0x7efe15UL)
# define P6PU STC_XFR8(0x7efe16UL)
# define P7PU STC_XFR8(0x7efe17UL)
# define P8PU STC_XFR8(0x7ef9c0UL)
# define P9PU STC_XFR8(0x7ef9c1UL)
# define PAPU STC_XFR8(0x7ef9c2UL)
# define PBPU STC_XFR8(0x7ef9c3UL)
#endif

#if STC_CORE_HAS_PORT_MODE
# if defined(STC_CORE_FAMILY_16)
/* STC16Fxx.h and the STC16 manual SFR table use this separate layout. */
STC_SFR(P0M1, 0xf1);
STC_SFR(P0M0, 0xf2);
STC_SFR(P1M1, 0xf3);
STC_SFR(P1M0, 0xf4);
STC_SFR(P2M1, 0xf5);
STC_SFR(P2M0, 0xf6);
STC_SFR(P3M1, 0xf9);
STC_SFR(P3M0, 0xfa);
STC_SFR(P4M1, 0xfb);
STC_SFR(P4M0, 0xfc);
#  if STC_CORE_HAS_PORT5
STC_SFR(P5M1, 0xec);
STC_SFR(P5M0, 0xed);
#  endif
#  if STC_CORE_HAS_PORT6
STC_SFR(P6M1, 0xee);
STC_SFR(P6M0, 0xef);
#  endif
#  if STC_CORE_HAS_PORT7
STC_SFR(P7M1, 0xd2);
STC_SFR(P7M0, 0xd3);
#  endif
# else
STC_SFR(P1M1, 0x91);
STC_SFR(P1M0, 0x92);
STC_SFR(P0M1, 0x93);
STC_SFR(P0M0, 0x94);
STC_SFR(P2M1, 0x95);
STC_SFR(P2M0, 0x96);
STC_SFR(P3M1, 0xb1);
STC_SFR(P3M0, 0xb2);
STC_SFR(P4M1, 0xb3);
STC_SFR(P4M0, 0xb4);
# if STC_CORE_HAS_PORT5
STC_SFR(P5M1, 0xc9);
STC_SFR(P5M0, 0xca);
# endif
# if STC_CORE_HAS_PORT6
STC_SFR(P6M1, 0xcb);
STC_SFR(P6M0, 0xcc);
# endif
# if STC_CORE_HAS_PORT7
STC_SFR(P7M1, 0xe1);
STC_SFR(P7M0, 0xe2);
# endif
# endif
#endif

#if STC_CORE_HAS_ADC
# if STC_CORE_ADC_LAYOUT == STC_ADC_LAYOUT_STC12C2052AD_C5_8BIT
STC_SFR(ADC_CONTR, 0xc5);
STC_SFR(ADC_DATA,  0xc6);
# else
STC_SFR(ADC_CONTR, 0xbc);
STC_SFR(ADC_RES,   0xbd);
STC_SFR(ADC_RESL,  0xbe);
# endif
# if STC_CORE_ADC_USES_P1ASF
STC_SFR(P1ASF, 0x9d);
# endif
# if STC_CORE_ADC_LAYOUT == STC_ADC_LAYOUT_LEGACY_BC_10BIT_AUXR1
STC_SFR(STC_ADC_ADJUST, 0xa2);
# elif STC_CORE_ADC_LAYOUT == STC_ADC_LAYOUT_LEGACY_BC_10BIT_CLKDIV
STC_SFR(STC_ADC_ADJUST, 0x97);
# elif STC_CORE_ADC_LAYOUT == STC_ADC_LAYOUT_MODERN_BC_ADCCFG
STC_SFR(ADCCFG, 0xde);
# endif
#endif

#if STC_CORE_PINMUX_PSWX1_BIT0_CLEAR
/*
 * AI8H2K maps P_SWX1 into the extended SFR window at XDATA 0xFD69.
 * P_SW2.7 must be set only while this lvalue is accessed.
 */
# define STC_P_SWX1 (*(volatile __xdata unsigned char *)0xfd69u)
#endif

#undef STC_SFR

#define STC_SCON_RI       0x01u
#define STC_SCON_TI       0x02u
#define STC_SCON_REN      0x10u
#define STC_SCON_MODE1    0x40u
#define STC_TCON_TR1      0x40u
#define STC_TCON_TF0      0x20u
#define STC_TCON_TR0      0x10u
#define STC_TCON_IE1      0x08u
#define STC_TCON_IT1      0x04u
#define STC_TCON_IE0      0x02u
#define STC_TCON_IT0      0x01u
#define STC_PCON_SMOD     0x80u
#define STC_AUXR_T0_1T    0x80u
#define STC_AUXR_T1_1T    0x40u
#define STC_AUXR_S1_BRT_T2 0x01u
#define STC_P_SW2_EAXFR   0x80u

#define STC_IE_EA         0x80u
#define STC_IE_ES         0x10u
#define STC_IE_ET1        0x08u
#define STC_IE_EX1        0x04u
#define STC_IE_ET0        0x02u
#define STC_IE_EX0        0x01u

#endif
