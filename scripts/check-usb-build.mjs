// Build the checkout through Arduino's real board recipes in an isolated sketchbook.
// Usage: node scripts/check-usb-build.mjs [case-name ...]
import {spawnSync} from 'node:child_process';
import {mkdirSync,writeFileSync,existsSync,symlinkSync} from 'node:fs';
import {resolve,dirname,join} from 'node:path';
import {fileURLToPath} from 'node:url';
const root=resolve(dirname(fileURLToPath(import.meta.url)),'..');
const work=join(root,'.tmp/usb-cdc');
mkdirSync(join(work,'user/hardware/stc'),{recursive:true});
const platform=join(work,'user/hardware/stc/mcs251');
if(!existsSync(platform))symlinkSync(root,platform,process.platform==='win32'?'junction':'dir');
const config=join(work,'arduino-cli.yaml');
const data=process.env.ARDUINO_DIRECTORIES_DATA || (process.platform==='win32'
  ? join(process.env.LOCALAPPDATA,'Arduino15') : join(process.env.HOME,'.arduino15'));
writeFileSync(config,JSON.stringify({directories:{data,user:join(work,'user')}},null,2));
const cases=[
  ['g144-cdc','stc32g144k246:cdc=enabled','USB/CDCSerial'],
  ['g144-high-cdc','stc32g144k246:cdc=enabled,clock=48m,xram=high','USB/CDCSerial'],
  ['g144-echo','stc32g144k246:cdc=disabled','USB/CDCSerialEcho'],
  ['g144-composite','stc32g144k246:cdc=enabled','USB/CDCKeyboardMouse'],
  ['g12-cdc','stc32g12k128:cdc=enabled','USB/CDCSerial'],
  ['g12-small-cdc','stc32g12k64:cdc=enabled','USB/CDCSerial'],
  ['ai64-cdc','ai8051u_34k64:cdc=enabled','USB/CDCSerial'],
  ['ai32-cdc','ai8051u_34k32:cdc=enabled','USB/CDCSerial'],
  ['ai16-cdc','ai8051u_34k16:cdc=enabled','USB/CDCMinimal'],
  ['g12-hid','stc32g12k128:cdc=disabled','Mouse/ButtonMouse'],
  ['ai16-hid','ai8051u_34k16:cdc=disabled','HID/RawHID'],
  ['g12-raw-composite','stc32g12k128:cdc=enabled','HID/RawHID'],
  ['g8-uart','stc32g8k64',''],
];
let failed=false;
for(const [name,board,example] of cases){
  if(process.argv.length>2&&!process.argv.slice(2).includes(name))continue;
  const [library,sketch]=example.split('/');
  const path=example ? join(root,'libraries',library,'examples',sketch) : join(root,'examples/Blink');
  const result=spawnSync('arduino-cli',['compile','--config-file',config,'--fqbn',`stc:mcs251:${board}`,
    '--build-path',join(work,name),path],{encoding:'utf8',windowsHide:true,maxBuffer:64*1024*1024});
  const log=(result.stdout||'')+(result.stderr||'');writeFileSync(join(work,name+'.log'),log);
  console.log(`${name}: ${result.status===0?'PASS':'FAIL'}\n`+log.split(/\r?\n/)
    .filter(l=>/Sketch uses|Global variables|error [0-9]+:|error:|^stcxx:|Error during/.test(l)).join('\n'));
  if(result.status!==0)failed=true;
}
process.exitCode=failed?1:0;
