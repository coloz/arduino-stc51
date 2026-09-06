#!/usr/bin/env node

import fs from 'node:fs';
import path from 'node:path';

function fail(message) {
  throw new Error(message);
}

function parseArguments(argv) {
  const index = argv.indexOf('--build-dir');
  if (index < 0 || index + 1 >= argv.length) {
    fail('usage: check-mcs251-isr-context.mjs --build-dir <Arduino build>');
  }
  return path.resolve(argv[index + 1]);
}

function instructionsForFunction(filePath, symbol) {
  if (!fs.existsSync(filePath)) {
    fail(`generated assembly is missing: ${filePath}`);
  }
  const text = fs.readFileSync(filePath, 'utf8');
  const marker = `_${symbol}:`;
  const markerCount = text.split(marker).length - 1;
  if (markerCount !== 1) {
    fail(`${filePath}: expected exactly one function label ${marker}; ` +
      `found ${markerCount}`);
  }
  const start = text.indexOf(marker);
  const reti = text.indexOf('\n\treti', start);
  if (reti < 0) {
    fail(`${filePath}: ${symbol} has no RETI`);
  }
  return text.slice(start, reti + '\n\treti'.length)
    .split(/\r?\n/u)
    .map((line) => line.split(';', 1)[0].trim().toLowerCase()
      .replace(/\s+/gu, ' '))
    .filter(Boolean);
}

function requireOrdered(symbol, instructions, expected) {
  let cursor = -1;
  for (const token of expected) {
    cursor = instructions.indexOf(token, cursor + 1);
    if (cursor < 0) {
      fail(`${symbol}: missing or out-of-order instruction ${JSON.stringify(token)}`);
    }
  }
}

function countSequence(instructions, expected) {
  let count = 0;
  for (let index = 0; index <= instructions.length - expected.length; index += 1) {
    if (expected.every((token, offset) => instructions[index + offset] === token)) {
      count += 1;
    }
  }
  return count;
}

const buildDirectory = parseArguments(process.argv.slice(2));
const core = path.join(buildDirectory, 'core');
const checks = [
  ['stc_timer0_isr', 'wiring.c.asm', 'anl _tcon,#0xdf'],
  ['stc_uart1_isr', 'HardwareSerial_isr.c.asm', 'mov a,_scon'],
  ['stc_external0_isr', 'WInterrupts_isr.c.asm',
    'mov dptr,#_stc_external_callbacks'],
  ['stc_external1_isr', 'WInterrupts_isr.c.asm',
    'mov dptr,#(_stc_external_callbacks + 0x0003)'],
];

for (const [symbol, fileName, firstCOperation] of checks) {
  const instructions = instructionsForFunction(path.join(core, fileName), symbol);
  requireOrdered(symbol, instructions, [
    'push dpxl',
    'push dr24',
    'push dr28',
    firstCOperation,
    'pop dr28',
    'pop dr24',
    'pop dpxl',
    'reti',
  ]);

  for (const sequence of [
    ['push dpxl', 'push dr24', 'push dr28'],
    ['pop dr28', 'pop dr24', 'pop dpxl'],
  ]) {
    const count = countSequence(instructions, sequence);
    if (count !== 1) {
      fail(`${symbol}: expected exactly one ${JSON.stringify(sequence)}`);
    }
  }
}

process.stdout.write(
  'MCS251 ISR extended context: PASS (Timer0, UART1, INT0, INT1)\n',
);
