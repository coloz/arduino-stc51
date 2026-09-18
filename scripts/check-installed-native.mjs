// Exercise the actual installed Arduino recipes and its ordinary build cache.
import {spawnSync} from 'node:child_process';
import {mkdirSync,writeFileSync} from 'node:fs';
import {resolve,dirname,join} from 'node:path';
import {fileURLToPath} from 'node:url';
const root=resolve(dirname(fileURLToPath(import.meta.url)),'..');
const work=join(root,'.tmp/native-driver');mkdirSync(work,{recursive:true});
const env={...process.env};
for(const key of ['STCXX_PLATFORM_ROOT','STCXX_TOOLS_ROOT','STCXX_CPP_TOOLS_ROOT','STCXX_SDCC'])delete env[key];
const cases=[
  ['installed-blink-cold','examples/Blink','stc32g12k128',true],
  ['installed-blink-warm','examples/Blink','stc32g12k128',false],
  ['installed-mouse','libraries/Mouse/examples/ButtonMouse','stc32g12k128',false],
  ['installed-keyboard','libraries/Keyboard/examples/KeyboardMouse','stc32g12k128',false],
  ['installed-rawhid','libraries/HID/examples/RawHID','ai8051u_34k16',false],
];
for(const [name,sketch,board,clean] of cases){
  const result=spawnSync('arduino-cli',['compile','--verbose','--fqbn',`stc:mcs251:${board}`,...(clean?['--clean']:[]),resolve(root,sketch)],{encoding:'utf8',env,windowsHide:true,maxBuffer:64*1024*1024});
  const log=(result.stdout||'')+(result.stderr||'');writeFileSync(join(work,name+'.log'),log);
  if(result.status!==0){console.error(log.split(/\r?\n/).filter(l=>/: (?:fatal )?error[: ]|^stcxx:|^Error during/.test(l)).join('\n'));throw new Error(`${name}: failed; see ${join(work,name+'.log')}`);}
  if(/powershell|python|stc-windows|stcxx-cli\.sh/i.test(log))throw new Error(`${name}: legacy command appeared`);
  if(!log.includes('stcxx.exe')||!log.includes('STCXX_NATIVE_LINK=PASS'))throw new Error(`${name}: missing native link evidence`);
  console.log(name+': PASS\n'+log.split(/\r?\n/).filter(l=>/^Sketch uses|^Global variables|Using precompiled core|Using previously compiled/.test(l)).join('\n'));
}
