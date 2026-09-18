// Install already validated native payloads. The old installation is retained
// outside Arduino's package directory; no shell or interpreter is launched.
import {cpSync,existsSync,mkdirSync,readFileSync,readdirSync,renameSync,writeFileSync} from 'node:fs';
import {resolve,dirname,join,relative,isAbsolute,sep} from 'node:path';
import {randomUUID} from 'node:crypto';
const [platformInput,toolchainInput,dataInput]=process.argv.slice(2);
if(!platformInput||!toolchainInput)throw new Error('Usage: node scripts/install-native-driver.mjs <native-platform-directory> <native-toolchain-directory> [Arduino15-directory]');
const platform=resolve(platformInput),toolchain=resolve(toolchainInput);
const data=resolve(dataInput||join(process.env.LOCALAPPDATA,'Arduino15'));
const version=readFileSync(join(platform,'platform.txt'),'utf8').match(/^version=([\d.]+)$/m)?.[1];
if(!version||!existsSync(join(platform,'tools/stcxx-driver/stcxx.exe')))throw new Error('Missing Windows native platform');
if(JSON.parse(readFileSync(join(toolchain,'toolchain.json'),'utf8')).execution!=='native')throw new Error('Toolchain is not a native payload');
function checkPayload(root){
  for(const entry of readdirSync(root,{withFileTypes:true})){
    const path=join(root,entry.name);
    if(entry.isSymbolicLink())throw new Error(`Unexpected link: ${path}`);
    if(/python|\.(py|pyc|pyd|ps1|sh)$/i.test(entry.name))throw new Error(`Interpreter payload: ${path}`);
    if(entry.isDirectory())checkPayload(path);
  }
}
checkPayload(platform);checkPayload(toolchain);
const id=randomUUID();
const backup=resolve(dirname(data),'Arduino15-native-backups',id);
const destinations=[join(data,'packages/stc/hardware/mcs251',version),join(data,'packages/stc/tools/stcxx-toolchain/0.1.0')];
const sources=[platform,toolchain];
// Every directory rename is constrained to the explicitly selected Arduino
// data directory or this unique sibling backup directory.
function within(root,path){const rel=relative(root,resolve(path));if(!rel||rel.startsWith('..'+sep)||rel==='..'||isAbsolute(rel))throw new Error(`Unsafe installation path: ${path}`);}
const operations=destinations.map((destination,i)=>{
  within(data,destination);
  if(!existsSync(destination))throw new Error(`Install the published platform first: ${destination}`);
  const saved=join(backup,i===0?'platform':'toolchain');within(backup,saved);
  return {source:sources[i],destination,staged:destination+'.native-'+id,saved};
});
mkdirSync(backup,{recursive:true});
for(const op of operations){within(data,op.staged);cpSync(op.source,op.staged,{recursive:true,errorOnExist:true,force:false});}
const done=[];
try{
  for(const op of operations){
    renameSync(op.destination,op.saved);
    try{renameSync(op.staged,op.destination);}catch(error){renameSync(op.saved,op.destination);throw error;}
    done.push(op);
  }
}catch(error){
  for(const op of done.reverse()){renameSync(op.destination,op.staged);renameSync(op.saved,op.destination);}
  throw error;
}
writeFileSync(join(backup,'installation.json'),JSON.stringify({date:new Date().toISOString(),operations},null,2)+'\n');
console.log(JSON.stringify({platform:destinations[0],toolchain:destinations[1],backup},null,2));
