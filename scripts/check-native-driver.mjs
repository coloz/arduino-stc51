// Run with node; the compiler-under-test is a native executable, with no interpreter.
import { spawnSync } from 'node:child_process';
import { mkdirSync, writeFileSync } from 'node:fs';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
const platform=resolve(dirname(fileURLToPath(import.meta.url)),'..');
const [name='blink', sketch='examples/Blink', board='stc32g12k128', ...extra]=process.argv.slice(2);
const native=resolve(platform,'tools/stcxx-driver/target/release/stcxx.exe');
const properties={'compiler.driver':native,'compiler.driver.windows':native,'compiler.shell.cmd':native,'compiler.shell.args':`--platform "${platform}"`,'compiler.wrapper.compile':'compile','compiler.wrapper.archive':'archive','compiler.wrapper.link':'link','compiler.wrapper.size':'size'};
const work=resolve(platform,'.tmp/native-driver',name);mkdirSync(work,{recursive:true});
const argv=['compile','--fqbn',`stc:mcs251:${board}`,'--build-path',work,'--libraries',resolve(platform,'libraries'),...Object.entries(properties).flatMap(([k,v])=>['--build-property',`${k}=${v}`]),...extra,resolve(platform,sketch)];
const result=spawnSync('arduino-cli',argv,{encoding:'utf8',maxBuffer:64*1024*1024,windowsHide:true});
const log=(result.stdout||'')+(result.stderr||'');writeFileSync(work+'.log',log);console.log(log.split(/\r?\n/).filter(l=>/Sketch uses|Global variables|error:|stcxx:|warning [0-9]|STCXX_NATIVE_LINK|Error during/.test(l)).slice(-20).join('\n'));console.log(`status=${result.status} log=${work}.log`);if(result.error)console.error(result.error);process.exit(result.status??1);
