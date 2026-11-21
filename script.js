const State = {
  currentPortal: 'school',
  selectedSchoolRole: 'admin',
  selectedStudentTier: '11-12',
  mouseX: 0,
  mouseY: 0,
  reset: { portal: null, identifier: '', institution: '', fails: 0 }
};

const PORTAL_FORM = { school: 'form-school', parent: 'form-parent', student: 'form-student' };
const ALL_VIEWS = ['form-school', 'form-parent', 'form-student', 'view-forgot', 'view-reset', 'view-contact'];
const $ = (id) => document.getElementById(id);

// 1. 3D BACKGROUND (pure canvas, no libraries)
(function init3DCanvas() {
  const canvas = $('canvas3d');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  let width = (canvas.width = window.innerWidth);
  let height = (canvas.height = window.innerHeight);

  window.addEventListener('resize', () => {
    width = canvas.width = window.innerWidth;
    height = canvas.height = window.innerHeight;
  });
  window.addEventListener('mousemove', (e) => {
    State.mouseX = (e.clientX - width / 2) / (width / 2);
    State.mouseY = (e.clientY - height / 2) / (height / 2);
  });

  const particles = [];
  const count = window.innerWidth < 700 ? 90 : 190;
  for (let i = 0; i < count; i++) {
    particles.push({
      x: (Math.random() - 0.5) * 2000,
      y: (Math.random() - 0.5) * 2000,
      z: Math.random() * 1500,
      size: Math.random() * 2 + 1,
      speedZ: Math.random() * 1.5 + 0.5
    });
  }

  const cubeSize = 150;
  const vertices = [
    [-1, -1, -1], [1, -1, -1], [1, 1, -1], [-1, 1, -1],
    [-1, -1, 1], [1, -1, 1], [1, 1, 1], [-1, 1, 1]
  ].map(([x, y, z]) => ({ x: x * cubeSize, y: y * cubeSize, z: z * cubeSize }));
  const edges = [[0, 1], [1, 2], [2, 3], [3, 0], [4, 5], [5, 6], [6, 7], [7, 4], [0, 4], [1, 5], [2, 6], [3, 7]];
  let rotX = 0, rotY = 0;

  function colors() {
    const p = State.currentPortal;
    return {
      primary: p === 'parent' ? '#10b981' : p === 'student' ? '#a855f7' : '#00f0ff',
      secondary: p === 'parent' ? 'rgba(5,150,105,0.4)' : p === 'student' ? 'rgba(236,72,153,0.4)' : 'rgba(2,132,199,0.4)'
    };
  }

  function render3D() {
    ctx.clearRect(0, 0, width, height);
    const { primary, secondary } = colors();

    ctx.fillStyle = primary;
    for (const p of particles) {
      p.z -= p.speedZ;
      if (p.z <= 0) p.z = 1500;
      const scale = 300 / (300 + p.z);
      const px = (p.x + State.mouseX * 60) * scale + width / 2;
      const py = (p.y + State.mouseY * 60) * scale + height / 2;
      if (px > 0 && px < width && py > 0 && py < height) {
        ctx.beginPath();
        ctx.arc(px, py, p.size * scale, 0, Math.PI * 2);
        ctx.fill();
      }
    }

    rotX += 0.006 + State.mouseY * 0.01;
    rotY += 0.009 + State.mouseX * 0.01;
    const cx = width > 900 ? width * 0.22 : width * 0.5;
    const cy = height * 0.48;
    const projected = vertices.map(({ x, y, z }) => {
      const x1 = x * Math.cos(rotY) - z * Math.sin(rotY);
      const z1 = z * Math.cos(rotY) + x * Math.sin(rotY);
      const y2 = y * Math.cos(rotX) - z1 * Math.sin(rotX);
      const z2 = z1 * Math.cos(rotX) + y * Math.sin(rotX);
      const scale = 400 / (z2 + 500);
      return { x: x1 * scale + cx, y: y2 * scale + cy, scale };
    });

    ctx.lineWidth = 1.5;
    ctx.strokeStyle = secondary;
    for (const [a, b] of edges) {
      ctx.beginPath();
      ctx.moveTo(projected[a].x, projected[a].y);
      ctx.lineTo(projected[b].x, projected[b].y);
      ctx.stroke();
    }
    ctx.fillStyle = primary;
    for (const p of projected) {
      ctx.beginPath();
      ctx.arc(p.x, p.y, 4 * p.scale, 0, Math.PI * 2);
      ctx.fill();
    }
    requestAnimationFrame(render3D);
  }
  render3D();
})();

// 2. CARD TILT (small, so forms stay easy to use)
(function tilt() {
  const card = $('tiltCard');
  if (!card || window.matchMedia('(max-width: 900px)').matches) return;
  card.addEventListener('mousemove', (e) => {
    const r = card.getBoundingClientRect();
    const x = e.clientX - r.left, y = e.clientY - r.top;
    const rx = ((y - r.height / 2) / (r.height / 2)) * -3;
    const ry = ((x - r.width / 2) / (r.width / 2)) * 3;
    card.style.transform = `rotateX(${rx}deg) rotateY(${ry}deg)`;
    card.style.setProperty('--mouse-x', `${(x / r.width) * 100}%`);
    card.style.setProperty('--mouse-y', `${(y / r.height) * 100}%`);
  });
  card.addEventListener('mouseleave', () => { card.style.transform = ''; });
})();

// 3. VIEW + PORTAL SWITCHING
function showView(id) {
  ALL_VIEWS.forEach((v) => $(v)?.classList.toggle('hidden', v !== id));
}

function switchPortal(portal) {
  State.currentPortal = portal;
  const root = document.documentElement;
  ['school', 'parent', 'student'].forEach((p) => {
    $(`dock-${p}`)?.classList.toggle('active', p === portal);
    $(`copy-${p}`)?.classList.toggle('hidden', p !== portal);
  });
  showView(PORTAL_FORM[portal]);

  const theme = { school: ['🏫', 'Institutional ERP'], parent: ['👨‍👩‍👧', 'Parent Link Radar'], student: ['🚀', 'Adaptive Cosmos'] }[portal];
  for (const k of ['primary', 'secondary', 'glow', 'gradient']) {
    root.style.setProperty(`--theme-${k}`, `var(--${portal}-${k})`);
  }
  $('brandLogo').textContent = theme[0];
  $('brandBadge').textContent = theme[1];
}

function setSchoolRole(role) {
  State.selectedSchoolRole = role;
  ['admin', 'teacher', 'hod'].forEach((r) => $(`role-${r}`)?.classList.toggle('active', r === role));
}

function setParentAuthMode(mode) {
  const isOtp = mode === 'otp';
  $('p-mode-otp').classList.toggle('active', isOtp);
  $('p-mode-pwd').classList.toggle('active', !isOtp);
  $('p-view-otp').classList.toggle('hidden', !isOtp);
  $('p-view-pwd').classList.toggle('hidden', isOtp);
}

function setStudentTier(tier) {
  State.selectedStudentTier = tier;
  ['18', '910', '1112'].forEach((t) => $(`tier-${t}`)?.classList.toggle('active', t === tier.replace('-', '')));
  $('stream-selector-group').classList.toggle('hidden', tier !== '11-12');
}
setStudentTier('11-12');

function togglePw(btn) {
  const input = btn.parentElement.querySelector('input');
  const show = input.type === 'password';
  input.type = show ? 'text' : 'password';
  btn.textContent = show ? '🙈' : '👁️';
}

// 4. BACKEND CLIENT (same origin; the login lives in an HttpOnly cookie)
async function api(path, body) {
  let res;
  try {
    res = await fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  } catch {
    throw Object.assign(new Error("Can't reach the server. Is it running? (python server.py)"), { network: true });
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw Object.assign(new Error(data.error || 'Something went wrong'), { code: data.code });
  return data;
}

function setBusy(btn, busy) {
  if (!btn) return;
  btn.disabled = busy;
  btn.classList.toggle('loading', busy);
}

// 5. PARENT OTP
function setupOtpBoxes() {
  const boxes = [...document.querySelectorAll('.otp-box')];
  boxes.forEach((box, i) => {
    box.addEventListener('input', () => {
      box.value = box.value.replace(/\D/g, '').slice(-1);
      if (box.value && boxes[i + 1]) boxes[i + 1].focus();
    });
    box.addEventListener('keydown', (e) => {
      if (e.key === 'Backspace' && !box.value && boxes[i - 1]) boxes[i - 1].focus();
    });
    box.addEventListener('paste', (e) => {
      const digits = (e.clipboardData.getData('text') || '').replace(/\D/g, '').slice(0, 4);
      if (!digits) return;
      e.preventDefault();
      boxes.forEach((b, j) => (b.value = digits[j] || ''));
      boxes[Math.min(digits.length, 3)].focus();
    });
  });
}
setupOtpBoxes();

let otpTimer = null;
function startOtpCountdown(seconds = 30) {
  const btn = $('otp-btn'), label = $('otp-timer');
  clearInterval(otpTimer);
  let left = seconds;
  btn.disabled = true;
  const tick = () => {
    if (left <= 0) {
      clearInterval(otpTimer);
      btn.disabled = false;
      btn.textContent = 'Resend OTP';
      label.textContent = '';
      return;
    }
    btn.textContent = `Resend in ${left}s`;
    label.textContent = 'OTP valid for 5 minutes';
    left--;
  };
  tick();
  otpTimer = setInterval(tick, 1000);
}

async function requestOtp() {
  const mobile = $('p-mobile').value.replace(/\D/g, '');
  if (!/^[6-9]\d{9}$/.test(mobile)) return showToast('Check the number', 'Enter a valid 10-digit mobile number', true);
  try {
    const data = await api('/api/auth/parent/otp/request', { mobile });
    showToast('OTP requested', data.message);
    startOtpCountdown(30);
    document.querySelector('.otp-box').focus();
    if (data.dev_otp) {
      // Dev mode only: auto-fill so you can test without an SMS provider
      document.querySelectorAll('.otp-box').forEach((b, i) => (b.value = data.dev_otp[i] || ''));
    }
  } catch (err) {
    showToast('Could not send OTP', err.message, true);
  }
}

// 6. LOGIN
async function handleLoginSubmit(e, portal) {
  e.preventDefault();
  const btn = e.target.querySelector('button[type=submit]');
  try {
    let result;
    if (portal === 'school') {
      const code = $('s-code').value.trim(), identifier = $('s-id').value.trim(), password = $('s-pass').value;
      if (!code || !identifier || !password) throw new Error('Fill in the institution code, email/mobile and password');
      setBusy(btn, true);
      result = await api('/api/auth/school/login', { institution_code: code, identifier, password, role: State.selectedSchoolRole });
    } else if (portal === 'parent') {
      if (!$('p-view-otp').classList.contains('hidden')) {
        const mobile = $('p-mobile').value.replace(/\D/g, '');
        const otp = [...document.querySelectorAll('.otp-box')].map((b) => b.value).join('');
        if (!/^[6-9]\d{9}$/.test(mobile)) throw new Error('Enter a valid 10-digit mobile number');
        if (otp.length !== 4) throw new Error('Tap "Get OTP", then enter the 4-digit code');
        setBusy(btn, true);
        result = await api('/api/auth/parent/otp/verify', { mobile, otp });
      } else {
        const identifier = $('p-id').value.trim(), password = $('p-pass').value;
        if (!identifier || !password) throw new Error('Enter your email, mobile or admission number, and password');
        setBusy(btn, true);
        result = await api('/api/auth/parent/login', { identifier, password });
      }
    } else {
      const identifier = $('st-id').value.trim(), password = $('st-pass').value;
      if (!identifier || !password) throw new Error('Enter your roll no, handle, email or mobile, and password');
      setBusy(btn, true);
      result = await api('/api/auth/student/login', {
        identifier, password, tier: State.selectedStudentTier,
        stream: $('st-stream')?.value || ''
      });
    }
    showToast('Access granted', `Welcome, ${result.user.name}`);
    setTimeout(() => { window.location.href = result.redirect; }, 600);
  } catch (err) {
    showToast('Login failed', err.message, true);
    setBusy(btn, false);
  }
}

// 7. FORGOT PASSWORD
const FORGOT_TEXT = {
  school: { label: 'Registered Email or Mobile', ph: 'name@institution.edu.in or 10-digit mobile' },
  parent: { label: 'Registered Mobile or Email', ph: '10-digit mobile or email' },
  student: { label: 'Handle, Roll No, Email or Mobile', ph: 'e.g. ravi.sai or 10-digit mobile' }
};

function openForgot(portal) {
  const p = portal || State.reset.portal || State.currentPortal;
  State.reset = { portal: p, identifier: '', institution: '', fails: 0 };
  $('f-inst-group').classList.toggle('hidden', p !== 'school');
  $('f-id-label').textContent = FORGOT_TEXT[p].label;
  $('f-id').placeholder = FORGOT_TEXT[p].ph;
  // carry over what was typed on the login form
  const typed = { school: $('s-id'), parent: $('p-id'), student: $('st-id') }[p]?.value.trim() || '';
  $('f-id').value = typed;
  if (p === 'school') $('f-inst').value = $('s-code').value.trim();
  showView('view-forgot');
  $('f-id').focus();
}

async function sendResetCode(e) {
  e.preventDefault();
  const btn = e.target.querySelector('button[type=submit]');
  const identifier = $('f-id').value.trim();
  const institution = $('f-inst').value.trim();
  if (!identifier) return showToast('Missing details', 'Enter your registered email or mobile', true);
  if (State.reset.portal === 'school' && !institution) return showToast('Missing details', 'Enter your institution code', true);
  setBusy(btn, true);
  try {
    const data = await api('/api/auth/reset/request', {
      portal: State.reset.portal, identifier, institution_code: institution
    });
    State.reset.identifier = identifier;
    State.reset.institution = institution;
    State.reset.fails = 0;
    $('r-code').value = '';
    $('r-new').value = '';
    $('r-new2').value = '';
    const note = $('dev-note');
    if (data.dev_otp) {
      $('r-code').value = data.dev_otp;
      note.textContent = `Test mode: the code is auto-filled (${data.dev_otp}). In real use it arrives by SMS or email.`;
      note.classList.remove('hidden');
    } else {
      note.classList.add('hidden');
    }
    $('reset-sub').textContent = data.message;
    showView('view-reset');
    $('r-new').focus();
  } catch (err) {
    if (err.code === 'contact_admin') openContact();
    else showToast('Could not send code', err.message, true);
  } finally {
    setBusy(btn, false);
  }
}

async function confirmReset(e) {
  e.preventDefault();
  const btn = e.target.querySelector('button[type=submit]');
  const otp = $('r-code').value.trim(), pw = $('r-new').value, pw2 = $('r-new2').value;
  if (!/^\d{6}$/.test(otp)) return showToast('Check the code', 'Enter the 6-digit code', true);
  if (pw.length < 8 || !/[A-Za-z]/.test(pw) || !/\d/.test(pw)) return showToast('Weak password', 'Use at least 8 characters with letters and numbers', true);
  if (pw !== pw2) return showToast('Passwords differ', 'The two passwords do not match', true);
  setBusy(btn, true);
  try {
    await api('/api/auth/reset/confirm', {
      portal: State.reset.portal, identifier: State.reset.identifier, institution_code: State.reset.institution,
      otp, new_password: pw
    });
    const portal = State.reset.portal;
    const id = State.reset.identifier;
    switchPortal(portal);
    const field = { school: $('s-id'), parent: $('p-id'), student: $('st-id') }[portal];
    if (field) field.value = id;
    if (portal === 'parent') setParentAuthMode('pwd');
    showToast('Password updated', 'Log in with your new password');
  } catch (err) {
    State.reset.fails++;
    if (err.code === 'contact_admin' || State.reset.fails >= 3) openContact();
    else showToast('Could not reset', err.message, true);
  } finally {
    setBusy(btn, false);
  }
}

function openContact() {
  $('toast')?.classList.remove('visible');
  showView('view-contact');
}
function backToLogin() { switchPortal(State.reset.portal || State.currentPortal); }

// 8. TOAST
let toastTimer = null;
function showToast(title, desc, isError = false) {
  const toast = $('toast');
  if (!toast) return;
  $('toastTitle').textContent = title;
  $('toastDesc').textContent = desc;
  $('toastIcon').textContent = isError ? '⚠️' : '✨';
  toast.classList.toggle('error', isError);
  toast.classList.add('visible');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.remove('visible'), 3600);
}

// open a portal straight from a link, e.g. index.html#parent
const startPortal = location.hash.replace('#', '');
if (PORTAL_FORM[startPortal]) switchPortal(startPortal);
