# MCS251 QEMU development patches

These patches extend the locked upstream QEMU tree for the retained STC32 and AI8051U machines, Timer0/1, UART1, GPIO interrupts and the limited PWM model. Independent STC8 machine patches and the retired STC16 upper-bank extension are removed.

Start at the upstream commit in `practical-peripherals.json`, then apply:

```sh
git apply --check "$PATCH_DIR/exact-machines-v2.patch"
git apply "$PATCH_DIR/exact-machines-v2.patch"
git apply --check "$PATCH_DIR/practical-peripherals.patch"
git apply "$PATCH_DIR/practical-peripherals.patch"
cp "$PATCH_DIR/stc_advanced_pwm.inc" hw/timer/stc_advanced_pwm.inc
mkdir build-practical
cd build-practical
../configure --target-list=mcs251-softmmu --disable-docs --disable-gtk --disable-sdl --disable-werror
ninja -j4 qemu-system-mcs251
```

QEMU's shared `hw/mcs51`, `target/mcs51` and header paths are upstream implementation names also used by MCS251, not a second supported Arduino target. Do not apply the patches twice. Input/output and patch hashes are bound in the JSON manifest.

The PWM subset omits electrical pin routing, complementary outputs, dead time, capture and break inputs. Smaller exact-memory machines do not gain full ADC/SPI/I2C/USB emulation. UART socket delivery is not paced to the physical baud rate; use request/response pacing. Hardware remains necessary for electrical timing and peripheral behavior.
