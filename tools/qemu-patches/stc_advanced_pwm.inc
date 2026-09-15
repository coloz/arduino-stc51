/* SPDX-License-Identifier: GPL-2.0-or-later
 * STC advanced PWM A/B subset: edge-aligned mode 1, positive outputs,
 * prescaler/ARR/CCR preload and update events. No capture, complementary
 * output, dead time, break inputs, IRQs or physical pin mux model.
 * Included in stc32g_timer.c by the practical-test QEMU patch.
 */
#define TYPE_STC_ADVANCED_PWM "stc-advanced-pwm"
typedef struct StcAdvancedPWM StcAdvancedPWM;
typedef struct StcPWMBank {
    StcAdvancedPWM *parent;
    QEMUTimer *timer;
    int64_t epoch;
    uint16_t psc, arr, ccr[4];
    unsigned index;
} StcPWMBank;
struct StcAdvancedPWM {
    SysBusDevice parent_obj;
    MemoryRegion mmio;
    uint8_t regs[0x50];
    uint32_t frequency;
    qemu_irq output[8];
    StcPWMBank bank[2];
};
#define PWM_R(s, offset) ((s)->regs[(offset) - 0xb0])
static uint16_t stc_pwm_word(StcAdvancedPWM *s, unsigned offset)
{
    return (PWM_R(s, offset) << 8) | PWM_R(s, offset + 1);
}
static void stc_pwm_load(StcPWMBank *b)
{
    StcAdvancedPWM *s = b->parent;
    unsigned base = 0xc0 + b->index * 0x20;
    b->psc = stc_pwm_word(s, base + 0x10);
    b->arr = stc_pwm_word(s, base + 0x12);
    for (unsigned c = 0; c < 4; c++) {
        b->ccr[c] = stc_pwm_word(s, base + 0x15 + c * 2);
    }
}
static void stc_pwm_update(void *opaque)
{
    StcPWMBank *b = opaque;
    StcAdvancedPWM *s = b->parent;
    unsigned base = 0xc0 + b->index * 0x20;
    int64_t now = qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL);
    uint64_t tick_ns = DIV_ROUND_UP((uint64_t)(b->psc + 1) * 1000000000,
                                    s->frequency);
    uint64_t period = tick_ns * (b->arr + 1);
    uint64_t elapsed = MAX(0, now - b->epoch);
    bool running = PWM_R(s, base) & 1;
    if (running && elapsed >= period) {
        b->epoch += (elapsed / period) * period;
        stc_pwm_load(b);
        tick_ns = DIV_ROUND_UP((uint64_t)(b->psc + 1) * 1000000000,
                              s->frequency);
        period = tick_ns * (b->arr + 1);
        elapsed = now - b->epoch;
    }
    uint64_t counter = elapsed / tick_ns;
    int64_t next = b->epoch + period;
    for (unsigned c = 0; c < 4; c++) {
        bool enabled = running && (PWM_R(s, base + 0x1d) & 0x80) &&
            (PWM_R(s, 0xb1 + b->index * 4) & (1 << (c * 2))) &&
            (PWM_R(s, base + 0x0c + c / 2) & (1 << ((c % 2) * 4))) &&
            ((PWM_R(s, base + 8 + c) & 0x70) == 0x60);
        bool high = enabled && counter < b->ccr[c];
        qemu_set_irq(s->output[b->index * 4 + c], high);
        if (high && b->ccr[c] <= b->arr) {
            next = MIN(next, b->epoch + b->ccr[c] * tick_ns);
        }
    }
    if (running) timer_mod(b->timer, MAX(now + 1, next));
    else timer_del(b->timer);
}
static uint64_t stc_pwm_read(void *opaque, hwaddr addr, unsigned size)
{
    StcAdvancedPWM *s = opaque;
    unsigned offset = addr + 0xb0;
    if (offset == 0xce || offset == 0xcf || offset == 0xee || offset == 0xef) {
        StcPWMBank *b = &s->bank[offset >= 0xe0];
        stc_pwm_update(b);
        uint64_t tick_ns = DIV_ROUND_UP((uint64_t)(b->psc + 1) * 1000000000,
                                        s->frequency);
        uint16_t count = (qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL) - b->epoch) /
                         tick_ns;
        return (offset & 1) ? (count & 255) : (count >> 8);
    }
    return s->regs[addr];
}
static void stc_pwm_write(void *opaque, hwaddr addr, uint64_t value, unsigned size)
{
    StcAdvancedPWM *s = opaque;
    unsigned offset = addr + 0xb0;
    s->regs[addr] = value;
    for (unsigned n = 0; n < 2; n++) {
        unsigned base = 0xc0 + n * 0x20;
        if ((offset == base + 7 && (value & 1)) || offset == base) {
            if (offset != base || !(value & 1)) {
                s->bank[n].epoch = qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL);
            }
            if (offset == base + 7) stc_pwm_load(&s->bank[n]);
        }
        stc_pwm_update(&s->bank[n]);
    }
    if (offset == 0xc7 || offset == 0xe7) s->regs[addr] = 0;
}
static const MemoryRegionOps stc_pwm_ops = {
    .read = stc_pwm_read, .write = stc_pwm_write, .endianness = DEVICE_NATIVE_ENDIAN,
    .valid = { .min_access_size = 1, .max_access_size = 1 },
};
static void stc_pwm_reset(DeviceState *dev)
{
    StcAdvancedPWM *s = (StcAdvancedPWM *)dev;
    memset(s->regs, 0, sizeof(s->regs));
    for (unsigned n = 0; n < 2; n++) {
        s->bank[n].epoch = qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL);
        stc_pwm_load(&s->bank[n]);
        stc_pwm_update(&s->bank[n]);
    }
}
static void stc_pwm_init(Object *obj)
{
    StcAdvancedPWM *s = (StcAdvancedPWM *)obj;
    memory_region_init_io(&s->mmio, obj, &stc_pwm_ops, s, "stc-pwm-xfr", 0x50);
    sysbus_init_mmio(SYS_BUS_DEVICE(obj), &s->mmio);
    qdev_init_gpio_out_named(DEVICE(obj), s->output, "pwm-out", 8);
    for (unsigned n = 0; n < 2; n++) {
        s->bank[n].parent = s;
        s->bank[n].index = n;
        s->bank[n].timer = timer_new_ns(QEMU_CLOCK_VIRTUAL, stc_pwm_update,
                                        &s->bank[n]);
    }
}
static void stc_pwm_finalize(Object *obj)
{
    StcAdvancedPWM *s = (StcAdvancedPWM *)obj;
    for (unsigned n = 0; n < 2; n++) timer_free(s->bank[n].timer);
}
static const Property stc_pwm_properties[] = {
    DEFINE_PROP_UINT32("clock-frequency", StcAdvancedPWM, frequency, 24000000),
};
static void stc_pwm_class_init(ObjectClass *klass, const void *data)
{
    DeviceClass *dc = DEVICE_CLASS(klass);
    device_class_set_legacy_reset(dc, stc_pwm_reset);
    device_class_set_props(dc, stc_pwm_properties);
}
static const TypeInfo stc_pwm_type = {
    .name = TYPE_STC_ADVANCED_PWM, .parent = TYPE_SYS_BUS_DEVICE,
    .instance_size = sizeof(StcAdvancedPWM), .instance_init = stc_pwm_init,
    .instance_finalize = stc_pwm_finalize, .class_init = stc_pwm_class_init,
};
static void stc_pwm_register(void) { type_register_static(&stc_pwm_type); }
type_init(stc_pwm_register)
