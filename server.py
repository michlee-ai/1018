import ast
import hashlib
import json
import os
import secrets
import sqlite3
import subprocess
import sys
import threading
import time
import unicodedata
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
MAX_REQUEST_BYTES = 32_000
DB_PATH = ROOT / "students.sqlite3"


def load_project_env():
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.removeprefix("export ").strip()
        value = value.strip().strip('"').strip("'")
        if name and name not in os.environ:
            os.environ[name] = value


load_project_env()
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY", "")
TEACHER_EMAILS = {
    email.strip().casefold()
    for email in os.environ.get("TEACHER_EMAILS", "").split(",")
    if email.strip()
}
TEACHER_NAME = os.environ.get("TEACHER_NAME", "선생님").strip() or "선생님"
TEACHER_PIN = os.environ.get("TEACHER_PIN", "2468")
SAFE_CALLS = {
    "print",
    "input",
    "int",
    "float",
    "str",
    "bool",
    "len",
    "abs",
    "round",
    "min",
    "max",
    "sum",
    "sorted",
    "map",
    "list",
    "range",
}
COMMON_NODES = {
    "Module",
    "Assign",
    "Name",
    "Load",
    "Store",
    "Constant",
    "Expr",
    "Call",
    "BinOp",
    "UnaryOp",
    "Compare",
    "BoolOp",
    "If",
    "IfExp",
    "AugAssign",
    "Tuple",
    "List",
    "Subscript",
    "Slice",
    "Attribute",
    "keyword",
    "Pass",
    "Add",
    "Sub",
    "Mult",
    "Div",
    "FloorDiv",
    "Mod",
    "Pow",
    "UAdd",
    "USub",
    "Not",
    "Eq",
    "NotEq",
    "Lt",
    "LtE",
    "Gt",
    "GtE",
    "Is",
    "IsNot",
    "In",
    "NotIn",
    "And",
    "Or",
}
COURSE_NODES = {
    "basic": COMMON_NODES,
    "intermediate": COMMON_NODES | {"For", "Break", "Continue"},
}

# These cases remain on the server and are never included in the page source.
TESTS = {
    1: [("3 5", "8"), ("-14 6", "-8"), ("0 0", "0"), ("120 35", "155")],
    2: [("4 6", "24"), ("1 9", "9"), ("0 7", "0"), ("12 15", "180")],
    3: [("3 9 5", "9"), ("-8 -3 -12", "-3"), ("7 7 2", "7"), ("120 35 99", "120")],
    4: [
        ("5\n1 2 4 7 8", "3"),
        ("4\n1 3 5 7", "0"),
        ("1\n-2", "1"),
        ("6\n0 11 12 -4 9 20", "4"),
    ],
    5: [("5", "15"), ("1", "1"), ("10", "55"), ("100", "5050")],
    6: [
        ("3", "3\n6\n9\n12\n15\n18\n21\n24\n27"),
        ("2", "2\n4\n6\n8\n10\n12\n14\n16\n18"),
        ("9", "9\n18\n27\n36\n45\n54\n63\n72\n81"),
    ],
    7: [("5032", "10"), ("9", "9"), ("10000", "1"), ("123456", "21")],
    8: [("python", "6"), ("a", "1"), ("classroom", "9"), ("coding", "6")],
    9: [("120", "21"), ("7", "7"), ("9081", "1809"), ("1000", "1")],
    10: [
        ("4", "*\n**\n***\n****"),
        ("1", "*"),
        ("3", "*\n**\n***"),
        ("6", "*\n**\n***\n****\n*****\n******"),
    ],
}
SAMPLES = {
    1: ("3 5", "8"),
    2: ("4 6", "24"),
    3: ("3 9 5", "9"),
    4: ("5\n1 2 4 7 8", "3"),
    5: ("5", "15"),
    6: ("3", "3\n6\n9\n12\n15\n18\n21\n24\n27"),
    7: ("5032", "10"),
    8: ("python", "6"),
    9: ("120", "21"),
    10: ("4", "*\n**\n***\n****"),
}
SOLUTIONS = {
    1: {
        "code": "a, b = map(int, input().split())\nprint(a + b)",
        "explanation": "공백으로 나뉜 두 값을 정수로 바꾼 뒤, 더한 결과를 출력합니다.",
    },
    2: {
        "code": "width, height = map(int, input().split())\nprint(width * height)",
        "explanation": "가로와 세로를 정수로 입력받고 두 값을 곱해 넓이를 구합니다.",
    },
    3: {
        "code": "a, b, c = map(int, input().split())\nprint(max(a, b, c))",
        "explanation": "max 함수에 세 수를 넣으면 가장 큰 수를 찾을 수 있습니다.",
    },
    4: {
        "code": "n = int(input())\nnumbers = list(map(int, input().split()))\ncount = 0\nfor number in numbers:\n    if number % 2 == 0:\n        count += 1\nprint(count)",
        "explanation": "리스트의 수를 하나씩 확인하고, 2로 나누어떨어질 때마다 개수를 1 늘립니다.",
    },
    5: {
        "code": "n = int(input())\ntotal = 0\nfor number in range(1, n + 1):\n    total += number\nprint(total)",
        "explanation": "반복문으로 1부터 N까지의 수를 차례로 total에 더합니다.",
    },
    6: {
        "code": "n = int(input())\nfor i in range(1, 10):\n    print(n * i)",
        "explanation": "반복문이 1부터 9까지 바뀔 때마다 N과 곱한 값을 한 줄씩 출력합니다.",
    },
    7: {
        "code": "total = 0\nfor digit in input():\n    total += int(digit)\nprint(total)",
        "explanation": "입력된 숫자를 문자 하나씩 살펴보고, 각 문자를 정수로 바꾸어 더합니다.",
    },
    8: {
        "code": "word = input()\nprint(len(word))",
        "explanation": "len 함수는 문자열에 들어 있는 글자 수를 알려줍니다.",
    },
    9: {
        "code": "number = input()\nprint(int(number[::-1]))",
        "explanation": "문자열 슬라이싱 [::-1]로 자릿수 순서를 뒤집고, 정수로 바꿔 앞자리 0을 없앱니다.",
    },
    10: {
        "code": "n = int(input())\nfor i in range(1, n + 1):\n    print('*' * i)",
        "explanation": "반복 횟수 i만큼 별 문자열을 만든 뒤 한 줄씩 출력합니다.",
    },
}
SESSIONS = {}
SESSION_LOCK = threading.Lock()
AUTH_FAILURES = {}
AUTH_LOCK = threading.Lock()


class AuthRateLimitError(Exception):
    pass


def database():
    return sqlite3.connect(DB_PATH, timeout=10)


def initialize_database():
    with database() as connection:
        connection.execute(
            """CREATE TABLE IF NOT EXISTS students (
                id INTEGER PRIMARY KEY,
                stable_key TEXT UNIQUE,
                auth_uid TEXT UNIQUE,
                email TEXT UNIQUE,
                class_code TEXT NOT NULL,
                display_name TEXT NOT NULL,
                normalized_name TEXT NOT NULL,
                pin_salt BLOB NOT NULL,
                pin_hash BLOB NOT NULL,
                next_problem INTEGER NOT NULL DEFAULT 1,
                UNIQUE(class_code, normalized_name)
            )"""
        )
        columns = {row[1] for row in connection.execute("PRAGMA table_info(students)")}
        if "stable_key" not in columns:
            connection.execute("ALTER TABLE students ADD COLUMN stable_key TEXT")
        if "auth_uid" not in columns:
            connection.execute("ALTER TABLE students ADD COLUMN auth_uid TEXT")
        if "email" not in columns:
            connection.execute("ALTER TABLE students ADD COLUMN email TEXT")
        for (student_id,) in connection.execute(
            "SELECT id FROM students WHERE stable_key IS NULL"
        ).fetchall():
            connection.execute(
                "UPDATE students SET stable_key = ? WHERE id = ?",
                (secrets.token_urlsafe(18), student_id),
            )
        connection.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS students_stable_key ON students(stable_key)"
        )
        connection.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS students_auth_uid ON students(auth_uid) WHERE auth_uid IS NOT NULL"
        )
        connection.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS students_email ON students(email) WHERE email IS NOT NULL"
        )
        connection.execute(
            """CREATE TABLE IF NOT EXISTS teachers (
                id INTEGER PRIMARY KEY,
                display_name TEXT NOT NULL,
                normalized_name TEXT NOT NULL UNIQUE,
                pin_salt BLOB NOT NULL,
                pin_hash BLOB NOT NULL
            )"""
        )
        if (
            len(TEACHER_PIN) != 4
            or not TEACHER_PIN.isascii()
            or not TEACHER_PIN.isdigit()
        ):
            raise ValueError("TEACHER_PIN must be exactly four digits")
        salt = secrets.token_bytes(16)
        pin_hash = make_pin_hash(TEACHER_PIN, salt)
        connection.execute(
            """INSERT INTO teachers (id, display_name, normalized_name, pin_salt, pin_hash)
               VALUES (1, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                   display_name = excluded.display_name,
                   normalized_name = excluded.normalized_name,
                   pin_salt = excluded.pin_salt,
                   pin_hash = excluded.pin_hash""",
            (TEACHER_NAME, normalize_name(TEACHER_NAME), salt, pin_hash),
        )


def normalize_name(name):
    return unicodedata.normalize("NFKC", name.strip()).casefold()


def validate_auth_fields(payload):
    name = str(payload.get("name", "")).strip()
    normalized_name = normalize_name(name)
    pin = str(payload.get("pin", ""))
    if not name or len(name) > 32 or not normalized_name:
        raise ValueError("이름을 1~32자로 입력해 주세요.")
    if len(pin) != 4 or not pin.isascii() or not pin.isdigit():
        raise ValueError("PIN은 숫자 4자리로 입력해 주세요.")
    return name, normalized_name, pin


def make_pin_hash(pin, salt):
    return hashlib.scrypt(pin.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=32)


def create_student(payload):
    name, normalized_name, pin = validate_auth_fields(payload)
    stable_key = secrets.token_urlsafe(18)
    salt = secrets.token_bytes(16)
    pin_hash = make_pin_hash(pin, salt)
    try:
        with database() as connection:
            existing = connection.execute(
                "SELECT 1 FROM students WHERE normalized_name = ? LIMIT 1",
                (normalized_name,),
            ).fetchone()
            if existing:
                raise ValueError(
                    "이미 등록된 이름이에요. 로그인하거나 별명을 사용해 주세요."
                )
            cursor = connection.execute(
                "INSERT INTO students (stable_key, class_code, display_name, normalized_name, pin_salt, pin_hash) VALUES (?, ?, ?, ?, ?, ?)",
                (stable_key, "MAIN", name, normalized_name, salt, pin_hash),
            )
            student_id = cursor.lastrowid
    except sqlite3.IntegrityError as error:
        raise ValueError(
            "이미 등록된 이름이에요. 별명을 쓰거나 로그인해 주세요."
        ) from error
    return {"id": student_id, "key": stable_key, "name": name, "next_problem": 1}


def login_student(payload):
    _, normalized_name, pin = validate_auth_fields(payload)
    key = ("student", normalized_name)
    now = time.time()
    with AUTH_LOCK:
        failures = [stamp for stamp in AUTH_FAILURES.get(key, []) if now - stamp < 900]
        AUTH_FAILURES[key] = failures
        if len(failures) >= 5:
            raise AuthRateLimitError(
                "PIN을 여러 번 틀렸어요. 15분 뒤에 다시 시도해 주세요."
            )
    with database() as connection:
        rows = connection.execute(
            "SELECT id, stable_key, display_name, pin_salt, pin_hash, next_problem FROM students WHERE normalized_name = ?",
            (normalized_name,),
        ).fetchall()
    matches = []
    for row in rows:
        candidate = make_pin_hash(pin, row[3])
        if secrets.compare_digest(candidate, row[4]):
            matches.append(row)
    if not rows:
        make_pin_hash(pin, b"codeclass-dummy-salt")
    if len(matches) > 1:
        raise ValueError("같은 이름의 계정이 있어요. 별명으로 다시 등록해 주세요.")
    if not matches:
        with AUTH_LOCK:
            AUTH_FAILURES.setdefault(key, []).append(now)
        raise ValueError("이름 또는 PIN이 맞지 않아요.")
    with AUTH_LOCK:
        AUTH_FAILURES.pop(key, None)
    row = matches[0]
    return {
        "id": row[0],
        "key": row[1],
        "name": row[2],
        "next_problem": row[5],
    }


def login_teacher(payload):
    _, normalized_name, pin = validate_auth_fields(payload)
    key = ("teacher", normalized_name)
    now = time.time()
    with AUTH_LOCK:
        failures = [stamp for stamp in AUTH_FAILURES.get(key, []) if now - stamp < 900]
        AUTH_FAILURES[key] = failures
        if len(failures) >= 5:
            raise AuthRateLimitError(
                "PIN을 여러 번 틀렸어요. 15분 뒤에 다시 시도해 주세요."
            )
    with database() as connection:
        row = connection.execute(
            "SELECT id, display_name, pin_salt, pin_hash FROM teachers WHERE normalized_name = ?",
            (normalized_name,),
        ).fetchone()
    if row:
        candidate = make_pin_hash(pin, row[2])
        valid = secrets.compare_digest(candidate, row[3])
    else:
        make_pin_hash(pin, b"codeclass-dummy-salt")
        valid = False
    if not valid:
        with AUTH_LOCK:
            AUTH_FAILURES.setdefault(key, []).append(now)
        raise ValueError("교사 이름 또는 PIN이 맞지 않아요.")
    with AUTH_LOCK:
        AUTH_FAILURES.pop(key, None)
    return {"id": row[0], "name": row[1]}


def get_student(student_id):
    with database() as connection:
        row = connection.execute(
            "SELECT id, stable_key, display_name, next_problem FROM students WHERE id = ?",
            (student_id,),
        ).fetchone()
    if not row:
        return None
    return {"id": row[0], "key": row[1], "name": row[2], "next_problem": row[3]}


def verify_supabase_user(access_token):
    if not SUPABASE_URL or not SUPABASE_ANON_KEY:
        raise RuntimeError("Supabase 설정이 아직 완료되지 않았어요.")
    if not isinstance(access_token, str) or len(access_token) > 12_000:
        raise ValueError("로그인 세션을 확인할 수 없어요.")
    request = Request(
        f"{SUPABASE_URL}/auth/v1/user",
        headers={
            "apikey": SUPABASE_ANON_KEY,
            "Authorization": f"Bearer {access_token}",
        },
    )
    try:
        with urlopen(request, timeout=8) as response:
            user = json.loads(response.read())
    except HTTPError as error:
        if error.code in {401, 403}:
            raise ValueError(
                "Supabase 로그인 세션이 만료됐어요. 다시 로그인해 주세요."
            ) from error
        raise RuntimeError("Supabase 계정을 확인하지 못했어요.") from error
    except (URLError, TimeoutError, json.JSONDecodeError) as error:
        raise RuntimeError(
            "Supabase에 연결하지 못했어요. 잠시 후 다시 시도해 주세요."
        ) from error
    if not user.get("id") or not user.get("email"):
        raise ValueError("인증된 이메일 계정을 확인할 수 없어요.")
    return user


def supabase_student(user):
    auth_uid = str(user["id"])
    email = str(user["email"]).strip().casefold()
    metadata = user.get("user_metadata") or {}
    name = str(
        metadata.get("display_name")
        or metadata.get("full_name")
        or metadata.get("name")
        or email.split("@", 1)[0]
    ).strip()[:32]
    if not name:
        name = "학생"
    with database() as connection:
        row = connection.execute(
            "SELECT id FROM students WHERE auth_uid = ? OR email = ? LIMIT 1",
            (auth_uid, email),
        ).fetchone()
        if row:
            connection.execute(
                "UPDATE students SET auth_uid = ?, email = ?, display_name = ? WHERE id = ?",
                (auth_uid, email, name, row[0]),
            )
            student_id = row[0]
        else:
            stable_key = secrets.token_urlsafe(18)
            salt = secrets.token_bytes(16)
            unused_pin_hash = make_pin_hash(secrets.token_urlsafe(32), salt)
            cursor = connection.execute(
                """INSERT INTO students
                   (stable_key, auth_uid, email, class_code, display_name, normalized_name, pin_salt, pin_hash)
                   VALUES (?, ?, ?, 'MAIN', ?, ?, ?, ?)""",
                (
                    stable_key,
                    auth_uid,
                    email,
                    name,
                    f"supabase:{auth_uid}",
                    salt,
                    unused_pin_hash,
                ),
            )
            student_id = cursor.lastrowid
    return get_student(student_id)


def get_teacher(teacher_id):
    with database() as connection:
        row = connection.execute(
            "SELECT id, display_name FROM teachers WHERE id = ?", (teacher_id,)
        ).fetchone()
    if not row:
        return None
    return {"id": row[0], "name": row[1]}


def list_student_progress():
    with database() as connection:
        rows = connection.execute(
            "SELECT display_name, next_problem FROM students ORDER BY normalized_name"
        ).fetchall()
    return [
        {"name": name, "completed": min(next_problem - 1, len(TESTS))}
        for name, next_problem in rows
    ]


def save_student_progress(student_id, next_problem):
    with database() as connection:
        connection.execute(
            "UPDATE students SET next_problem = MAX(next_problem, ?) WHERE id = ?",
            (next_problem, student_id),
        )


RUNNER = r"""
import contextlib
import io
import json
import resource
import sys

payload = json.loads(sys.argv[1])
resource.setrlimit(resource.RLIMIT_CPU, (2, 2))
resource.setrlimit(resource.RLIMIT_AS, (256 * 1024 * 1024, 256 * 1024 * 1024))

class LimitedOutput(io.StringIO):
    def write(self, text):
        if self.tell() + len(text) > 10000:
            raise ValueError("출력이 너무 깁니다.")
        return super().write(text)

safe_names = "print input int float str bool len abs round min max sum sorted map list range".split()
safe_builtins = {name: getattr(__builtins__, name) for name in safe_names if hasattr(__builtins__, name)} if not isinstance(__builtins__, dict) else {name: __builtins__[name] for name in safe_names if name in __builtins__}
compiled = compile(payload["code"], "<student-code>", "exec")
def run_case(case):
    old_stdin = sys.stdin
    output = LimitedOutput()
    try:
        sys.stdin = io.StringIO(case["input"])
        scope = {"__builtins__": safe_builtins}
        with contextlib.redirect_stdout(output):
            exec(compiled, scope, scope)
        passed = output.getvalue().strip() == case["output"].strip()
        return passed, None
    except Exception as error:
        return False, type(error).__name__
    finally:
        sys.stdin = old_stdin

results = []
for index, case in enumerate(payload["tests"]):
    passed, error = run_case(case)
    result = {"index": index, "passed": passed}
    if error:
        result["error"] = error
    results.append(result)
sample_passed, sample_error = run_case(payload["sample"])
print(json.dumps({"results": results, "sample_passed": sample_passed, "sample_error": sample_error}))
"""


def validate_code(code, level):
    if not isinstance(code, str) or len(code) > 12_000:
        raise ValueError("코드가 너무 길어요. 12,000자 이내로 작성해 주세요.")
    if level not in COURSE_NODES:
        raise ValueError("문제의 교육 단계가 올바르지 않아요.")
    try:
        tree = ast.parse(code)
    except SyntaxError as error:
        raise ValueError(
            f"파이썬 문법을 확인해 주세요. {error.msg} (줄 {error.lineno})"
        ) from error

    for node in ast.walk(tree):
        kind = type(node).__name__
        if kind not in COURSE_NODES[level]:
            raise ValueError(f"교육 범위 밖 문법: {kind}")
        if isinstance(node, ast.Name) and node.id.startswith("__"):
            raise ValueError("특수 이름은 사용할 수 없어요.")
        if isinstance(node, ast.Attribute) and node.attr != "split":
            raise ValueError("교육 범위 밖 속성 접근입니다.")
        if isinstance(node, ast.Call):
            safe_call = isinstance(node.func, ast.Name) and node.func.id in SAFE_CALLS
            safe_method = (
                isinstance(node.func, ast.Attribute) and node.func.attr == "split"
            )
            if not (safe_call or safe_method):
                raise ValueError("허용된 기본 함수만 사용할 수 있어요.")


def grade(problem_id, code):
    level = "intermediate" if problem_id in {4, 5, 6, 7, 9, 10} else "basic"
    validate_code(code, level)
    payload = {
        "code": code,
        "tests": [
            {"input": data, "output": expected} for data, expected in TESTS[problem_id]
        ],
        "sample": {"input": SAMPLES[problem_id][0], "output": SAMPLES[problem_id][1]},
    }
    try:
        completed = subprocess.run(
            [
                sys.executable,
                "-I",
                "-c",
                RUNNER,
                json.dumps(payload, ensure_ascii=False),
            ],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise TimeoutError(
            "실행 시간이 너무 길어요. 반복문이 끝나는지 확인해 주세요."
        ) from error
    if completed.returncode != 0:
        raise RuntimeError(
            "코드 실행이 중단됐어요. 반복 횟수와 계산량을 확인해 주세요."
        )
    try:
        return json.loads(completed.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError) as error:
        raise RuntimeError(
            "채점 결과를 만들지 못했어요. 코드를 다시 확인해 주세요."
        ) from error


class Handler(BaseHTTPRequestHandler):
    def get_session_token(self):
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie", ""))
        except (CookieError, TypeError, ValueError):
            return None
        morsel = cookie.get("course_session")
        token = morsel.value if morsel else None
        with SESSION_LOCK:
            return token if token in SESSIONS else None

    def create_session(self):
        token = self.get_session_token()
        if token:
            return token
        token = secrets.token_urlsafe(24)
        with SESSION_LOCK:
            SESSIONS[token] = {
                "next_problem": 1,
                "grading": False,
                "user_id": None,
                "teacher_id": None,
                "teacher": None,
                "role": None,
            }
        return token

    def bind_student_session(self, student):
        old_token = self.get_session_token()
        token = secrets.token_urlsafe(24)
        with SESSION_LOCK:
            if old_token:
                SESSIONS.pop(old_token, None)
            SESSIONS[token] = {
                "next_problem": student["next_problem"],
                "grading": False,
                "user_id": student["id"],
                "teacher_id": None,
                "teacher": None,
                "role": "student",
            }
        return token

    def bind_teacher_session(self, teacher):
        old_token = self.get_session_token()
        token = secrets.token_urlsafe(24)
        with SESSION_LOCK:
            if old_token:
                SESSIONS.pop(old_token, None)
            SESSIONS[token] = {
                "next_problem": 1,
                "grading": False,
                "user_id": None,
                "teacher_id": teacher["id"],
                "teacher": teacher,
                "role": "teacher",
            }
        return token

    def set_session_cookie(self, token):
        secure = "; Secure" if self.headers.get("X-Forwarded-Proto") == "https" else ""
        self.send_header(
            "Set-Cookie",
            f"course_session={token}; HttpOnly; SameSite=Lax; Path=/; Max-Age=86400{secure}",
        )

    def clear_grading(self, token):
        if token:
            with SESSION_LOCK:
                if token in SESSIONS:
                    SESSIONS[token]["grading"] = False

    def send_json(self, status, data, token=None, clear_cookie=False):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if token:
            self.set_session_cookie(token)
        elif clear_cookie:
            self.send_header(
                "Set-Cookie",
                "course_session=; HttpOnly; SameSite=Lax; Path=/; Max-Age=0",
            )
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/__preview-bridge.js":
            bridge = (ROOT / "__preview-bridge.js").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "application/javascript; charset=utf-8")
            self.send_header("Content-Length", str(len(bridge)))
            self.end_headers()
            self.wfile.write(bridge)
            return
        if self.path == "/api/config":
            configured = bool(SUPABASE_URL and SUPABASE_ANON_KEY)
            self.send_json(
                200,
                {
                    "supabase_ready": configured,
                    "supabase_url": SUPABASE_URL if configured else "",
                    "supabase_anon_key": SUPABASE_ANON_KEY if configured else "",
                    "teacher_configured": bool(TEACHER_EMAILS),
                },
            )
            return
        if self.path == "/api/health":
            token = self.create_session()
            with SESSION_LOCK:
                session = SESSIONS[token]
                role = session["role"]
                student_id = session["user_id"]
                teacher_id = session["teacher_id"]
                session_teacher = session.get("teacher")
            student = (
                get_student(student_id) if role == "student" and student_id else None
            )
            if student:
                with SESSION_LOCK:
                    SESSIONS[token]["next_problem"] = student["next_problem"]
                self.send_json(
                    200,
                    {
                        "ready": True,
                        "authenticated": True,
                        "student": student,
                        "next_problem": student["next_problem"],
                    },
                    token,
                )
            elif role == "teacher" and teacher_id:
                teacher = session_teacher or get_teacher(teacher_id)
                self.send_json(
                    200,
                    {
                        "ready": True,
                        "authenticated": True,
                        "role": "teacher",
                        "teacher": teacher,
                    },
                    token,
                )
            else:
                data = {
                    "ready": True,
                    "authenticated": False,
                    "teacher_configured": bool(TEACHER_EMAILS),
                }
                self.send_json(200, data, token)
            return
        if self.path == "/api/teacher/overview":
            token = self.get_session_token()
            if not token:
                self.send_json(401, {"error": "교사 계정으로 로그인해 주세요."})
                return
            with SESSION_LOCK:
                is_teacher = SESSIONS[token]["role"] == "teacher"
            if not is_teacher:
                self.send_json(403, {"error": "교사 계정만 볼 수 있는 화면이에요."})
                return
            students = list_student_progress()
            self.send_json(
                200,
                {
                    "students": students,
                    "student_count": len(students),
                    "completed_count": sum(
                        s["completed"] == len(TESTS) for s in students
                    ),
                },
            )
            return
        if self.path.startswith("/api/solution/"):
            try:
                problem_id = int(self.path.rsplit("/", 1)[1])
            except ValueError:
                self.send_error(404)
                return
            token = self.get_session_token()
            if not token:
                self.send_json(401, {"error": "먼저 로그인해 주세요."})
                return
            with SESSION_LOCK:
                session = SESSIONS[token]
                student_id = session["user_id"]
                is_student = session["role"] == "student"
                next_problem = session["next_problem"]
            if not student_id or not is_student:
                self.send_json(401, {"error": "먼저 로그인해 주세요."})
                return
            if problem_id not in SOLUTIONS:
                self.send_error(404)
                return
            if problem_id > next_problem:
                self.send_json(403, {"error": "먼저 현재 문제를 풀어 주세요."})
                return
            self.send_json(200, SOLUTIONS[problem_id])
            return
        if self.path not in {"/", "/index.html"}:
            self.send_error(404)
            return
        page = (ROOT / "index.html").read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(page)))
        self.set_session_cookie(self.create_session())
        self.end_headers()
        self.wfile.write(page)

    def read_json_body(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length < 1 or length > MAX_REQUEST_BYTES:
            raise ValueError("요청 크기가 올바르지 않아요.")
        payload = json.loads(self.rfile.read(length))
        if not isinstance(payload, dict):
            raise TypeError("요청 형식을 확인해 주세요.")
        return payload

    def handle_supabase_auth(self):
        try:
            payload = self.read_json_body()
            requested_role = payload.get("role", "student")
            if requested_role not in {"student", "teacher"}:
                raise ValueError("계정 종류를 확인해 주세요.")
            authorization = self.headers.get("Authorization", "")
            access_token = (
                authorization[7:] if authorization.startswith("Bearer ") else ""
            )
            user = verify_supabase_user(access_token)
            email = user["email"].strip().casefold()
            is_teacher = email in TEACHER_EMAILS
            if requested_role == "teacher" and not is_teacher:
                if not TEACHER_EMAILS:
                    raise ValueError(
                        "교사 이메일 허용 목록이 아직 설정되지 않았어요. 운영자에게 문의해 주세요."
                    )
                raise ValueError("이 이메일은 교사 계정으로 등록되어 있지 않아요.")
            if is_teacher:
                metadata = user.get("user_metadata") or {}
                teacher_name = str(
                    metadata.get("display_name")
                    or metadata.get("full_name")
                    or metadata.get("name")
                    or email.split("@", 1)[0]
                ).strip()[:32]
                account = {
                    "id": user["id"],
                    "name": teacher_name or "교사",
                    "email": email,
                }
                token = self.bind_teacher_session(account)
                self.send_json(
                    200,
                    {"role": "teacher", "teacher": account},
                    token,
                )
                return
            account = supabase_student(user)
            if not account:
                raise RuntimeError("학생 계정을 불러오지 못했어요.")
            token = self.bind_student_session(account)
            self.send_json(
                200,
                {
                    "role": "student",
                    "student": account,
                    "next_problem": account["next_problem"],
                },
                token,
            )
        except ValueError as error:
            self.send_json(400, {"error": str(error)})
        except RuntimeError as error:
            self.send_json(503, {"error": str(error)})
        except (json.JSONDecodeError, AttributeError, TypeError):
            self.send_json(400, {"error": "로그인 정보를 확인해 주세요."})

    def handle_auth(self, action):
        try:
            payload = self.read_json_body()
            if action == "register":
                account = create_student(payload)
                token = self.bind_student_session(account)
            elif action == "teacher":
                account = login_teacher(payload)
                token = self.bind_teacher_session(account)
            else:
                account = login_student(payload)
                token = self.bind_student_session(account)
            self.send_json(
                201 if action == "register" else 200,
                {
                    "role": "teacher" if action == "teacher" else "student",
                    "student" if action != "teacher" else "teacher": account,
                    "next_problem": account.get("next_problem", 1),
                },
                token,
            )
        except AuthRateLimitError as error:
            self.send_json(429, {"error": str(error)})
        except ValueError as error:
            self.send_json(400, {"error": str(error)})
        except (json.JSONDecodeError, AttributeError, TypeError):
            self.send_json(400, {"error": "입력한 정보를 확인해 주세요."})

    def do_POST(self):
        if self.path == "/api/auth/supabase":
            self.handle_supabase_auth()
            return
        if self.path == "/api/auth/register":
            self.send_json(410, {"error": "이메일 가입을 사용해 주세요."})
            return
        if self.path == "/api/auth/login":
            self.send_json(410, {"error": "이메일 로그인을 사용해 주세요."})
            return
        if self.path == "/api/auth/teacher":
            self.send_json(410, {"error": "교사 이메일 로그인을 사용해 주세요."})
            return
        if self.path == "/api/auth/logout":
            token = self.get_session_token()
            with SESSION_LOCK:
                if token:
                    SESSIONS.pop(token, None)
            self.send_json(200, {"ok": True}, clear_cookie=True)
            return
        if self.path != "/api/grade":
            self.send_error(404)
            return
        token = self.get_session_token()
        if not token:
            self.send_json(
                403, {"error": "학습 세션을 찾지 못했어요. 페이지를 새로고침해 주세요."}
            )
            return
        with SESSION_LOCK:
            session = SESSIONS[token]
            student_id = session["user_id"]
            is_student = session["role"] == "student"
        if not student_id or not is_student:
            self.send_json(401, {"error": "학생 계정으로 로그인해 주세요."})
            return
        grading_started = False
        try:
            payload = self.read_json_body()
            problem_id = payload.get("problem_id")
            if not isinstance(problem_id, int) or problem_id not in TESTS:
                self.send_json(400, {"error": "문제를 찾을 수 없어요."})
                return
            with SESSION_LOCK:
                session = SESSIONS[token]
                if problem_id > session["next_problem"]:
                    self.send_json(
                        409,
                        {
                            "error": f"먼저 {session['next_problem']}번 문제를 풀어 주세요."
                        },
                    )
                    return
                if session["grading"]:
                    self.send_json(
                        409, {"error": "채점이 진행 중이에요. 잠시 기다려 주세요."}
                    )
                    return
                session["grading"] = True
                grading_started = True
            grade_result = grade(problem_id, payload.get("code"))
            results = grade_result["results"]
            with SESSION_LOCK:
                session = SESSIONS[token]
                session["grading"] = False
                grading_started = False
                if results and all(result["passed"] for result in results):
                    save_student_progress(student_id, problem_id + 1)
                    student = get_student(student_id)
                    if student:
                        session["next_problem"] = student["next_problem"]
                next_problem = session["next_problem"]
            self.send_json(200, {**grade_result, "next_problem": next_problem})
        except ValueError as error:
            if grading_started:
                self.clear_grading(token)
            message = str(error)
            if message.startswith("파이썬 문법을 확인"):
                error_kind = "syntax"
            elif "교육 범위 밖" in message or "허용된 기본 함수" in message:
                error_kind = "curriculum"
            else:
                error_kind = "validation"
            self.send_json(400, {"error": message, "error_kind": error_kind})
        except TimeoutError as error:
            if grading_started:
                self.clear_grading(token)
            self.send_json(200, {"error": str(error), "results": []})
        except (json.JSONDecodeError, AttributeError, TypeError):
            if grading_started:
                self.clear_grading(token)
            self.send_json(400, {"error": "요청 형식을 확인해 주세요."})
        except (BrokenPipeError, ConnectionResetError):
            if grading_started:
                self.clear_grading(token)
            return
        except Exception:  # noqa: BLE001 - keep grader failures from leaking details
            if grading_started:
                self.clear_grading(token)
            self.send_json(
                500, {"error": "채점 중 문제가 생겼어요. 다시 시도해 주세요."}
            )

    def log_message(self, format, *_args):
        pass


if __name__ == "__main__":
    initialize_database()
    port = int(os.environ.get("PORT", "3000"))
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"Serving on 0.0.0.0:{port}", flush=True)
    server.serve_forever()
