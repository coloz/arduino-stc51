#ifndef STCXX_SPI_CLASS_H
#define STCXX_SPI_CLASS_H

#include <stddef.h>
#include <stdint.h>

#include "stcxx_config.h"

#ifndef LSBFIRST
# define LSBFIRST 0u
#endif
#ifndef MSBFIRST
# define MSBFIRST 1u
#endif

#ifndef SPI_MODE0
# define SPI_MODE0 0x00u
#endif
#ifndef SPI_MODE1
# define SPI_MODE1 0x01u
#endif
#ifndef SPI_MODE2
# define SPI_MODE2 0x02u
#endif
#ifndef SPI_MODE3
# define SPI_MODE3 0x03u
#endif

#ifndef SPI_DEFAULT_CLOCK_HZ
# define SPI_DEFAULT_CLOCK_HZ 100000UL
#endif

#ifndef SPI_HAS_TRANSACTION
# define SPI_HAS_TRANSACTION 1
#endif
#ifndef SPI_HAS_NOTUSINGINTERRUPT
# define SPI_HAS_NOTUSINGINTERRUPT 1
#endif
#ifndef SPI_ATOMIC_VERSION
# define SPI_ATOMIC_VERSION 1
#endif

/*
 * Legacy Arduino SPI libraries pass these symbolic values to
 * setClockDivider().  They are divisor ratios here, not AVR register
 * encodings; the software HAL consumes a requested clock frequency.
 */
#ifndef SPI_CLOCK_DIV2
# define SPI_CLOCK_DIV2 2u
#endif
#ifndef SPI_CLOCK_DIV4
# define SPI_CLOCK_DIV4 4u
#endif
#ifndef SPI_CLOCK_DIV8
# define SPI_CLOCK_DIV8 8u
#endif
#ifndef SPI_CLOCK_DIV16
# define SPI_CLOCK_DIV16 16u
#endif
#ifndef SPI_CLOCK_DIV32
# define SPI_CLOCK_DIV32 32u
#endif
#ifndef SPI_CLOCK_DIV64
# define SPI_CLOCK_DIV64 64u
#endif
#ifndef SPI_CLOCK_DIV128
# define SPI_CLOCK_DIV128 128u
#endif

class SPISettings
{
public:
    SPISettings()
        : _clock((uint32_t)SPI_DEFAULT_CLOCK_HZ), _bitOrder(MSBFIRST),
          _dataMode(SPI_MODE0)
    {
    }

    SPISettings(uint32_t clock, uint8_t bitOrder, uint8_t dataMode)
        : _clock(clock),
          _bitOrder(bitOrder == LSBFIRST ? LSBFIRST : MSBFIRST),
          _dataMode((uint8_t)(dataMode & 0x03u))
    {
    }

private:
    uint32_t _clock;
    uint8_t _bitOrder;
    uint8_t _dataMode;

    friend class SPIClass;
};

class SPIClass
{
public:
    void begin();
    void end();
    void setPins(uint8_t mosi, uint8_t miso, uint8_t clock, uint8_t select);

    void beginTransaction(const SPISettings &settings);
    void beginTransaction(uint32_t clock, uint8_t bitOrder,
                          uint8_t dataMode);
    void endTransaction();

    uint8_t transfer(uint8_t value);
    uint16_t transfer16(uint16_t value);
    void transfer(void *buffer, size_t length);

    void setBitOrder(uint8_t bitOrder);
    void setDataMode(uint8_t dataMode);
    void setClockDivider(uint8_t clockDivider);

    /* Register interrupt users so transactions can exclude them safely. */
    void usingInterrupt(uint8_t interruptNumber);
    void notUsingInterrupt(uint8_t interruptNumber);

    /* Software SPI has no peripheral interrupt to enable or disable. */
    void attachInterrupt() {}
    void detachInterrupt() {}
};

extern SPIClass SPI;

#endif
