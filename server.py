#!/usr/bin/env python3
"""VidyaSetu 360 backend - pure Python standard library (no pip install needed).

Run:  python server.py        (then open http://localhost:3000)
Env:  PORT=3000  DEV=1 (default; prints OTPs, allows http cookies)  SECRET_KEY=...
"""
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import threading
import time
from datetime import date, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

BASE = Path(__file__).resolve().parent
DB_PATH = BASE / "vidyasetu.db"
PORT = int(os.environ.get("PORT", "3000"))
DEV = os.environ.get("DEV", "1") == "1"
TOKEN_TTL = 8 * 3600
OTP_TTL = 300
PBKDF2_ITERS = 200_000

# Only these files are ever served, so server.py / the database / .secret stay private.
STATIC = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/dashboard.html": ("dashboard.html", "text/html; charset=utf-8"),
    "/style.css": ("style.css", "text/css; charset=utf-8"),
    "/script.js": ("script.js", "application/javascript; charset=utf-8"),
}


def load_secret():
    env = os.environ.get("SECRET_KEY")
    if env:
        return env.encode()
    f = BASE / ".secret"
    if not f.exists():
        f.write_text(secrets.token_hex(32))
    return f.read_text().strip().encode()


SECRET = load_secret()


# ---------------------------------------------------------------- security helpers
def hash_pw(password, salt=None):
    salt = salt or secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), PBKDF2_ITERS)
    return f"{salt}${h.hex()}"


def verify_pw(password, stored):
    salt, _, h = stored.partition("$")
    cand = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), PBKDF2_ITERS).hex()
    return hmac.compare_digest(cand, h)


DUMMY_HASH = hash_pw("dummy-password-for-timing")  # keeps timing equal when user is unknown


def b64e(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def b64d(s):
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def make_token(payload):
    payload = dict(payload, exp=int(time.time()) + TOKEN_TTL)
    body = b64e(json.dumps(payload, separators=(",", ":")).encode())
    sig = b64e(hmac.new(SECRET, body.encode(), hashlib.sha256).digest())
    return f"{body}.{sig}"


def read_token(tok):
    try:
        body, sig = tok.split(".")
        good = b64e(hmac.new(SECRET, body.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, good):
            return None
        data = json.loads(b64d(body))
        return data if data["exp"] > time.time() else None
    except Exception:
        return None


_attempts = {}
_attempts_lock = threading.Lock()


def check_limit(key, limit=5, window=600, code=None):
    now = time.time()
    with _attempts_lock:
        recent = [t for t in _attempts.get(key, []) if now - t < window]
        _attempts[key] = recent
        if len(recent) >= limit:
            raise ApiError(429, "Too many attempts. Please wait a few minutes and try again.", code)


def record(key):
    with _attempts_lock:
        _attempts.setdefault(key, []).append(time.time())


def clear(key):
    with _attempts_lock:
        _attempts.pop(key, None)


class ApiError(Exception):
    def __init__(self, status, message, code=None):
        super().__init__(message)
        self.status, self.message, self.code = status, message, code


# ---------------------------------------------------------------- database
SCHEMA = """
CREATE TABLE IF NOT EXISTS institutions(
  id INTEGER PRIMARY KEY, code TEXT UNIQUE NOT NULL, name TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS staff(
  id INTEGER PRIMARY KEY, institution_id INTEGER NOT NULL REFERENCES institutions(id),
  name TEXT NOT NULL, email TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN('admin','teacher','hod')),
  pw_hash TEXT NOT NULL, UNIQUE(institution_id, email));
CREATE TABLE IF NOT EXISTS students(
  id INTEGER PRIMARY KEY, institution_id INTEGER NOT NULL REFERENCES institutions(id),
  name TEXT NOT NULL, admission_no TEXT UNIQUE NOT NULL, handle TEXT UNIQUE NOT NULL,
  class_no INTEGER NOT NULL, section TEXT NOT NULL, roll_no INTEGER NOT NULL, stream TEXT,
  pw_hash TEXT NOT NULL, parent_key_hash TEXT NOT NULL,
  streak INTEGER NOT NULL DEFAULT 0, coins INTEGER NOT NULL DEFAULT 0, last_login TEXT);
CREATE TABLE IF NOT EXISTS guardians(
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, mobile TEXT UNIQUE NOT NULL);
CREATE TABLE IF NOT EXISTS guardian_students(
  guardian_id INTEGER NOT NULL REFERENCES guardians(id),
  student_id INTEGER NOT NULL REFERENCES students(id), PRIMARY KEY(guardian_id, student_id));
CREATE TABLE IF NOT EXISTS otps(
  mobile TEXT PRIMARY KEY, code_hash TEXT NOT NULL, expires REAL NOT NULL, attempts INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS attendance(
  student_id INTEGER NOT NULL REFERENCES students(id), day TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN('present','absent','late')), marked_by INTEGER,
  PRIMARY KEY(student_id, day));
CREATE TABLE IF NOT EXISTS homework(
  id INTEGER PRIMARY KEY, institution_id INTEGER NOT NULL, class_no INTEGER NOT NULL, section TEXT NOT NULL,
  subject TEXT NOT NULL, title TEXT NOT NULL, due_date TEXT NOT NULL, created_by INTEGER);
CREATE TABLE IF NOT EXISTS notifications(
  id INTEGER PRIMARY KEY, guardian_id INTEGER NOT NULL REFERENCES guardians(id),
  message TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS resets(
  key TEXT PRIMARY KEY, code_hash TEXT NOT NULL, expires REAL NOT NULL, attempts INTEGER NOT NULL DEFAULT 0);
"""

# Columns added after the first version. Added automatically to an existing database.
NEW_COLUMNS = [("staff", "mobile"), ("students", "email"), ("students", "mobile"),
               ("guardians", "email"), ("guardians", "pw_hash")]
NEW_INDEXES = [("staff", "mobile"), ("students", "email"), ("students", "mobile"), ("guardians", "email")]


def connect():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def migrate(conn):
    for table, col in NEW_COLUMNS:
        have = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        if col not in have:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} TEXT")
    for table, col in NEW_INDEXES:
        conn.execute(f"CREATE UNIQUE INDEX IF NOT EXISTS ux_{table}_{col} ON {table}({col})")


def backfill_demo(conn):
    """Gives the demo accounts an email / mobile so login-by-email-or-mobile and password reset can be tried.
    Only fills empty values, so it never overwrites real data. Remove before real use."""
    for adm, email, mobile in [("DPS-2024-884", "shivanand@example.com", "9000000011"),
                               ("DPS-2022-310", "ravi@example.com", "9000000012"),
                               ("DPS-2021-455", "rehan@example.com", "9000000013")]:
        conn.execute("UPDATE students SET email=?, mobile=? WHERE admission_no=? AND email IS NULL AND mobile IS NULL",
                     (email, mobile, adm))
    for em, mobile in [("firstyeardean@mrdu.edu.in", "9000000001"), ("teacher@dpsdelhi.edu.in", "9000000002"),
                       ("hod@dpsdelhi.edu.in", "9000000003")]:
        conn.execute("UPDATE staff SET mobile=? WHERE email=? AND mobile IS NULL", (mobile, em))
    conn.execute("UPDATE guardians SET email='rohit.parent@example.com' WHERE mobile='9876543210' AND email IS NULL")
    conn.execute("UPDATE guardians SET pw_hash=? WHERE mobile='9876543210' AND pw_hash IS NULL",
                 (hash_pw("Parent2026!"),))


def init_db():
    conn = connect()
    conn.executescript(SCHEMA)
    migrate(conn)
    if conn.execute("SELECT COUNT(*) FROM institutions").fetchone()[0] == 0:
        seed(conn)
    backfill_demo(conn)
    conn.commit()
    conn.close()


def seed(conn):
    """Demo data matching the defaults pre-filled in index.html. Change/remove before going live."""
    conn.execute("INSERT INTO institutions(code,name) VALUES('DPS-DEL-2026','DPS Public School, Delhi')")
    for name, email, role, pw in [
        ("Dean Sir Shiva Prasad", "firstyeardean@mrdu.edu.in", "admin", "AdminPass2026@"),
        ("Mrs. Gupta", "teacher@dpsdelhi.edu.in", "teacher", "Teacher2026@"),
        ("Dr. Rao", "hod@dpsdelhi.edu.in", "hod", "Hod2026@"),
    ]:
        conn.execute("INSERT INTO staff(institution_id,name,email,role,pw_hash) VALUES(1,?,?,?,?)",
                     (name, email, role, hash_pw(pw)))
    students = [
        ("N.Shivanand Reddy", "DPS-2024-884", "shivanand.reddy19", 10, "A", 24, None),
        ("T.Ravi Sai Varma", "DPS-2022-310", "ravi.sai", 12, "B", 7, "JEE"),
        ("Md.Rehan", "DPS-2021-455", "rehan.md", 5, "C", 12, None),
    ]
    for name, adm, handle, cls, sec, roll, stream in students:
        conn.execute(
            "INSERT INTO students(institution_id,name,admission_no,handle,class_no,section,roll_no,stream,"
            "pw_hash,parent_key_hash) VALUES(1,?,?,?,?,?,?,?,?,?)",
            (name, adm, handle, cls, sec, roll, stream, hash_pw("Student2026!"), hash_pw("Parent2026!")))
    conn.execute("INSERT INTO guardians(name,mobile) VALUES('Rohit Verma','9876543210')")
    conn.execute("INSERT INTO guardian_students VALUES(1,1)")
    today = date.today()
    for sid in (1, 2, 3):
        for d in range(1, 8):
            day = today - timedelta(days=d)
            if day.weekday() >= 5:
                continue
            status = "absent" if (sid + d) % 6 == 0 else ("late" if (sid + d) % 5 == 0 else "present")
            conn.execute("INSERT INTO attendance VALUES(?,?,?,1)", (sid, day.isoformat(), status))
    for cls, sec, subj, title, days in [
        (10, "A", "Maths", "Quadratic equations - Ex 4.3", 2),
        (10, "A", "Science", "Chemical reactions worksheet", 4),
        (12, "B", "Physics", "HC Verma Ch 5 - Newton's Laws DPP", 1),
        (5, "C", "English", "Write a paragraph on your best friend", 3),
    ]:
        conn.execute("INSERT INTO homework(institution_id,class_no,section,subject,title,due_date,created_by) "
                     "VALUES(1,?,?,?,?,?,1)", (cls, sec, subj, title, (today + timedelta(days=days)).isoformat()))


# ---------------------------------------------------------------- request context + validation
class Ctx:
    def __init__(self, conn, body, ip, user):
        self.conn, self.body, self.ip, self.user = conn, body, ip, user
        self.new_token = None
        self.clear_cookie = False


def field(body, key, maxlen=200):
    v = body.get(key)
    if not isinstance(v, str) or not v.strip():
        raise ApiError(400, f"Missing field: {key}")
    v = v.strip()
    if len(v) > maxlen:
        raise ApiError(400, f"Field too long: {key}")
    return v


def tier_of(class_no):
    return "1-8" if class_no <= 8 else ("9-10" if class_no <= 10 else "11-12")


def issue(ctx, portal, sub, **extra):
    ctx.new_token = make_token({"portal": portal, "sub": sub, **extra})


def deny():
    raise ApiError(401, "Invalid credentials")


MOBILE_RE = re.compile(r"[6-9]\d{9}")


def parse_ident(raw):
    """Works out whether someone typed a mobile number, an email, or something else (handle / admission no)."""
    v = raw.strip().lower()
    compact = re.sub(r"[\s\-]", "", v)
    if compact.startswith("+91"):
        compact = compact[3:]
    elif len(compact) == 12 and compact.startswith("91"):
        compact = compact[2:]
    if MOBILE_RE.fullmatch(compact):
        return "mobile", compact
    if "@" in v:
        return "email", v
    return "other", v


def ident_from(body):
    """Accepts the new 'identifier' key and the old keys, so older pages keep working."""
    for k in ("identifier", "email", "admission_no", "handle"):
        if isinstance(body.get(k), str) and body[k].strip():
            return field(body, k, 120)
    raise ApiError(400, "Missing field: identifier")


# ---------------------------------------------------------------- auth routes
def school_login(ctx):
    code = field(ctx.body, "institution_code", 40).upper()
    kind, ident = parse_ident(ident_from(ctx.body))
    password = field(ctx.body, "password", 200)
    role = field(ctx.body, "role", 20)
    key = f"school:{ctx.ip}:{ident}"
    check_limit(key)
    col = "mobile" if kind == "mobile" else "email"
    row = ctx.conn.execute(
        "SELECT s.*, i.name AS inst FROM staff s JOIN institutions i ON i.id=s.institution_id "
        f"WHERE i.code=? AND s.{col}=?", (code, ident)).fetchone()
    ok = verify_pw(password, row["pw_hash"] if row else DUMMY_HASH)
    if not (row and ok and row["role"] == role):
        record(key)
        deny()
    clear(key)
    issue(ctx, "school", row["id"], role=row["role"], inst=row["institution_id"])
    return {"ok": True, "redirect": "dashboard.html?portal=school",
            "user": {"name": row["name"], "role": row["role"], "institution": row["inst"]}}


def parent_otp_request(ctx):
    mobile = field(ctx.body, "mobile", 10)
    if not re.fullmatch(r"[6-9]\d{9}", mobile):
        raise ApiError(400, "Enter a valid 10-digit mobile number")
    key = f"otpreq:{mobile}"
    check_limit(key, limit=3, window=600)
    record(key)
    resp = {"ok": True, "message": "If this number is registered, an OTP has been sent."}
    g = ctx.conn.execute("SELECT id FROM guardians WHERE mobile=?", (mobile,)).fetchone()
    if g:
        code = f"{secrets.randbelow(10000):04d}"
        digest = hmac.new(SECRET, f"{mobile}:{code}".encode(), hashlib.sha256).hexdigest()
        ctx.conn.execute("INSERT OR REPLACE INTO otps VALUES(?,?,?,0)", (mobile, digest, time.time() + OTP_TTL))
        ctx.conn.commit()
        # TODO production: send via an SMS provider here. In dev we print it instead.
        print(f"[DEV OTP] {mobile} -> {code}")
        if DEV:
            resp["dev_otp"] = code
    return resp


def parent_otp_verify(ctx):
    mobile = field(ctx.body, "mobile", 10)
    code = field(ctx.body, "otp", 4)
    row = ctx.conn.execute("SELECT * FROM otps WHERE mobile=?", (mobile,)).fetchone()
    if not row or row["expires"] < time.time() or row["attempts"] >= 3:
        if row:
            ctx.conn.execute("DELETE FROM otps WHERE mobile=?", (mobile,))
        raise ApiError(401, "OTP expired or invalid. Request a new one.")
    digest = hmac.new(SECRET, f"{mobile}:{code}".encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(digest, row["code_hash"]):
        ctx.conn.execute("UPDATE otps SET attempts=attempts+1 WHERE mobile=?", (mobile,))
        ctx.conn.commit()
        raise ApiError(401, "Incorrect OTP")
    ctx.conn.execute("DELETE FROM otps WHERE mobile=?", (mobile,))
    g = ctx.conn.execute("SELECT * FROM guardians WHERE mobile=?", (mobile,)).fetchone()
    issue(ctx, "parent", g["id"])
    return {"ok": True, "redirect": "dashboard.html?portal=parent", "user": {"name": g["name"]}}


def parent_login(ctx):
    """Parent password login. The identifier can be the guardian's mobile or email (uses the guardian's own
    password), or the child's admission number (uses the admission key the school gave the family)."""
    kind, ident = parse_ident(ident_from(ctx.body))
    password = field(ctx.body, "password", 200)
    key = f"parent:{ctx.ip}:{ident}"
    check_limit(key)
    if kind == "other":
        st = ctx.conn.execute("SELECT * FROM students WHERE admission_no=? COLLATE NOCASE", (ident,)).fetchone()
        ok = verify_pw(password, st["parent_key_hash"] if st else DUMMY_HASH)
        g = st and ctx.conn.execute(
            "SELECT g.* FROM guardians g JOIN guardian_students gs ON gs.guardian_id=g.id "
            "WHERE gs.student_id=? LIMIT 1", (st["id"],)).fetchone()
        good = bool(st and ok and g)
    else:
        col = "mobile" if kind == "mobile" else "email"
        g = ctx.conn.execute(f"SELECT * FROM guardians WHERE {col}=?", (ident,)).fetchone()
        ok = verify_pw(password, g["pw_hash"] if g and g["pw_hash"] else DUMMY_HASH)
        good = bool(g and g["pw_hash"] and ok)
    if not good:
        record(key)
        deny()
    clear(key)
    issue(ctx, "parent", g["id"])
    return {"ok": True, "redirect": "dashboard.html?portal=parent", "user": {"name": g["name"]}}


def student_login(ctx):
    kind, ident = parse_ident(ident_from(ctx.body))
    password = field(ctx.body, "password", 200)
    key = f"student:{ctx.ip}:{ident}"
    check_limit(key)
    st = find_student(ctx.conn, kind, ident)
    ok = verify_pw(password, st["pw_hash"] if st else DUMMY_HASH)
    if not (st and ok):
        record(key)
        deny()
    tier = tier_of(st["class_no"])  # the real tier comes from the class on file, so a wrong tier button never blocks login
    clear(key)
    today = date.today()
    streak, coins, last = st["streak"], st["coins"], st["last_login"]
    if last != today.isoformat():  # once-a-day streak + 100 coin bonus
        streak = streak + 1 if last == (today - timedelta(days=1)).isoformat() else 1
        coins += 100
        ctx.conn.execute("UPDATE students SET streak=?, coins=?, last_login=? WHERE id=?",
                         (streak, coins, today.isoformat(), st["id"]))
    issue(ctx, "student", st["id"], tier=tier)
    return {"ok": True, "redirect": f"dashboard.html?portal=student&tier={tier}",
            "user": {"name": st["name"], "class": st["class_no"], "streak": streak, "coins": coins}}


def logout(ctx):
    ctx.clear_cookie = True
    return {"ok": True}


# ---------------------------------------------------------------- forgot / reset password
RESET_TTL = 600
RESET_TABLES = {"school": ("staff", "pw_hash"), "student": ("students", "pw_hash"), "parent": ("guardians", "pw_hash")}


def find_student(conn, kind, ident):
    if kind == "mobile":
        return conn.execute("SELECT * FROM students WHERE mobile=?", (ident,)).fetchone()
    if kind == "email":
        return conn.execute("SELECT * FROM students WHERE email=?", (ident,)).fetchone()
    return conn.execute("SELECT * FROM students WHERE handle=? COLLATE NOCASE OR admission_no=? COLLATE NOCASE",
                        (ident, ident)).fetchone()


def find_account(conn, portal, raw, inst_code=""):
    """Returns (table, id) for the account a reset applies to, or None."""
    kind, ident = parse_ident(raw)
    if portal == "school":
        if kind == "other":
            return None
        col = "mobile" if kind == "mobile" else "email"
        sql = f"SELECT s.id FROM staff s JOIN institutions i ON i.id=s.institution_id WHERE s.{col}=?"
        args = [ident]
        if inst_code:
            sql += " AND i.code=?"
            args.append(inst_code.upper())
        r = conn.execute(sql, args).fetchone()
        return ("staff", r["id"]) if r else None
    if portal == "student":
        r = find_student(conn, kind, ident)
        return ("students", r["id"]) if r else None
    if kind == "other":  # parents reset with their registered mobile or email only
        return None
    r = conn.execute(f"SELECT id FROM guardians WHERE {'mobile' if kind == 'mobile' else 'email'}=?", (ident,)).fetchone()
    return ("guardians", r["id"]) if r else None


def reset_digest(key, code):
    return hmac.new(SECRET, f"reset:{key}:{code}".encode(), hashlib.sha256).hexdigest()


def reset_inputs(body):
    portal = field(body, "portal", 10)
    if portal not in RESET_TABLES:
        raise ApiError(400, "Unknown portal")
    inst = body.get("institution_code")
    return portal, field(body, "identifier", 120), (inst.strip() if isinstance(inst, str) else "")


def reset_request(ctx):
    portal, ident, inst = reset_inputs(ctx.body)
    # 3 codes per account and 30 per network address per 10 minutes (schools share one Wi-Fi address)
    for limit_key, limit in ((f"resetreq:{portal}:{ident.lower()}", 3), (f"resetreq:{ctx.ip}", 30)):
        check_limit(limit_key, limit=limit, window=600, code="contact_admin")
        record(limit_key)
    # Same answer whether or not the account exists, so nobody can probe which numbers/emails are registered.
    resp = {"ok": True, "message": "If we find this account, a 6-digit code has been sent to its registered "
                                   "mobile number or email."}
    acc = find_account(ctx.conn, portal, ident, inst)
    if acc:
        code = f"{secrets.randbelow(1_000_000):06d}"
        key = f"{acc[0]}:{acc[1]}"
        ctx.conn.execute("INSERT OR REPLACE INTO resets VALUES(?,?,?,0)",
                         (key, reset_digest(key, code), time.time() + RESET_TTL))
        ctx.conn.commit()
        # TODO production: send `code` by SMS / email here. In dev it is printed (and returned) instead.
        print(f"[DEV RESET CODE] {portal} {ident} -> {code}")
        if DEV:
            resp["dev_otp"] = code
    return resp


def reset_confirm(ctx):
    portal, ident, inst = reset_inputs(ctx.body)
    code = field(ctx.body, "otp", 6)
    new_pw = field(ctx.body, "new_password", 128)
    if len(new_pw) < 8 or not re.search(r"[A-Za-z]", new_pw) or not re.search(r"\d", new_pw):
        raise ApiError(400, "New password must be at least 8 characters and include a letter and a number")
    limit_key = f"resetcfm:{ctx.ip}:{ident.lower()}"
    check_limit(limit_key, limit=8, window=600, code="contact_admin")
    record(limit_key)
    acc = find_account(ctx.conn, portal, ident, inst)
    key = acc and f"{acc[0]}:{acc[1]}"
    row = key and ctx.conn.execute("SELECT * FROM resets WHERE key=?", (key,)).fetchone()
    if not row or row["expires"] < time.time() or row["attempts"] >= 3:
        if row:
            ctx.conn.execute("DELETE FROM resets WHERE key=?", (key,))
        raise ApiError(401, "Code expired or invalid. Please request a new one.",
                       "contact_admin" if row and row["attempts"] >= 3 else None)
    if not hmac.compare_digest(reset_digest(key, code), row["code_hash"]):
        if row["attempts"] + 1 >= 3:
            ctx.conn.execute("DELETE FROM resets WHERE key=?", (key,))
            raise ApiError(401, "Too many wrong codes.", "contact_admin")
        ctx.conn.execute("UPDATE resets SET attempts=attempts+1 WHERE key=?", (key,))
        raise ApiError(401, "Incorrect code")
    table, col = RESET_TABLES[portal]
    ctx.conn.execute(f"UPDATE {table} SET {col}=? WHERE id=?", (hash_pw(new_pw), acc[1]))
    ctx.conn.execute("DELETE FROM resets WHERE key=?", (key,))
    clear(limit_key)
    return {"ok": True, "message": "Password updated. You can log in now."}


# ---------------------------------------------------------------- data helpers
def attendance_summary(conn, sid, days=30):
    rows = conn.execute("SELECT day,status FROM attendance WHERE student_id=? ORDER BY day DESC LIMIT ?",
                        (sid, days)).fetchall()
    total = len(rows)
    attended = sum(1 for r in rows if r["status"] in ("present", "late"))
    return {"percent": round(100 * attended / total, 1) if total else None,
            "recent": [{"date": r["day"], "status": r["status"]} for r in rows[:7]]}


def homework_for(conn, st):
    rows = conn.execute(
        "SELECT subject,title,due_date FROM homework WHERE institution_id=? AND class_no=? AND section=? "
        "AND due_date>=? ORDER BY due_date", (st["institution_id"], st["class_no"], st["section"],
                                              date.today().isoformat())).fetchall()
    return [dict(r) for r in rows]


def require(ctx, portal, roles=None):
    u = ctx.user
    if not u:
        raise ApiError(401, "Please log in")
    if u["portal"] != portal or (roles and u.get("role") not in roles):
        raise ApiError(403, "You don't have access to this")
    return u


# ---------------------------------------------------------------- authenticated routes
def me(ctx):
    u = ctx.user
    if not u:
        raise ApiError(401, "Please log in")
    c = ctx.conn
    if u["portal"] == "school":
        r = c.execute("SELECT s.name,s.role,i.name AS inst FROM staff s JOIN institutions i ON i.id=s.institution_id "
                      "WHERE s.id=?", (u["sub"],)).fetchone()
    elif u["portal"] == "parent":
        r = c.execute("SELECT name FROM guardians WHERE id=?", (u["sub"],)).fetchone()
    else:
        r = c.execute("SELECT name,class_no,section FROM students WHERE id=?", (u["sub"],)).fetchone()
    if not r:
        raise ApiError(401, "Account no longer exists")
    return {"portal": u["portal"], **dict(r)}


def dashboard(ctx):
    u, c = ctx.user, ctx.conn
    if not u:
        raise ApiError(401, "Please log in")
    today = date.today().isoformat()
    if u["portal"] == "school":
        inst = u["inst"]
        counts = {r["status"]: r["n"] for r in c.execute(
            "SELECT a.status, COUNT(*) n FROM attendance a JOIN students s ON s.id=a.student_id "
            "WHERE s.institution_id=? AND a.day=? GROUP BY a.status", (inst, today))}
        who = c.execute("SELECT name,role FROM staff WHERE id=?", (u["sub"],)).fetchone()
        return {"portal": "school", "name": who["name"] if who else "", "role": who["role"] if who else u.get("role"),
                "students": c.execute("SELECT COUNT(*) FROM students WHERE institution_id=?", (inst,)).fetchone()[0],
                "staff": c.execute("SELECT COUNT(*) FROM staff WHERE institution_id=?", (inst,)).fetchone()[0],
                "today_attendance": {"present": counts.get("present", 0), "late": counts.get("late", 0),
                                     "absent": counts.get("absent", 0)},
                "upcoming_homework": [dict(r) for r in c.execute(
                    "SELECT class_no,section,subject,title,due_date FROM homework WHERE institution_id=? AND due_date>=? "
                    "ORDER BY due_date LIMIT 10", (inst, today))]}
    if u["portal"] == "parent":
        kids = c.execute("SELECT s.* FROM students s JOIN guardian_students gs ON gs.student_id=s.id "
                         "WHERE gs.guardian_id=?", (u["sub"],)).fetchall()
        notes = c.execute("SELECT message,created_at FROM notifications WHERE guardian_id=? "
                          "ORDER BY id DESC LIMIT 10", (u["sub"],)).fetchall()
        gname = c.execute("SELECT name FROM guardians WHERE id=?", (u["sub"],)).fetchone()
        return {"portal": "parent", "name": gname["name"] if gname else "",
                "children": [{"name": k["name"], "class": f"{k['class_no']}-{k['section']}", "roll_no": k["roll_no"],
                              "attendance": attendance_summary(c, k["id"]), "homework": homework_for(c, k)}
                             for k in kids],
                "notifications": [dict(n) for n in notes]}
    st = c.execute("SELECT * FROM students WHERE id=?", (u["sub"],)).fetchone()
    return {"portal": "student", "name": st["name"], "class": st["class_no"], "tier": tier_of(st["class_no"]),
            "streak": st["streak"], "coins": st["coins"],
            "attendance": attendance_summary(c, st["id"]), "homework": homework_for(c, st)}


def list_students(ctx):
    u = require(ctx, "school", ("admin", "teacher", "hod"))
    rows = ctx.conn.execute(
        "SELECT s.id,s.name,s.admission_no,s.class_no,s.section,s.roll_no,"
        "(SELECT status FROM attendance a WHERE a.student_id=s.id AND a.day=?) AS today "
        "FROM students s WHERE s.institution_id=? ORDER BY s.class_no,s.section,s.roll_no",
        (date.today().isoformat(), u["inst"])).fetchall()
    return {"students": [dict(r) for r in rows]}


def mark_attendance(ctx):
    u = require(ctx, "school", ("admin", "teacher"))
    try:
        sid = int(ctx.body.get("student_id"))
    except (TypeError, ValueError):
        raise ApiError(400, "student_id must be a number")
    status = field(ctx.body, "status", 10)
    if status not in ("present", "absent", "late"):
        raise ApiError(400, "status must be present, absent or late")
    day = ctx.body.get("date") or date.today().isoformat()
    try:
        date.fromisoformat(day)
    except (TypeError, ValueError):
        raise ApiError(400, "date must be YYYY-MM-DD")
    st = ctx.conn.execute("SELECT * FROM students WHERE id=? AND institution_id=?", (sid, u["inst"])).fetchone()
    if not st:
        raise ApiError(404, "Student not found")
    ctx.conn.execute("INSERT OR REPLACE INTO attendance VALUES(?,?,?,?)", (sid, day, status, u["sub"]))
    verb = {"present": "arrived at school", "late": "arrived late", "absent": "was marked absent"}[status]
    for g in ctx.conn.execute("SELECT guardian_id FROM guardian_students WHERE student_id=?", (sid,)):
        ctx.conn.execute("INSERT INTO notifications(guardian_id,message) VALUES(?,?)",
                         (g["guardian_id"], f"{st['name']} {verb} on {day}."))
    return {"ok": True}


def add_homework(ctx):
    u = require(ctx, "school", ("admin", "teacher"))
    try:
        cls = int(ctx.body.get("class_no"))
    except (TypeError, ValueError):
        raise ApiError(400, "class_no must be a number")
    due = field(ctx.body, "due_date", 10)
    try:
        date.fromisoformat(due)
    except ValueError:
        raise ApiError(400, "due_date must be YYYY-MM-DD")
    ctx.conn.execute(
        "INSERT INTO homework(institution_id,class_no,section,subject,title,due_date,created_by) VALUES(?,?,?,?,?,?,?)",
        (u["inst"], cls, field(ctx.body, "section", 3).upper(), field(ctx.body, "subject", 60),
         field(ctx.body, "title", 200), due, u["sub"]))
    return {"ok": True}


ROUTES = {
    ("POST", "/api/auth/school/login"): school_login,
    ("POST", "/api/auth/parent/otp/request"): parent_otp_request,
    ("POST", "/api/auth/parent/otp/verify"): parent_otp_verify,
    ("POST", "/api/auth/parent/login"): parent_login,
    ("POST", "/api/auth/student/login"): student_login,
    ("POST", "/api/auth/reset/request"): reset_request,
    ("POST", "/api/auth/reset/confirm"): reset_confirm,
    ("POST", "/api/auth/logout"): logout,
    ("GET", "/api/me"): me,
    ("GET", "/api/dashboard"): dashboard,
    ("GET", "/api/students"): list_students,
    ("POST", "/api/attendance"): mark_attendance,
    ("POST", "/api/homework"): add_homework,
}


# ---------------------------------------------------------------- HTTP layer
class Handler(BaseHTTPRequestHandler):
    server_version = "VidyaSetu/1.0"

    def log_message(self, fmt, *args):
        print(f"{self.address_string()} {fmt % args}")

    def _headers(self, status, ctype, length):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(length))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "same-origin")

    def _json(self, status, data, ctx=None):
        raw = json.dumps(data).encode()
        self._headers(status, "application/json", len(raw))
        self.send_header("Cache-Control", "no-store")
        secure = "" if DEV else "; Secure"
        if ctx and ctx.new_token:
            self.send_header("Set-Cookie", f"vs_token={ctx.new_token}; HttpOnly; SameSite=Lax; Path=/; "
                                           f"Max-Age={TOKEN_TTL}{secure}")
        if ctx and ctx.clear_cookie:
            self.send_header("Set-Cookie", f"vs_token=; HttpOnly; SameSite=Lax; Path=/; Max-Age=0{secure}")
        self.end_headers()
        self.wfile.write(raw)

    def _user(self):
        for part in self.headers.get("Cookie", "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == "vs_token":
                return read_token(v)
        return None

    def _api(self, method, path):
        fn = ROUTES.get((method, path))
        if not fn:
            return self._json(404, {"ok": False, "error": "Not found"})
        body = {}
        if method == "POST":
            n = int(self.headers.get("Content-Length") or 0)
            if n > 10_000:
                return self._json(413, {"ok": False, "error": "Request too large"})
            try:
                body = json.loads(self.rfile.read(n) or b"{}")
                if not isinstance(body, dict):
                    raise ValueError
            except ValueError:
                return self._json(400, {"ok": False, "error": "Invalid JSON"})
        conn = connect()
        ctx = Ctx(conn, body, self.client_address[0], self._user())
        try:
            data = fn(ctx)
            conn.commit()
            self._json(200, data, ctx)
        except ApiError as e:
            conn.commit()
            self._json(e.status, {"ok": False, "error": e.message, **({"code": e.code} if e.code else {})})
        except Exception as e:  # never leak internals to the client
            print("ERROR", repr(e))
            self._json(500, {"ok": False, "error": "Server error"})
        finally:
            conn.close()

    def do_GET(self):
        path = urlparse(self.path).path
        if path.startswith("/api/"):
            return self._api("GET", path)
        entry = STATIC.get(path)
        if not entry:
            return self._json(404, {"ok": False, "error": "Not found"})
        raw = (BASE / entry[0]).read_bytes() if (BASE / entry[0]).exists() else b""
        if not raw:
            return self._json(404, {"ok": False, "error": "Not found"})
        self._headers(200, entry[1], len(raw))
        self.end_headers()
        self.wfile.write(raw)

    def do_POST(self):
        path = urlparse(self.path).path
        if not path.startswith("/api/"):
            return self._json(404, {"ok": False, "error": "Not found"})
        self._api("POST", path)


if __name__ == "__main__":
    init_db()
    print(f"VidyaSetu backend running on http://localhost:{PORT}  (DEV={DEV})")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
