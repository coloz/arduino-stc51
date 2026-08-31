#!/usr/bin/env node
// Generate boards.txt and per-model variants from devices.json.

import { readFileSync, writeFileSync, mkdirSync, existsSync } from "node:fs";
import { dirname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = dirname(fileURLToPath(import.meta.url));
const root = join(scriptDir, "..", "..");
const databasePath = join(scriptDir, "devices.json");
const check = process.argv.includes("--check");

const CORE_FAMILY_RULES = [
  [/^STC89/, "89"],
  [/^STC12/, "12"],
  [/^STC15/, "15"],
  [/^STC8(?!9)/, "8"],
  [/^AI8[A-Z]/, "8"],
  [/^STC32/, "32"],
  [/^AI8051U$/, "AI8051U"],
];

const ADC_LAYOUTS = {
  stc12c2052ad_c5_8bit: { id: 1, resolutions: [8], p1Only: true },
  legacy_bc_10bit_auxr1: { id: 2, resolutions: [10], p1Only: true },
  legacy_bc_10bit_clkdiv: { id: 3, resolutions: [10], p1Only: true },
  modern_bc_adccfg: { id: 4, resolutions: [10, 12], p1Only: false },
};

const PIN_SELECTORS = new Set(["pswx1_bit0_clear_for_p5_4"]);

function isObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function requireString(device, field) {
  if (typeof device[field] !== "string" || device[field].trim() === "") {
    throw new Error(`${field} must be a non-empty string for ${device.model ?? device.id ?? "device"}`);
  }
}

function requireInteger(device, field, minimum = 0) {
  if (!Number.isInteger(device[field]) || device[field] < minimum) {
    throw new Error(`${field} must be an integer >= ${minimum} for ${device.model ?? device.id ?? "device"}`);
  }
}

function coreFamilyName(device) {
  const matches = CORE_FAMILY_RULES.filter(([pattern]) => pattern.test(device.family));
  if (matches.length !== 1) {
    throw new Error(`unsupported or ambiguous core family ${device.family} for ${device.model}`);
  }
  return matches[0][1];
}

function adcEntries(device) {
  return device.adc === false ? [] :
    Object.entries(device.adc.channels).sort((left, right) => left[1] - right[1]);
}

function adcLayoutId(device) {
  return device.adc === false ? 0 : ADC_LAYOUTS[device.adc.layout].id;
}

function pinMacro(pin) {
  return pin.replace(".", "_");
}

function physicalIoCount(device) {
  return device.physical_io ?? device.max_io;
}

function pinAliasGroups(device) {
  return device.pin_alias_groups ?? [];
}

function renderPhysicalAliasMacro(device) {
  const mappings = [];
  for (const [left, right] of pinAliasGroups(device)) {
    mappings.push([pinMacro(left), pinMacro(right)]);
    mappings.push([pinMacro(right), pinMacro(left)]);
  }
  return renderMapMacro("STC_VARIANT_PHYSICAL_ALIAS", "pin", mappings, "NOT_A_PIN");
}

function renderPinAliasMacro(device) {
  const pairs = [];
  for (const group of pinAliasGroups(device)) {
    for (let left = 0; left < group.length; left += 1) {
      for (let right = left + 1; right < group.length; right += 1) {
        pairs.push([pinMacro(group[left]), pinMacro(group[right])]);
      }
    }
  }
  if (pairs.length === 0) {
    return "#define STC_VARIANT_PINS_SHARE_PHYSICAL_PAD(left, right) (0)";
  }
  const lines = ["#define STC_VARIANT_PINS_SHARE_PHYSICAL_PAD(left, right) \\"];
  pairs.forEach(([left, right], index) => {
    const prefix = index === 0 ? "  (" : "   ";
    const suffix = index === pairs.length - 1 ? ")" : " || \\";
    const expression = `((((left) == (${left})) && ((right) == (${right}))) || ` +
      `(((left) == (${right})) && ((right) == (${left}))))`;
    lines.push(`${prefix}${expression}${suffix}`);
  });
  return lines.join("\n");
}

function renderMapMacro(name, argument, mappings, fallback) {
  if (mappings.length === 0) return `#define ${name}(${argument}) (${fallback})`;
  const lines = [`#define ${name}(${argument}) \\`];
  mappings.forEach(([key, value], index) => {
    const prefix = index === 0 ? "  (" : "   ";
    lines.push(`${prefix}((${argument}) == (${key})) ? (${value}) : \\`);
  });
  lines.push(`   (${fallback}))`);
  return lines.join("\n");
}

function renderCoreFlags(device) {
  const ports = new Set(device.capabilities.ports);
  const flags = [`-DSTC_CORE_FAMILY_${coreFamilyName(device)}=1`];
  for (let port = 0; port < 8; port += 1) {
    flags.push(`-DSTC_CORE_HAS_PORT${port}=${ports.has(port) ? 1 : 0}`);
  }
  flags.push(`-DSTC_CORE_HAS_PORT_MODE=${device.capabilities.port_mode ? 1 : 0}`);
  flags.push(`-DSTC_CORE_TIMER1_IS_1T=${device.capabilities.timer1_1t ? 1 : 0}`);
  flags.push(`-DSTC_CORE_HAS_UART1=${device.capabilities.uart1 === false ? 0 : 1}`);
  flags.push(`-DSTC_CORE_SERIAL_BUFFERED_RX=${device.capabilities.uart1 !== false && device.maximum_code_bytes > 2048 ? 1 : 0}`);
  flags.push(`-DSTC_CORE_HAS_ADC=${device.adc === false ? 0 : 1}`);
  flags.push(`-DSTC_CORE_ADC_LAYOUT=${adcLayoutId(device)}`);
  flags.push(`-DSTC_CORE_PINMUX_PSWX1_BIT0_CLEAR=${device.pin_selector === "pswx1_bit0_clear_for_p5_4" ? 1 : 0}`);
  flags.push(`-DSTC_CORE_ADC_NATIVE_BITS=${device.adc === false ? 0 : device.adc.resolution_bits}`);
  return flags.join(" ");
}

function popcount(value) {
  let count = 0;
  for (let byte = value; byte; byte >>>= 1) count += byte & 1;
  return count;
}

function loadDatabase() {
  const data = JSON.parse(readFileSync(databasePath, "utf8"));
  if (!isObject(data)) throw new Error("devices.json root must be an object");
  if (data.schema_version !== 2) throw new Error("unsupported devices.json schema");
  if (typeof data.as_of !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(data.as_of)) {
    throw new Error("as_of must use YYYY-MM-DD format");
  }
  if (data.pin_encoding !== "(port << 4) | bit") {
    throw new Error("unsupported pin encoding");
  }
  if (!Array.isArray(data.devices) || data.devices.length === 0) {
    throw new Error("devices must be a non-empty array");
  }
  const ids = new Set();
  const models = new Set();
  const macros = new Set();
  const variants = new Set();
  for (const device of data.devices) {
    if (!isObject(device)) throw new Error("each device must be an object");
    for (const field of ["id", "model", "macro", "family", "selection", "target", "eeprom", "default_memory_model", "official_url"]) {
      requireString(device, field);
    }
    if (!/^[a-z0-9][a-z0-9_]*$/.test(device.id)) {
      throw new Error(`invalid board id ${device.id}`);
    }
    if (!/^[A-Za-z0-9][A-Za-z0-9_+\-]*$/.test(device.model)) {
      throw new Error(`invalid model name ${device.model}`);
    }
    if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(device.macro)) {
      throw new Error(`invalid C macro ${device.macro} for ${device.model}`);
    }
    if (!/^[A-Z][A-Z0-9]*$/.test(device.family)) {
      throw new Error(`invalid SDK family ${device.family} for ${device.model}`);
    }
    if (!/^[a-z][a-z0-9_]*$/.test(device.selection)) {
      throw new Error(`invalid selection group ${device.selection} for ${device.model}`);
    }
    if (!/^https:\/\/(?:www\.)?stcmicro\.com\//.test(device.official_url)) {
      throw new Error(`official_url must use the STC website for ${device.model}`);
    }
    if (!["mcs51", "mcs251", "dual"].includes(device.target)) {
      throw new Error(`invalid compiler target ${device.target} for ${device.model}`);
    }
    if (typeof device.experimental !== "boolean") {
      throw new Error(`experimental must be boolean for ${device.model}`);
    }
    if (device.target === "mcs251" && !device.experimental) {
      throw new Error(`${device.model} uses mcs251 but is not marked experimental`);
    }
    if (device.rank !== undefined) requireInteger(device, "rank", 1);
    for (const field of ["flash_bytes", "maximum_code_bytes", "idata_bytes", "xdata_bytes", "edata_bytes", "max_io", "default_clock_hz"]) {
      requireInteger(device, field, field === "flash_bytes" || field === "maximum_code_bytes" || field === "default_clock_hz" ? 1 : 0);
    }
    for (const field of ["reserved_flash_bytes", "usb_ram_bytes", "physical_io"]) {
      if (device[field] !== undefined) requireInteger(device, field);
    }
    if (typeof device.package_dependent !== "boolean") {
      throw new Error(`package_dependent must be boolean for ${device.model}`);
    }
    if (!Array.isArray(device.memory_models) || device.memory_models.length === 0 ||
        device.memory_models.some((model) => typeof model !== "string" || !/^[a-z][a-z0-9_]*$/.test(model)) ||
        new Set(device.memory_models).size !== device.memory_models.length ||
        !device.memory_models.includes(device.default_memory_model)) {
      throw new Error(`invalid memory models for ${device.model}`);
    }
    if (!Array.isArray(device.clock_options_hz) || device.clock_options_hz.length === 0 ||
        device.clock_options_hz.some((hz) => !Number.isInteger(hz) || hz <= 0) ||
        new Set(device.clock_options_hz).size !== device.clock_options_hz.length ||
        new Set(device.clock_options_hz.map(clockId)).size !== device.clock_options_hz.length ||
        !device.clock_options_hz.includes(device.default_clock_hz)) {
      throw new Error(`invalid clock options for ${device.model}`);
    }
    if (device.experimental_targets !== undefined &&
        (!Array.isArray(device.experimental_targets) ||
         device.experimental_targets.some((target) => !["mcs51", "mcs251"].includes(target)) ||
         new Set(device.experimental_targets).size !== device.experimental_targets.length)) {
      throw new Error(`invalid experimental targets for ${device.model}`);
    }
    if (!isObject(device.capabilities) ||
        !Array.isArray(device.capabilities.ports) ||
        device.capabilities.ports.length === 0 ||
        device.capabilities.ports.some((port) => !Number.isInteger(port) || port < 0 || port > 7) ||
        new Set(device.capabilities.ports).size !== device.capabilities.ports.length ||
        typeof device.capabilities.port_mode !== "boolean" ||
        typeof device.capabilities.timer1_1t !== "boolean" ||
        (device.capabilities.uart1 !== undefined &&
         typeof device.capabilities.uart1 !== "boolean")) {
      throw new Error(`invalid capabilities for ${device.model}`);
    }
    if (![0, 1, 2, 3].every((port) => device.capabilities.ports.includes(port))) {
      throw new Error(`${device.model} capabilities must include core ports 0 through 3`);
    }
    coreFamilyName(device);
    const variant = variantName(device);
    if (ids.has(device.id) || models.has(device.model) || macros.has(device.macro) || variants.has(variant)) {
      throw new Error(`duplicate id, model, macro, or variant for ${device.model}`);
    }
    ids.add(device.id);
    models.add(device.model);
    macros.add(device.macro);
    variants.add(variant);
    if (!Array.isArray(device.port_masks) || device.port_masks.length !== 8 ||
        device.port_masks.some((mask) => !Number.isInteger(mask) || mask < 0 || mask > 255)) {
      throw new Error(`invalid port masks for ${device.model}`);
    }
    const bonded = device.port_masks.reduce((total, mask) => total + popcount(mask), 0);
    if (bonded !== device.max_io) {
      throw new Error(`${device.model} masks contain ${bonded} pins, expected ${device.max_io}`);
    }
    const aliasGroups = pinAliasGroups(device);
    if (!Array.isArray(aliasGroups) ||
        aliasGroups.some((group) => !Array.isArray(group) || group.length !== 2 ||
          group.some((pin) => typeof pin !== "string"))) {
      throw new Error(`invalid physical pin alias groups for ${device.model}`);
    }
    const aliasedPins = new Set();
    let aliasReduction = 0;
    for (const group of aliasGroups) {
      if (new Set(group).size !== group.length) {
        throw new Error(`duplicate pin inside a physical alias group for ${device.model}`);
      }
      for (const pin of group) {
        const match = /^P([0-7])\.([0-7])$/.exec(pin);
        if (match === null ||
            (device.port_masks[Number(match[1])] & (1 << Number(match[2]))) === 0) {
          throw new Error(`invalid or unbonded physical pin alias ${pin} for ${device.model}`);
        }
        if (aliasedPins.has(pin)) {
          throw new Error(`physical pin alias ${pin} occurs in multiple groups for ${device.model}`);
        }
        aliasedPins.add(pin);
      }
      aliasReduction += group.length - 1;
    }
    if (physicalIoCount(device) !== device.max_io - aliasReduction) {
      throw new Error(`${device.model} physical_io does not match its logical masks and alias groups`);
    }
    if (device.pin_selector !== undefined && !PIN_SELECTORS.has(device.pin_selector)) {
      throw new Error(`invalid startup pin selector for ${device.model}`);
    }
    if (device.pin_selector === "pswx1_bit0_clear_for_p5_4" &&
        (device.family !== "AI8H" || (device.port_masks[5] & 0x10) === 0 ||
         (device.port_masks[1] & 0x04) !== 0)) {
      throw new Error(`${device.model} P_SWX1 selector must canonicalize P1.2 as bonded P5.4 on AI8H`);
    }
    for (let port = 0; port < 8; port += 1) {
      if (device.port_masks[port] !== 0 && !device.capabilities.ports.includes(port)) {
        throw new Error(`${device.model} has bonded P${port} pins but no P${port} capability`);
      }
    }
    if (device.adc !== false && !isObject(device.adc)) {
      throw new Error(`adc must be false or an object for ${device.model}`);
    }
    if (device.adc !== false) {
      const layout = ADC_LAYOUTS[device.adc.layout];
      if (layout === undefined ||
          !layout.resolutions.includes(device.adc.resolution_bits) ||
          !isObject(device.adc.channels) ||
          Object.keys(device.adc.channels).length === 0) {
        throw new Error(`invalid ADC layout, resolution, or channels for ${device.model}`);
      }
      const channels = new Set();
      for (const [pin, channel] of adcEntries(device)) {
        const match = /^P([0-7])\.([0-7])$/.exec(pin);
        if (match === null || !Number.isInteger(channel) || channel < 0 || channel > 14) {
          throw new Error(`invalid ADC route ${pin} -> ${channel} for ${device.model}`);
        }
        const port = Number(match[1]);
        const bit = Number(match[2]);
        if ((device.port_masks[port] & (1 << bit)) === 0) {
          throw new Error(`${device.model} ADC route ${pin} is not present in its port mask`);
        }
        if (channels.has(channel)) {
          throw new Error(`${device.model} maps ADC channel ${channel} more than once`);
        }
        if (layout.p1Only && (port !== 1 || channel !== bit)) {
          throw new Error(`${device.model} legacy ADC routes must be P1.x -> channel x`);
        }
        channels.add(channel);
      }
      if (layout.p1Only && adcEntries(device).length !== 8) {
        throw new Error(`${device.model} legacy ADC layout must expose all eight P1 channels`);
      }
    }
    if (device.maximum_code_bytes > device.flash_bytes) {
      throw new Error(`maximum code exceeds flash for ${device.model}`);
    }
  }
  return data;
}

function variantName(device) {
  return device.model.replaceAll("-", "_");
}

function clockId(hz) {
  if (hz === 11059200) return "11m0592";
  if (hz % 1000000 === 0) return `${hz / 1000000}m`;
  return String(hz);
}

function clockLabel(hz) {
  if (hz === 11059200) return "11.0592 MHz";
  return `${hz / 1000000} MHz`;
}

function renderBoards(devices) {
  const lines = [
    "# Generated by tools/variants/generate.mjs; edit devices.json instead.",
    "# Bare-MCU variants use maximum logical port masks. Verify the selected package pinout.",
    "",
    "menu.clock=CPU clock (must match ISP configuration)",
    "menu.machine=STC89 machine cycle (must match ISP configuration)",
    "menu.memory=SDCC memory model",
    "menu.execution=Execution mode",
    "",
  ];
  for (const device of devices) {
    const board = device.id;
    let display = device.model;
    if (device.target === "mcs251") display += " (experimental MCS251)";
    const defaultTarget = device.target === "dual" ? "mcs51" : device.target;
    lines.push(
      `#################### ${device.model} ####################`,
      `${board}.name=${display}`,
      "",
      `${board}.build.core=STC`,
      `${board}.build.board=${device.macro}`,
      `${board}.build.mcu_macro=${device.macro}`,
      `${board}.build.variant=${variantName(device)}`,
      `${board}.build.sdk_family=${device.family}`,
      `${board}.build.f_cpu=${device.default_clock_hz}L`,
      `${board}.build.memory_model=${device.default_memory_model}`,
      `${board}.build.target=-m${defaultTarget}`,
      `${board}.build.mode_flags=-DSTC_EXECUTION_MODE_${defaultTarget.toUpperCase()}`,
      `${board}.build.core_flags=${renderCoreFlags(device)}`,
      `${board}.build.timer_flags=${device.family.startsWith("STC89") ? "-DSTC_TIMER0_CLOCK_DIVIDER=12UL -DSTC_SERIAL_TIMER1_CLOCK_DIVIDER=12UL" : ""}`,
      `${board}.upload.maximum_size=${device.maximum_code_bytes}`,
      `${board}.upload.maximum_idata_size=${device.idata_bytes}`,
      `${board}.upload.maximum_xdata_size=${device.xdata_bytes}`,
      `${board}.upload.maximum_edata_size=${device.edata_bytes}`,
      "",
    );

    if (device.target === "dual") {
      lines.push(
        `${board}.menu.execution.mcs51=8051 compatible / SDCC MCS51 (default)`,
        `${board}.menu.execution.mcs51.build.target=-mmcs51`,
        `${board}.menu.execution.mcs51.build.mode_flags=-DSTC_EXECUTION_MODE_MCS51`,
        `${board}.menu.execution.mcs251=32-bit / experimental SDCC MCS251`,
        `${board}.menu.execution.mcs251.build.target=-mmcs251`,
        `${board}.menu.execution.mcs251.build.mode_flags=-DSTC_EXECUTION_MODE_MCS251`,
        "",
      );
    }

    if (device.family.startsWith("STC89")) {
      lines.push(
        `${board}.menu.machine.12t=12T (default)`,
        `${board}.menu.machine.12t.build.timer_flags=-DSTC_TIMER0_CLOCK_DIVIDER=12UL -DSTC_SERIAL_TIMER1_CLOCK_DIVIDER=12UL`,
        `${board}.menu.machine.6t=6T`,
        `${board}.menu.machine.6t.build.timer_flags=-DSTC_TIMER0_CLOCK_DIVIDER=6UL -DSTC_SERIAL_TIMER1_CLOCK_DIVIDER=6UL`,
        "",
      );
    }

    for (const model of device.memory_models) {
      const suffix = model === device.default_memory_model ? " (default)" : "";
      lines.push(
        `${board}.menu.memory.${model}=${model[0].toUpperCase()}${model.slice(1)}${suffix}`,
        `${board}.menu.memory.${model}.build.memory_model=${model}`,
      );
    }
    lines.push("");

    for (const hz of device.clock_options_hz) {
      const suffix = hz === device.default_clock_hz ? " (default)" : "";
      const option = clockId(hz);
      lines.push(
        `${board}.menu.clock.${option}=${clockLabel(hz)}${suffix}`,
        `${board}.menu.clock.${option}.build.f_cpu=${hz}L`,
      );
    }
    lines.push("", "");
  }
  return `${lines.join("\n").trimEnd()}\n`;
}

function renderCommonHeader() {
  const pins = [];
  for (let port = 0; port < 8; port += 1) {
    for (let bit = 0; bit < 8; bit += 1) {
      pins.push(`#define P${port}_${bit} STC_PORT_PIN(${port}, ${bit})`);
    }
  }
  return `// Generated support header. Pin encoding is kept compatible with the original core.
#ifndef STC_VARIANT_PINS_COMMON_H
#define STC_VARIANT_PINS_COMMON_H

#ifndef NOT_A_PIN
#define NOT_A_PIN 0xFF
#endif
#ifndef NOT_A_PORT
#define NOT_A_PORT 0xFF
#endif
#ifndef NOT_AN_ANALOG_INPUT
#define NOT_AN_ANALOG_INPUT 0xFF
#endif
#ifndef NOT_AN_ADC_CHANNEL
#define NOT_AN_ADC_CHANNEL 0xFF
#endif
#define STC_PORT_PIN(port, bit) ((((port) & 0x07) << 4) | ((bit) & 0x07))
#define STC_PIN_PORT(pin) (((pin) == NOT_A_PIN) ? NOT_A_PORT : (((pin) >> 4) & 0x0F))
#define STC_PIN_BIT(pin) ((pin) & 0x07)
#define STC_PIN_BIT_MASK(pin) \
  (((pin) == NOT_A_PIN || (((pin) & 0x0F) > 7)) ? 0U : (1U << STC_PIN_BIT(pin)))
#define STC_PIN_ENCODING_LIMIT 0x78
#define STC_NUM_PIN_CODES STC_PIN_ENCODING_LIMIT

${pins.join("\n")}

#define LED_BUILTIN NOT_A_PIN
#define NUM_DIGITAL_PINS STC_NUM_PIN_CODES
#ifndef NUM_ANALOG_INPUTS
# define NUM_ANALOG_INPUTS 0
#endif
#ifndef analogInputToDigitalPin
# define analogInputToDigitalPin(index) (NOT_A_PIN)
#endif
#ifndef digitalPinToAnalogInput
# define digitalPinToAnalogInput(pin) (NOT_AN_ANALOG_INPUT)
#endif
#ifndef STC_VARIANT_ADC_PIN_TO_CHANNEL
# define STC_VARIANT_ADC_PIN_TO_CHANNEL(pin) (NOT_AN_ADC_CHANNEL)
#endif
#ifndef STC_VARIANT_FIRST_ANALOG_PIN
# define STC_VARIANT_FIRST_ANALOG_PIN NOT_A_PIN
#endif
#ifndef STC_VARIANT_LAST_ANALOG_PIN
# define STC_VARIANT_LAST_ANALOG_PIN NOT_A_PIN
#endif
#ifndef STC_VARIANT_PINS_SHARE_PHYSICAL_PAD
# define STC_VARIANT_PINS_SHARE_PHYSICAL_PAD(left, right) (0)
#endif
#ifndef STC_VARIANT_PHYSICAL_ALIAS
# define STC_VARIANT_PHYSICAL_ALIAS(pin) (NOT_A_PIN)
#endif
#ifndef digitalPinsSharePhysicalPad
# define digitalPinsSharePhysicalPad(left, right) \
    STC_VARIANT_PINS_SHARE_PHYSICAL_PAD((left), (right))
#endif
#ifndef digitalPinToPhysicalAlias
# define digitalPinToPhysicalAlias(pin) STC_VARIANT_PHYSICAL_ALIAS(pin)
#endif

#define PIN_SERIAL_RX P3_0
#define PIN_SERIAL_TX P3_1
#define PIN_WIRE_SDA P3_2
#define PIN_WIRE_SCL P3_3
#define SDA PIN_WIRE_SDA
#define SCL PIN_WIRE_SCL

#if (PIN_VALID_MASK_P3 & 0x30U) == 0x30U
# define PIN_SPI_MOSI P3_2
# define PIN_SPI_MISO P3_3
# define PIN_SPI_SCK  P3_4
# define PIN_SPI_SS   P3_5
#else
/* STC8G1K08A exposes only P3.0..P3.3 plus P5.4/P5.5. */
# define PIN_SPI_MOSI P3_2
# define PIN_SPI_MISO P3_3
# define PIN_SPI_SCK  P5_4
# define PIN_SPI_SS   P5_5
#endif
#define MOSI PIN_SPI_MOSI
#define MISO PIN_SPI_MISO
#define SCK  PIN_SPI_SCK
#define SS   PIN_SPI_SS

#ifndef digitalPinToPort
#define digitalPinToPort(pin) STC_PIN_PORT(pin)
#endif
#ifndef digitalPinToBitMask
#define digitalPinToBitMask(pin) STC_PIN_BIT_MASK(pin)
#endif

#endif
`;
}

function renderVariantHeader(device) {
  const guard = `ARDUINO_VARIANT_${device.macro}_H`;
  const masks = device.port_masks
    .map((mask, port) => `#define PIN_VALID_MASK_P${port} 0x${mask.toString(16).padStart(2, "0").toUpperCase()}U`)
    .join("\n");
  const entries = adcEntries(device);
  const analogAliases = entries
    .map(([pin], index) => `#define A${index} ${pinMacro(pin)}`)
    .join("\n");
  const analogDefinitions = [
    `#define STC_VARIANT_HAS_ADC ${device.adc === false ? 0 : 1}`,
    `#define STC_VARIANT_ADC_LAYOUT ${adcLayoutId(device)}U`,
    `#define STC_VARIANT_ADC_NATIVE_BITS ${device.adc === false ? 0 : device.adc.resolution_bits}U`,
    `#define STC_VARIANT_ADC_BITS STC_VARIANT_ADC_NATIVE_BITS`,
    `#define STC_VARIANT_ADC_CHANNEL_COUNT ${entries.length}U`,
    `#define NUM_ANALOG_INPUTS ${entries.length}`,
    analogAliases,
    `#define STC_VARIANT_FIRST_ANALOG_PIN ${entries.length === 0 ? "NOT_A_PIN" : "A0"}`,
    `#define STC_VARIANT_LAST_ANALOG_PIN ${entries.length === 0 ? "NOT_A_PIN" : `A${entries.length - 1}`}`,
    renderMapMacro("analogInputToDigitalPin", "index",
      entries.map(([pin], index) => [`${index}U`, pinMacro(pin)]), "NOT_A_PIN"),
    renderMapMacro("digitalPinToAnalogInput", "pin",
      entries.map(([pin], index) => [pinMacro(pin), `${index}U`]), "NOT_AN_ANALOG_INPUT"),
    renderMapMacro("STC_VARIANT_ADC_PIN_TO_CHANNEL", "pin",
      entries.map(([pin, channel]) => [pinMacro(pin), `${channel}U`]), "NOT_AN_ADC_CHANNEL"),
  ].filter((line) => line !== "").join("\n");
  return `// Generated by tools/variants/generate.mjs; edit devices.json instead.
#ifndef ${guard}
#define ${guard}

#define STC_VARIANT_MODEL "${device.model}"
#define STC_VARIANT_FAMILY "${device.family}"
#define STC_FLASH_BYTES ${device.flash_bytes}UL
#define STC_MAXIMUM_CODE_BYTES ${device.maximum_code_bytes}UL
#define STC_IDATA_BYTES ${device.idata_bytes}U
#define STC_XDATA_BYTES ${device.xdata_bytes}UL
#define STC_EDATA_BYTES ${device.edata_bytes}UL
#define STC_NUM_LOGICAL_DIGITAL_PINS ${device.max_io}U
#define STC_NUM_BONDED_DIGITAL_PINS ${physicalIoCount(device)}U
#define STC_VARIANT_PIN_ALIAS_GROUP_COUNT ${pinAliasGroups(device).length}U
#define STC_PINOUT_IS_PACKAGE_DEPENDENT ${device.package_dependent ? 1 : 0}
#define STC_VARIANT_HAS_UART1 ${device.capabilities.uart1 === false ? 0 : 1}
#define STC_VARIANT_SERIAL_BUFFERED_RX ${device.capabilities.uart1 !== false && device.maximum_code_bytes > 2048 ? 1 : 0}
#define STC_VARIANT_PINMUX_PSWX1_BIT0_CLEAR ${device.pin_selector === "pswx1_bit0_clear_for_p5_4" ? 1 : 0}
${masks}
${renderPinAliasMacro(device)}
${renderPhysicalAliasMacro(device)}
${analogDefinitions}

#include "../_common/pins_arduino_common.h"

#endif
`;
}

function renderVariantC() {
  return `// Generated by tools/variants/generate.mjs.
#include "Arduino.h"

void initVariant(void)
{
    /* Clock source/frequency is configured by the STC ISP options. */
}
`;
}

function renderMetadata(database, device) {
  const memory = {
    flash_bytes: device.flash_bytes,
    maximum_code_bytes: device.maximum_code_bytes,
    idata_bytes: device.idata_bytes,
    xdata_bytes: device.xdata_bytes,
    edata_bytes: device.edata_bytes,
  };
  if (device.reserved_flash_bytes !== undefined) memory.reserved_flash_bytes = device.reserved_flash_bytes;
  if (device.usb_ram_bytes !== undefined) memory.usb_ram_bytes = device.usb_ram_bytes;
  const adc = device.adc === false ? {
    supported: false,
    layout: "none",
    native_resolution_bits: 0,
    channels: [],
  } : {
    supported: true,
    layout: device.adc.layout,
    native_resolution_bits: device.adc.resolution_bits,
    arduino_default_resolution_bits: 10,
    reference_modes: ["DEFAULT"],
    channels: adcEntries(device).map(([pin, channel], index) => ({
      alias: `A${index}`,
      pin,
      channel,
    })),
  };
  const metadata = {
    schema_version: 2,
    as_of: database.as_of,
    model: device.model,
    family: device.family,
    selection: device.selection,
    popularity_rank: device.rank ?? null,
    compiler_target: device.target,
    experimental_compiler_target: device.target === "mcs251",
    experimental_compiler_targets:
      device.experimental_targets ?? (device.target === "mcs251" ? ["mcs251"] : []),
    memory,
    pinout: {
      encoding: "(port << 4) | bit",
      maximum_logical_io: device.max_io,
      maximum_physical_io: physicalIoCount(device),
      physical_alias_groups: pinAliasGroups(device),
      port_masks: device.port_masks.map((mask) => `0x${mask.toString(16).padStart(2, "0").toUpperCase()}`),
      package_dependent: device.package_dependent,
      startup_selector: device.pin_selector ?? null,
      analog_aliases_enabled: device.adc !== false,
    },
    peripherals: {
      uart1: device.capabilities.uart1 !== false,
      uart1_buffered_rx:
        device.capabilities.uart1 !== false && device.maximum_code_bytes > 2048,
      adc,
    },
    official_product_page: device.official_url,
    caveat: "Verify the concrete package pinout; unavailable pins are rejected by the core masks.",
  };
  if (device.data_quality_note !== undefined) metadata.data_quality_note = device.data_quality_note;
  return `${JSON.stringify(metadata, null, 2)}\n`;
}

function generatedFiles(database) {
  const outputs = new Map([
    [join(root, "boards.txt"), renderBoards(database.devices)],
    [join(root, "variants", "_common", "pins_arduino_common.h"), renderCommonHeader()],
  ]);
  for (const device of database.devices) {
    const directory = join(root, "variants", variantName(device));
    outputs.set(join(directory, "pins_arduino.h"), renderVariantHeader(device));
    outputs.set(join(directory, "variant.c"), renderVariantC());
    outputs.set(join(directory, "variant.json"), renderMetadata(database, device));
  }
  return outputs;
}

try {
  const database = loadDatabase();
  const stale = [];
  for (const [path, content] of generatedFiles(database)) {
    const current = existsSync(path) ? readFileSync(path, "utf8") : null;
    if (current === content) continue;
    if (check) {
      stale.push(relative(root, path).replaceAll("\\", "/"));
    } else {
      mkdirSync(dirname(path), { recursive: true });
      writeFileSync(path, content, "utf8");
      console.log(`generated ${relative(root, path).replaceAll("\\", "/")}`);
    }
  }
  if (stale.length) {
    console.error("generated files are stale:");
    for (const path of stale) console.error(`  ${path}`);
    process.exitCode = 1;
  }
} catch (error) {
  console.error(`error: ${error.message}`);
  process.exitCode = 2;
}
