/**
 * Migu ddCalcu generator for live stream URL decryption.
 *
 * The latest playerVersion wasm may introduce incompatible imports.
 * We pin to a known-compatible wasm version while keeping the same
 * underlying encryption routine.
 */

const SECRET_KEY = 'J6XuCcCtPfVdSv6YUls4Jg==';

let wasmInstance = null;
let memoryP = null;
let memoryH = null;

function writeUtf8(str, offset, maxLen) {
    const encoded = new TextEncoder().encode(str);
    const safeLen = Math.max(0, maxLen - 1);
    for (let i = 0; i < encoded.length && i < safeLen; i++) {
        memoryP[offset + i] = encoded[i];
    }
    memoryP[offset + Math.min(encoded.length, safeLen)] = 0;
}

function readUtf8(offset) {
    let out = '';
    let i = 0;
    while (memoryP[offset + i]) {
        out += String.fromCharCode(memoryP[offset + i]);
        i += 1;
    }
    return out;
}

function importA(_e, t, r, n) {
    let sum = 0;
    for (let i = 0; i < r; i++) {
        const val = memoryH[(t + 4) >> 2];
        t += 8;
        sum += val;
    }
    memoryH[n >> 2] = sum;
    return 0;
}

function importB() {}
function importC() {}
function importD() { return 1; }

async function getPlayerVersion() {
    // 2026-03之后线上新版 wasm 与现有导入签名不兼容。
    // 使用已验证可用的稳定版本生成 ddCalcu。
    return 'v_20251124155500_63c16e66';
}

async function initWasm() {
    const playerVersion = await getPlayerVersion();
    const wasmUrl = `https://www.miguvideo.com/mgs/player/prd/${playerVersion}/dist/mgprtcl.wasm`;

    const wasmResp = await fetch(wasmUrl);
    if (!wasmResp.ok) {
        throw new Error(`Failed to download WASM: ${wasmResp.status}`);
    }

    const wasmBuffer = await wasmResp.arrayBuffer();
    const importObject = {
        a: {
            a: importA,
            b: importB,
            c: importC,
            d: importD,
        },
    };

    const { instance } = await WebAssembly.instantiate(wasmBuffer, importObject);
    wasmInstance = instance;

    const memory = wasmInstance.exports.e;
    memoryP = new Uint8Array(memory.buffer);
    memoryH = new Uint32Array(memory.buffer);
}

async function getDdCalcu(inputUrl) {
    if (!wasmInstance) {
        await initWasm();
    }

    const CallInterface1 = wasmInstance.exports.i;
    const CallInterface2 = wasmInstance.exports.j;
    const CallInterface3 = wasmInstance.exports.k;
    const CallInterface4 = wasmInstance.exports.l;
    const CallInterface6 = wasmInstance.exports.n;
    const CallInterface7 = wasmInstance.exports.o;
    const CallInterface8 = wasmInstance.exports.p;
    const CallInterface9 = wasmInstance.exports.q;
    const CallInterface10 = wasmInstance.exports.r;
    const CallInterface11 = wasmInstance.exports.s;
    const CallInterface14 = wasmInstance.exports.u;
    const malloc = wasmInstance.exports.v;

    const query = Object.fromEntries(new URL(inputUrl).searchParams.entries());

    const userid = query.userid || '';
    const timestamp = query.timestamp || '';
    const programId = query.ProgramID || '';
    const channelId = query.Channel_ID || '';
    const puData = query.puData || '';

    const pUserid = malloc(userid.length + 1);
    const pTimestamp = malloc(timestamp.length + 1);
    const pProgram = malloc(programId.length + 1);
    const pChannel = malloc(channelId.length + 1);
    const pPuData = malloc(puData.length + 1);
    const pSecret = malloc(SECRET_KEY.length + 1);

    const outFinal = malloc(128);
    const outToken = malloc(128);

    writeUtf8(userid, pUserid, userid.length + 1);
    writeUtf8(timestamp, pTimestamp, timestamp.length + 1);
    writeUtf8(programId, pProgram, programId.length + 1);
    writeUtf8(channelId, pChannel, channelId.length + 1);
    writeUtf8(puData, pPuData, puData.length + 1);
    writeUtf8(SECRET_KEY, pSecret, SECRET_KEY.length + 1);

    const ctx = CallInterface6();
    CallInterface1(ctx, pProgram, programId.length);
    CallInterface10(ctx, pTimestamp, timestamp.length);
    CallInterface9(ctx, pUserid, userid.length);
    CallInterface3(ctx, 0, 0);
    CallInterface11(ctx, 0, 0);
    CallInterface8(ctx, pPuData, puData.length);
    CallInterface2(ctx, pChannel, channelId.length);
    CallInterface14(ctx, pSecret, SECRET_KEY.length, outToken, 128);

    const token = readUtf8(outToken);
    const pToken = malloc(token.length + 1);
    writeUtf8(token, pToken, token.length + 1);

    CallInterface7(ctx, pToken, token.length);
    CallInterface4(ctx, outFinal, 128);

    return readUtf8(outFinal);
}

const url = process.argv[2];
if (!url) {
    console.error('Usage: node migu.js <source_url>');
    process.exit(1);
}

getDdCalcu(url)
    .then((result) => {
        console.log(result);
    })
    .catch((err) => {
        console.error(err);
        process.exit(1);
    });
