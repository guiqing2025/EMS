// Standalone Kingdee beforeLogin credential encryption (from k3cloud.slogin.min.js)
function cloneObject(obj) {
  return JSON.parse(JSON.stringify(obj));
}

function base64Encode(value) {
  const text = typeof value === 'object' && value !== null ? JSON.stringify(value) : String(value);
  return Buffer.from(text, 'utf8').toString('base64');
}

function beforeLoginEncrypt(username, password) {
  let n = cloneObject({ u: username, p: password });
  n.zt = Math.random().toString().replace(/[0.]/g, '');
  n.rt = Date.now();
  n.cr = Math.random().toString().replace(/[0.]/g, '');
  const keys = Object.keys(n).sort();
  const ordered = {};
  for (const k of keys) ordered[k] = n[k];
  n = ordered;

  let o = base64Encode(n);
  let s = '';
  const l = o.length;
  const c = 95;
  const d = l % c;
  for (let u = 0; u < l; u++) {
    let g = o.charCodeAt(u);
    let p = g - d;
    if (p < 32) p += c;
    else if (p > 126) p -= c;
    s += String.fromCharCode(p);
  }
  return base64Encode(s);
}

const user = process.argv[2] || '07.01.0089';
const pass = process.argv[3] || 'DX123456**';
console.log(beforeLoginEncrypt(user, pass));
