import {openSync,closeSync,unlinkSync} from 'node:fs';
import {build} from 'vite';
const lock='.build.lock';
let fd;
try { fd=openSync(lock,'wx'); }
catch { throw new Error('Another board build is running. Wait for it to finish before rebuilding.'); }
try { await build(); }
finally { closeSync(fd);unlinkSync(lock); }
