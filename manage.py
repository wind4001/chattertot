"""本项目启动/只读自检入口；启动器自身只依赖 Python 标准库。"""
import argparse
from contextlib import contextmanager
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time
from urllib.parse import urlsplit, urlunsplit
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, build_opener
import webbrowser

ROOT = Path(__file__).resolve().parent
BACKEND = ROOT / "cascade/backend"
ENV_FILE = BACKEND / ".env"
VENV = BACKEND / ".venv"
PYTHON = VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
COMPOSE = ["docker", "compose", "--project-name", "cascade", "--file", str(ROOT / "cascade/docker-compose.yml")]


class StartupError(Exception):
    pass


def project_id():
    return hashlib.sha256(os.path.normcase(str(ROOT)).encode()).hexdigest()[:16]


@contextmanager
def startup_lock(port):
    folder = ROOT / ".runtime"
    folder.mkdir(exist_ok=True)
    with (folder / f"start-{port}.lock").open("a+b") as handle:
        if os.fstat(handle.fileno()).st_size == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise StartupError("已有启动流程正在运行，请等待完成后再试") from error
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def child_env(test=False):
    env = os.environ.copy()
    env.update(PYTHONUTF8="1", CHATTERTOT_RUN_MODE="test" if test else "production")
    if test:
        configured = env.get("DB_URL")
        if configured is None and ENV_FILE.is_file():
            for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
                if line.strip().startswith("DB_URL="):
                    configured = line.split("=", 1)[1].strip().strip("\"'")
        parsed = urlsplit(configured or "postgresql://postgres:chattertot_dev_pw@localhost:5432/chattertot")
        database = parsed.path.lstrip("/") + "_test"
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", database):
            raise StartupError("测试数据库名无效，请检查 DB_URL")
        env["DB_URL"] = urlunsplit(parsed._replace(path="/" + database))
    return env


def run(args, *, timeout=30, input_text=None, check=True, live=False, env=None):
    try:
        completed = subprocess.run(
            [str(arg) for arg in args], cwd=ROOT, env=env, input=input_text,
            text=True, encoding="utf-8", errors="replace", timeout=timeout,
            capture_output=not live,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise StartupError(f"{Path(str(args[0])).name} 无法运行或等待超时；请检查安装和服务状态") from error
    if check and completed.returncode:
        raise StartupError(f"{Path(str(args[0])).name} 执行失败；请查看当前步骤输出或运行自检")
    return completed


def require_configuration_file():
    if not ENV_FILE.is_file():
        raise StartupError("缺少 cascade/backend/.env；从 .env.example 复制并填写 LLM_API_KEY 和 TTS_API_KEY")


def read_json(url, timeout=4):
    opener = build_opener(ProxyHandler({}))
    try:
        with opener.open(url, timeout=timeout) as response:
            return json.loads(response.read())
    except HTTPError as response:
        try:
            return json.loads(response.read())
        except (ValueError, OSError):
            return None
    except (OSError, URLError, ValueError):
        return None


def port_open(port):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return True
    except OSError:
        return False


def existing_backend(port, test=False):
    if not port_open(port):
        return False
    identity = read_json(f"http://127.0.0.1:{port}/health/live")
    if not isinstance(identity, dict) or any((
        identity.get("service") != "chattertot",
        identity.get("project_id") != project_id(),
        identity.get("mode") != ("test" if test else "production"),
    )):
        raise StartupError(f"端口 {port} 已被其他程序、其他项目副本或旧版后端占用；请先关闭对应服务，不会自动终止它")
    return True


def dependencies_ready():
    if not PYTHON.is_file():
        return False
    probe = run([PYTHON, "-c", "import fastapi,uvicorn,websockets,httpx,multipart,dotenv,asyncpg"], check=False)
    return probe.returncode == 0


def ensure_environment():
    if sys.version_info < (3, 11):
        raise StartupError("需要 Python 3.11 或更高版本")
    if not PYTHON.is_file():
        print("[准备] 创建项目独立 Python 环境", flush=True)
        run([sys.executable, "-m", "venv", VENV], timeout=120, live=True)
    digest = hashlib.sha256((BACKEND / "requirements.txt").read_bytes()).hexdigest()
    stamp = VENV / ".chattertot-requirements.sha256"
    if not dependencies_ready() or not stamp.exists() or stamp.read_text().strip() != digest:
        print("[准备] 安装/补齐后端依赖（首次需要联网）", flush=True)
        run([PYTHON, "-m", "pip", "install", "-r", BACKEND / "requirements.txt"], timeout=600, live=True)
        stamp.write_text(digest, encoding="ascii")


def health_report(test=False, config_only=False):
    args = [PYTHON, BACKEND / "health.py", "--json"]
    if config_only:
        args.append("--config-only")
    completed = run(args, timeout=15, check=False, env=child_env(test))
    try:
        report = json.loads(completed.stdout)
        if not isinstance(report.get("checks"), list):
            raise ValueError
        return report
    except (ValueError, AttributeError) as error:
        raise StartupError("自检模块无法运行；请检查虚拟环境依赖，运行启动入口补齐") from error


def show_checks(report):
    for item in report["checks"]:
        print(f"[{'OK' if item['ok'] else 'FAIL'}] {item['name']}: {item['message']}", flush=True)
        if item.get("action"):
            print("  建议：" + item["action"], flush=True)


def check_docker():
    if not shutil.which("docker"):
        raise StartupError("找不到 Docker；请安装并启动 Docker Desktop")
    probe = run(["docker", "info", "--format", "{{.ServerVersion}}"], timeout=12, check=False)
    if probe.returncode:
        raise StartupError("无法连接 Docker 引擎；请打开 Docker Desktop 并等待引擎就绪，或检查访问权限")
    if run(["docker", "compose", "version"], check=False).returncode:
        raise StartupError("Docker Compose 不可用；请检查 Docker Desktop 安装")


def prepare_services(test=False):
    print("[准备] 启动数据库", flush=True)
    run(COMPOSE + ["up", "-d", "db"], timeout=1800, live=True)
    deadline = time.monotonic() + 30
    while run(COMPOSE + ["exec", "-T", "db", "pg_isready", "-U", "postgres"], check=False).returncode:
        if time.monotonic() >= deadline:
            raise StartupError("数据库未就绪；运行 docker compose -p cascade -f cascade/docker-compose.yml logs --tail 80 db 检查")
        time.sleep(1)
    if test:
        database = urlsplit(child_env(True)["DB_URL"]).path.lstrip("/")
        exists = run(COMPOSE + ["exec", "-T", "db", "psql", "-U", "postgres", "-d", "postgres", "-tAc",
                                f"SELECT 1 FROM pg_database WHERE datname='{database}'"])
        if exists.stdout.strip() != "1":
            run(COMPOSE + ["exec", "-T", "db", "createdb", "-U", "postgres", database])
    run([str(PYTHON), str(BACKEND / "setup_database.py")], env=child_env(test), live=True, timeout=45)
    if run(["docker", "image", "inspect", "cascade-asr:latest"], check=False).returncode:
        print("[准备] 首次构建语音镜像，下载较大，请等待", flush=True)
        run(COMPOSE + ["build", "asr"], timeout=1800, live=True)
    prepare = ROOT / "cascade/asr/prepare_models.py"
    command = COMPOSE + ["run", "--rm", "--no-deps", "--entrypoint", "python",
                         "-v", f"{prepare}:/setup/prepare_models.py:ro", "asr", "/setup/prepare_models.py"]
    if run(command + ["--check-only"], timeout=30, check=False).returncode:
        print("[准备] 补齐正式模型（首次需要下载约 1GB）", flush=True)
        run(command, timeout=1800, live=True)
    print("[准备] 启动 ASR、声纹和唤醒词服务", flush=True)
    run(COMPOSE + ["up", "-d", "--no-build", "asr"], live=True)


def wait_dependencies(test, timeout):
    deadline = time.monotonic() + timeout
    previous = None
    while True:
        report = health_report(test)
        if report["status"] == "ready":
            show_checks(report)
            return
        failed = ", ".join(item["name"] for item in report["checks"] if not item["ok"])
        if failed != previous:
            print("[等待] 尚未就绪：" + failed, flush=True)
            previous = failed
        if time.monotonic() >= deadline:
            show_checks(report)
            raise StartupError("依赖服务等待超时；请按上方建议处理后重新启动")
        time.sleep(1)


def start_backend(port, test=False):
    logs = BACKEND / "logs"
    logs.mkdir(exist_ok=True)
    flags = (subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP) if os.name == "nt" else 0
    with (logs / "stdout.log").open("ab") as stdout, (logs / "stderr.log").open("ab") as stderr:
        subprocess.Popen([str(PYTHON), "-u", "-m", "uvicorn", "app:app", "--host", "127.0.0.1", "--port", str(port)],
                         cwd=BACKEND, env=child_env(test), stdin=subprocess.DEVNULL, stdout=stdout,
                         stderr=stderr, creationflags=flags, start_new_session=os.name != "nt")


def wait_backend(port, test, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if existing_backend(port, test):
            report = read_json(f"http://127.0.0.1:{port}/health/ready", timeout=8)
            if isinstance(report, dict) and report.get("status") == "ready":
                return
        time.sleep(1)
    raise StartupError("后端未能就绪；请查看 cascade/backend/logs/stderr.log 和 stdout.log")


def start(port, test=False, no_browser=False, timeout=180):
    reused = existing_backend(port, test)
    if not ENV_FILE.is_file():
        shutil.copyfile(BACKEND / ".env.example", ENV_FILE)
        raise StartupError("已生成 cascade/backend/.env；请填写 LLM_API_KEY 和 TTS_API_KEY 后重新启动")
    ensure_environment()
    report = health_report(test, config_only=True)
    if report["status"] != "ready":
        show_checks(report)
        raise StartupError("配置检查未通过，请修正后重新启动")
    check_docker()
    prepare_services(test)
    wait_dependencies(test, timeout)
    if not reused:
        print("[启动] 启动本机后端", flush=True)
        start_backend(port, test)
    wait_backend(port, test, min(timeout, 30))
    print(f"[就绪] {'复用已有服务' if reused else '启动完成'}：http://localhost:{port}", flush=True)
    if not no_browser:
        webbrowser.open(f"http://localhost:{port}")


def doctor(port, test=False):
    ok = True
    try:
        require_configuration_file()
        print("[OK] 项目配置文件存在", flush=True)
    except StartupError as error:
        print("[FAIL] " + str(error), flush=True)
        ok = False
    try:
        check_docker()
        print("[OK] Docker 引擎和 Compose 可用", flush=True)
    except StartupError as error:
        print("[FAIL] " + str(error), flush=True)
        ok = False
    if dependencies_ready():
        report = health_report(test)
        show_checks(report)
        ok = ok and report["status"] == "ready"
    else:
        print("[FAIL] Python 虚拟环境或依赖缺失；运行启动入口自动准备", flush=True)
        ok = False
    try:
        if not existing_backend(port, test):
            raise StartupError(f"后端 {port} 未启动；运行启动入口")
        print(f"[OK] 本项目后端 {port} 在线", flush=True)
    except StartupError as error:
        print("[FAIL] " + str(error), flush=True)
        ok = False
    return 0 if ok else 1


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="小云：一键启动或只读故障自检")
    parser.add_argument("action", choices=("start", "doctor"))
    parser.add_argument("--test", action="store_true", help="8081 + 配置库名_test 独立测试环境")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--timeout", type=int, default=180, choices=range(1, 601), metavar="1..600")
    args = parser.parse_args()
    port = 8081 if args.test else 8080
    try:
        if args.action == "doctor":
            return doctor(port, args.test)
        with startup_lock(port):
            start(port, args.test, args.no_browser, args.timeout)
        return 0
    except (StartupError, KeyboardInterrupt) as error:
        print("[FAIL] " + (str(error) or "已取消启动"), flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
