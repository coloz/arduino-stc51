#if defined(STCXX_CPP_CORE) && STCXX_CPP_CORE

#include <cpp/SPIClass.h>
#include <cpp/stc_c_hal.h>

namespace {

uint32_t currentClock = (uint32_t)SPI_DEFAULT_CLOCK_HZ;
uint8_t currentBitOrder = MSBFIRST;
uint8_t currentDataMode = SPI_MODE0;

} // namespace

SPIClass SPI;

void SPIClass::begin()
{
    SPI_begin();
}

void SPIClass::end()
{
    SPI_end();
}

void SPIClass::setPins(uint8_t mosi, uint8_t miso, uint8_t clock,
                       uint8_t select)
{
    SPI_setPins(mosi, miso, clock, select);
}

void SPIClass::beginTransaction(const SPISettings &settings)
{
    currentClock = settings._clock;
    currentBitOrder = settings._bitOrder;
    currentDataMode = settings._dataMode;
    SPI_beginTransaction((unsigned long)currentClock, currentBitOrder,
                         currentDataMode);
}

void SPIClass::beginTransaction(uint32_t clock, uint8_t bitOrder,
                                uint8_t dataMode)
{
    beginTransaction(SPISettings(clock, bitOrder, dataMode));
}

void SPIClass::endTransaction()
{
    SPI_endTransaction();
}

void SPIClass::usingInterrupt(uint8_t interruptNumber)
{
    SPI_usingInterrupt(interruptNumber);
}

void SPIClass::notUsingInterrupt(uint8_t interruptNumber)
{
    SPI_notUsingInterrupt(interruptNumber);
}

uint8_t SPIClass::transfer(uint8_t value)
{
    return SPI_transfer(value);
}

uint16_t SPIClass::transfer16(uint16_t value)
{
    uint8_t first;
    uint8_t second;

    if (currentBitOrder == LSBFIRST) {
        first = SPI_transfer((uint8_t)value);
        second = SPI_transfer((uint8_t)(value >> 8));
        return (uint16_t)((uint16_t)first | ((uint16_t)second << 8));
    }

    first = SPI_transfer((uint8_t)(value >> 8));
    second = SPI_transfer((uint8_t)value);
    return (uint16_t)(((uint16_t)first << 8) | (uint16_t)second);
}

void SPIClass::transfer(void *buffer, size_t length)
{
    SPI_transferBuffer(static_cast<uint8_t *>(buffer), length);
}

void SPIClass::setBitOrder(uint8_t bitOrder)
{
    currentBitOrder = (bitOrder == LSBFIRST) ? LSBFIRST : MSBFIRST;
    SPI_setSettings((unsigned long)currentClock, currentBitOrder,
                    currentDataMode);
}

void SPIClass::setDataMode(uint8_t dataMode)
{
    currentDataMode = (uint8_t)(dataMode & 0x03u);
    SPI_setSettings((unsigned long)currentClock, currentBitOrder,
                    currentDataMode);
}

void SPIClass::setClockDivider(uint8_t clockDivider)
{
#if defined(F_CPU)
    /* Spell out the ratios so the freestanding frontend can fold every
     * division at compile time; no target integer-division helper is needed. */
    if (clockDivider == SPI_CLOCK_DIV2) {
        currentClock = (uint32_t)(F_CPU / 2UL);
    } else if (clockDivider == SPI_CLOCK_DIV4) {
        currentClock = (uint32_t)(F_CPU / 4UL);
    } else if (clockDivider == SPI_CLOCK_DIV8) {
        currentClock = (uint32_t)(F_CPU / 8UL);
    } else if (clockDivider == SPI_CLOCK_DIV16) {
        currentClock = (uint32_t)(F_CPU / 16UL);
    } else if (clockDivider == SPI_CLOCK_DIV32) {
        currentClock = (uint32_t)(F_CPU / 32UL);
    } else if (clockDivider == SPI_CLOCK_DIV64) {
        currentClock = (uint32_t)(F_CPU / 64UL);
    } else if (clockDivider == SPI_CLOCK_DIV128) {
        currentClock = (uint32_t)(F_CPU / 128UL);
    } else {
        currentClock = (uint32_t)SPI_DEFAULT_CLOCK_HZ;
    }
    if (currentClock == 0u) {
        currentClock = 1u;
    }
#else
    /* Host-only consumers without a board definition retain the safe HAL
     * default instead of inventing a CPU frequency. */
    (void)clockDivider;
    currentClock = (uint32_t)SPI_DEFAULT_CLOCK_HZ;
#endif
    SPI_setSettings((unsigned long)currentClock, currentBitOrder,
                    currentDataMode);
}

#endif /* STCXX_CPP_CORE */
