"""cgamx infrastructure logic: the standalone MRVA lifecycle phases.

This is the Python port of what used to be
``cga/system-tests/standalone-multi-agent-lib.sh`` + the global phases of
``cga/system-tests/run-system-05`` (and the cga sample's ``cga-lib/infra.sh``). It
owns the MRVA *infrastructure*: Postgres, the MinIO artifact store, the CodeQL
DB HTTP server, and the ``mrvaserver`` process — plus the build, reset, log and
cleanup steps around them.

Design notes:

* Every function writes human/progress output to **stderr** (via ``cgast.info``)
  so the CGAST on stdout stays clean; ``cgamx`` is a CGAST filter like the other
  cga* programs.
* Configuration mirrors the shell library exactly: every value is read from the
  environment with a sane default, and the default is only computed when the
  variable is unset (``os.environ.setdefault``), so operator/harness overrides
  always win and spawned subprocesses (``mrvaserver``/``mrvaagent``) inherit the
  same values.
* Runtime process ids are recorded in the CGAST (the ``cgamx`` sub-object),
  which replaces the shell harness's ``state.env`` file. PID files under the tmp
  dir are still written as a backstop, and ``ss``-based port reclaim is the
  ultimate fallback (``lsof`` is not installed on the dev hosts here).

Standard library only, matching the rest of the cga skeleton.
"""

from __future__ import annotations

import os
import signal
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional

import cgast

# Tables + sequence the Go server creates in standalone mode. Kept here so
# reset (drop) and cleanup (drop) agree with the server's schema.
MRVA_TABLES = [
    "analyze_results", "analyze_jobs", "job_repo_map", "job_info",
    "job_status", "scheduler_lock", "worker_pool", "job_info_worker_id",
]
MRVA_SEQUENCES = ["session_id_seq"]


# ======================================================================
# Configuration
# ======================================================================

def _repo_root() -> Path:
    """Source checkout, independent of the configured CGAST artifact root."""
    return Path(__file__).resolve().parents[3]


def _setdefault(name: str, value: str) -> str:
    """os.environ.setdefault, returning the effective value."""
    return os.environ.setdefault(name, value)


def _default_postgres_port(host: str) -> str:
    """Use the active local Debian cluster port, falling back to 5432."""
    if host not in ("localhost", "127.0.0.1", "::1"):
        return "5432"
    if not shutil.which("pg_lsclusters"):
        return "5432"
    try:
        result = subprocess.run(
            ["pg_lsclusters", "--no-header"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return "5432"
    for line in result.stdout.splitlines():
        fields = line.split()
        if len(fields) >= 4 and fields[3] == "online" and fields[2].isdigit():
            return fields[2]
    return "5432"


def _postgres_executable() -> Optional[Path]:
    direct = shutil.which("postgres")
    if direct:
        return Path(direct)
    pg_config = shutil.which("pg_config")
    if pg_config:
        try:
            result = subprocess.run(
                [pg_config, "--bindir"],
                capture_output=True,
                text=True,
                check=False,
            )
            candidate = Path(result.stdout.strip()) / "postgres"
            if candidate.is_file():
                return candidate
        except OSError:
            pass
    candidates = sorted(
        Path("/usr/lib/postgresql").glob("*/bin/postgres"),
        reverse=True,
    )
    return candidates[0] if candidates else None


def _postgres_clusters() -> List[Dict[str, str]]:
    if not shutil.which("pg_lsclusters"):
        return []
    try:
        result = subprocess.run(
            ["pg_lsclusters", "--no-header"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return []
    clusters = []
    for line in result.stdout.splitlines():
        fields = line.split()
        if len(fields) < 4 or not fields[2].isdigit():
            continue
        clusters.append({
            "version": fields[0],
            "name": fields[1],
            "port": fields[2],
            "status": fields[3],
        })
    return clusters


def postgres_presence_check() -> Dict[str, object]:
    """Report configure-style PostgreSQL installation and endpoint findings."""
    executable = _postgres_executable()
    cgast.info(
        "checking for PostgreSQL server executable... "
        + (str(executable) if executable else "no")
    )
    version = None
    if executable:
        try:
            result = subprocess.run(
                [str(executable), "--version"],
                capture_output=True,
                text=True,
                check=False,
            )
            version = result.stdout.strip() or result.stderr.strip() or None
        except OSError:
            version = None
    cgast.info(f"checking PostgreSQL server version... {version or 'unknown'}")

    pg_isready = shutil.which("pg_isready")
    cgast.info(f"checking for pg_isready... {pg_isready or 'no'}")
    clusters = _postgres_clusters()
    if clusters:
        cluster_summary = ", ".join(
            f"{item['version']}/{item['name']} {item['status']} "
            f"port {item['port']}"
            for item in clusters
        )
    else:
        cluster_summary = "none found"
    cgast.info(f"checking for local PostgreSQL clusters... {cluster_summary}")

    host = os.environ["POSTGRES_HOST"]
    configured_port = os.environ["POSTGRES_PORT"]
    ports = []
    for port in (
        configured_port,
        *(item["port"] for item in clusters),
        "5432",
        "5433",
        "55432",
        "55440",
    ):
        if port.isdigit() and port not in ports:
            ports.append(port)

    endpoints = []
    for port in ports:
        accepting = False
        detail = "pg_isready unavailable"
        if pg_isready:
            try:
                result = subprocess.run(
                    [pg_isready, "-h", host, "-p", port, "-t", "1"],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                accepting = result.returncode == 0
                detail = (
                    result.stdout.strip()
                    or result.stderr.strip()
                    or f"exit {result.returncode}"
                )
            except OSError as error:
                detail = str(error)
        label = "configured" if port == configured_port else "likely"
        cgast.info(
            f"checking PostgreSQL at {host}:{port} ({label})... "
            f"{'yes' if accepting else 'no'}"
            + (f" ({detail})" if detail else "")
        )
        endpoints.append({
            "host": host,
            "port": int(port),
            "configured": port == configured_port,
            "accepting": accepting,
            "detail": detail,
        })

    accepting_ports = [
        str(item["port"]) for item in endpoints if item["accepting"]
    ]
    configured_ready = any(
        item["configured"] and item["accepting"] for item in endpoints
    )
    cgast.info(
        "PostgreSQL findings: "
        f"server={'found' if executable else 'not found'}, "
        f"clusters={len(clusters)}, "
        f"accepting_ports={','.join(accepting_ports) or 'none'}, "
        f"configured_endpoint={'ready' if configured_ready else 'not ready'}"
    )
    return {
        "executable": str(executable) if executable else None,
        "version": version,
        "pg_isready": pg_isready,
        "clusters": clusters,
        "endpoints": endpoints,
        "configured_endpoint_ready": configured_ready,
    }


def config() -> Dict[str, str]:
    """Resolve every infrastructure setting, defaulting only when unset.

    Mutates ``os.environ`` (via setdefault) so children inherit identical
    values, then returns the effective settings as a dict for convenience.
    """
    repo = _repo_root()

    # CodeQL ships an x86_64 JRE that cannot exec on arm64; point it at the
    # system JDK. Harmless on x86_64 Linux where /usr also holds a JDK.
    _setdefault("CODEQL_JAVA_HOME", "/usr")

    # --- server -----------------------------------------------------------
    port = _setdefault("PORT", "8081")
    _setdefault("SERVER_PORT", port)

    # --- Postgres ---------------------------------------------------------
    _setdefault("POSTGRES_DB", "mrvadev")
    postgres_host = _setdefault("POSTGRES_HOST", "localhost")
    _setdefault("POSTGRES_PORT", _default_postgres_port(postgres_host))
    _setdefault("POSTGRES_USER", os.environ.get("USER", "postgres"))
    _setdefault("POSTGRES_PASSWORD", "mrva")
    # Let every psql invocation authenticate over TCP without a prompt.
    os.environ["PGPASSWORD"] = os.environ["POSTGRES_PASSWORD"]

    # --- filesystem stores + logs ----------------------------------------
    work = _setdefault("MRVA_WORK_DIR", "/tmp/mrva-cgamx")
    _setdefault("MRVA_ARTIFACT_DIR", f"{work}/artifacts")
    _setdefault("MRVA_QLDB_DIR", f"{work}/qldbs")
    run_tag = _setdefault("RUN_TAG", "cgamx")
    tmp = _setdefault("MRVA_TMP_DIR", f"/tmp/mrva-{run_tag}")
    Path(tmp).mkdir(parents=True, exist_ok=True)

    # --- CodeQL DB HTTP server -------------------------------------------
    db_port = _setdefault("DB_SERVER_PORT", "9080")
    _setdefault("MRVA_DB_SERVER_URL", f"http://127.0.0.1:{db_port}")
    _setdefault("MRVA_DB_SERVE_DIR", f"{work}/db-serve")
    _setdefault("DB_SERVER_LOG", f"{tmp}/db-server.log")
    _setdefault("DB_SERVER_PID_FILE", f"{tmp}/db-server.pid")

    # --- object storage --------------------------------------------------
    # Local default is filesystem; set MRVA_STANDALONE_STORAGE=minio to exercise S3.
    _setdefault("MRVA_STANDALONE_STORAGE", "filesystem")
    minio_port = _setdefault("MINIO_PORT", "9000")
    _setdefault("MRVA_MINIO_ENDPOINT", f"localhost:{minio_port}")
    _setdefault("MRVA_MINIO_ACCESS_KEY", "minioadmin")
    _setdefault("MRVA_MINIO_SECRET_KEY", "minioadmin")
    _setdefault("MINIO_DATA_DIR", f"{work}/minio-data")
    _setdefault("MINIO_LOG", f"{tmp}/minio.log")
    _setdefault("MINIO_PID_FILE", f"{tmp}/minio.pid")
    # Must be the community (AGPLv3) MinIO build; the enterprise "AIStor" build
    # denies all S3 operations without a license.
    _setdefault("MINIO_BIN", "minio")
    _setdefault("MINIO_BUCKET", "mrvabucket")

    # --- server / agent binaries + runtime knobs -------------------------
    _setdefault("MRVA_STANDALONE", "true")
    _setdefault("MRVA_ENVSIM_AGENT_BINARY",
                str(repo / "agent-commander-argo" / "mrvaagent"))
    _setdefault("CODEQL_CLI_PATH", shutil.which("codeql") or "")

    # Worker-pool sizing (overridable). Default to 2 cores per worker and
    # (syscores - 1) / cores-per-worker workers, matching the Go standalone
    # defaults. Explicit env values always win.
    threads = int(_setdefault("MRVA_CODEQL_THREADS", "2"))
    syscores = os.cpu_count() or 1
    default_workers = max(1, (syscores - 1) // max(1, threads))
    _setdefault("MRVA_POOL_MAX_WORKERS", str(default_workers))
    _setdefault("MRVA_POOL_SCALE_CHECK_SECONDS", "2")
    _setdefault("MRVA_POOL_CLAIM_POLL_SECONDS", "2")

    # Optional sysview capture (off by default).
    _setdefault("MRVA_DBG_DUMP_SYSVIEW", "")
    _setdefault("MRVA_SYSVIEW_DUMP_PATH", "sysview-dump")

    _setdefault("SERVER_LOG", f"{tmp}/server.log")
    _setdefault("SERVER_PID_FILE", f"{tmp}/server.pid")

    return dict(os.environ)


def _server_url() -> str:
    return f"http://127.0.0.1:{os.environ['PORT']}"


def storage_is_minio() -> bool:
    return os.environ.get("MRVA_STANDALONE_STORAGE") == "minio"


def db_server_enabled() -> bool:
    return bool(os.environ.get("MRVA_DB_SERVER_URL"))


# ======================================================================
# Low-level helpers
# ======================================================================

def _run(cmd: List[str], **kwargs) -> subprocess.CompletedProcess:
    """Run a command with output going to stderr (keeps stdout = CGAST)."""
    kwargs.setdefault("stdout", sys.stderr)
    kwargs.setdefault("stderr", sys.stderr)
    return subprocess.run(cmd, **kwargs)


def pids_on_port(port: str) -> List[int]:
    """PIDs listening on a TCP port (via ss; lsof is not installed here)."""
    try:
        out = subprocess.run(
            ["ss", "-ltnp"], capture_output=True, text=True, check=False).stdout
    except FileNotFoundError:
        return []
    pids: List[int] = []
    needle = f":{port}"
    for line in out.splitlines():
        cols = line.split()
        if len(cols) < 4 or not cols[3].endswith(needle):
            continue
        for tok in line.split("pid=")[1:]:
            digits = ""
            for ch in tok:
                if ch.isdigit():
                    digits += ch
                else:
                    break
            if digits:
                pids.append(int(digits))
    return sorted(set(pids))


def reclaim_port(port: str, label: str) -> None:
    pids = pids_on_port(port)
    if pids:
        cgast.info(f"killing stale processes on {label} port {port}: "
                   f"{' '.join(map(str, pids))}")
        for pid in pids:
            _kill(pid)
        time.sleep(1)


def _kill(pid: int) -> bool:
    """Terminate a detached service and every descendant in its process group.

    Services started by :func:`_spawn_detached` are session/process-group
    leaders. Killing only the leader can orphan agents and CodeQL subprocesses;
    the group id remains equal to the original leader pid even after that
    process exits. Fall back to the individual pid for a listener discovered
    on a port that is not a group leader.
    """
    try:
        os.killpg(pid, signal.SIGTERM)
        return True
    except ProcessLookupError:
        pass
    except PermissionError:
        return False
    try:
        os.kill(pid, signal.SIGTERM)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def _http_ok(url: str, timeout: float = 1.0) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return 200 <= resp.status < 500
    except Exception:
        return False


def _wait_http(url: str, tries: int = 40, delay: float = 0.5) -> bool:
    for _ in range(tries):
        if _http_ok(url):
            return True
        time.sleep(delay)
    return False


def _spawn_detached(cmd: List[str], log_path: str,
                    env: Optional[Dict[str, str]] = None) -> int:
    """Start a fully detached background process, output to a log file."""
    Path(log_path).parent.mkdir(parents=True, exist_ok=True)
    logf = open(log_path, "wb")
    devnull = open(os.devnull, "rb")
    proc = subprocess.Popen(
        cmd, stdin=devnull, stdout=logf, stderr=subprocess.STDOUT,
        start_new_session=True, env=env)
    return proc.pid


def _write_pidfile(path: str, pid: int) -> None:
    try:
        Path(path).write_text(f"{pid}\n", encoding="utf-8")
    except OSError:
        pass


def _read_pidfile(path: str) -> Optional[int]:
    try:
        return int(Path(path).read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


# ======================================================================
# Postgres
# ======================================================================

def psql_mrva(args: List[str], **kwargs) -> subprocess.CompletedProcess:
    cmd = ["psql",
           "-h", os.environ["POSTGRES_HOST"],
           "-p", os.environ["POSTGRES_PORT"],
           "-U", os.environ["POSTGRES_USER"],
           "-d", os.environ["POSTGRES_DB"]] + args
    return subprocess.run(cmd, **kwargs)


def _pg_isready() -> bool:
    try:
        return subprocess.run(
            ["pg_isready", "-h", os.environ["POSTGRES_HOST"],
             "-p", os.environ["POSTGRES_PORT"]],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
    except FileNotFoundError:
        return False


def pg_ensure_running() -> None:
    if _pg_isready():
        return
    cgast.info("starting PostgreSQL")
    if shutil.which("systemctl"):
        for cmd in (["sudo", "systemctl", "start", "postgresql"],
                    ["systemctl", "start", "postgresql"]):
            if _run(cmd, check=False).returncode == 0:
                break
    elif shutil.which("pg_ctlcluster"):
        versions = sorted(Path("/usr/lib/postgresql").glob("*")) \
            if Path("/usr/lib/postgresql").is_dir() else []
        if versions:
            ver = versions[-1].name
            for cmd in (["sudo", "pg_ctlcluster", ver, "main", "start"],
                        ["pg_ctlcluster", ver, "main", "start"]):
                if _run(cmd, check=False).returncode == 0:
                    break
    for _ in range(30):
        if _pg_isready():
            return
        time.sleep(0.5)
    cgast.die(
        "PostgreSQL is not accepting connections at "
        f"{os.environ['POSTGRES_HOST']}:{os.environ['POSTGRES_PORT']}"
    )


def pg_ensure_role_db() -> None:
    if psql_mrva(["-c", "SELECT 1;"],
                 stdout=subprocess.DEVNULL,
                 stderr=subprocess.DEVNULL).returncode == 0:
        return
    user = os.environ["POSTGRES_USER"]
    password = os.environ["POSTGRES_PASSWORD"]
    db = os.environ["POSTGRES_DB"]
    cgast.info(f"bootstrapping role '{user}' and database '{db}'")
    role_sql = (
        "DO $$\nBEGIN\n"
        f"   IF EXISTS (SELECT FROM pg_roles WHERE rolname = '{user}') THEN\n"
        f"      ALTER ROLE \"{user}\" LOGIN CREATEDB PASSWORD '{password}';\n"
        "   ELSE\n"
        f"      CREATE ROLE \"{user}\" LOGIN CREATEDB PASSWORD '{password}';\n"
        "   END IF;\nEND\n$$;\n"
    )
    port = os.environ["POSTGRES_PORT"]
    _run(["sudo", "-u", "postgres", "psql", "-p", port,
          "-v", "ON_ERROR_STOP=1"],
         input=role_sql.encode(), stdout=sys.stderr, stderr=sys.stderr)
    exists = subprocess.run(
        ["sudo", "-u", "postgres", "psql", "-p", port, "-tAc",
         f"SELECT 1 FROM pg_database WHERE datname='{db}';"],
        capture_output=True, text=True).stdout
    if "1" not in exists:
        _run(["sudo", "-u", "postgres", "createdb", "-p", port,
              "-O", user, db], check=False)


def _drop_tables() -> None:
    tables = ", ".join(MRVA_TABLES)
    seqs = ", ".join(MRVA_SEQUENCES)
    sql = (f"DROP TABLE IF EXISTS {tables} CASCADE;\n"
           f"DROP SEQUENCE IF EXISTS {seqs} CASCADE;\n")
    psql_mrva(["-q", "-c", sql], stdout=subprocess.DEVNULL, stderr=sys.stderr)


# ======================================================================
# MinIO / DB server / mrvaserver lifecycle
# ======================================================================

def minio_reclaim_port() -> None:
    if storage_is_minio():
        reclaim_port(os.environ["MINIO_PORT"], "MinIO")


def minio_start(rt: Dict) -> None:
    if not storage_is_minio():
        return
    endpoint = os.environ["MRVA_MINIO_ENDPOINT"]
    port = os.environ["MINIO_PORT"]
    data = os.environ["MINIO_DATA_DIR"]
    cgast.info(f"--- starting MinIO on :{port} (data {data}) ---")
    if _http_ok(f"http://{endpoint}/minio/health/live"):
        cgast.info(f"  MinIO already running on {endpoint}")
        return
    minio_bin = os.environ["MINIO_BIN"]
    if not shutil.which(minio_bin):
        cgast.die(f"MinIO server '{minio_bin}' not found on PATH (install it, "
                  "or set MRVA_STANDALONE_STORAGE=filesystem)")
    Path(data).mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env["MINIO_ROOT_USER"] = os.environ["MRVA_MINIO_ACCESS_KEY"]
    env["MINIO_ROOT_PASSWORD"] = os.environ["MRVA_MINIO_SECRET_KEY"]
    pid = _spawn_detached(
        [minio_bin, "server", data, "--address", f":{port}"],
        os.environ["MINIO_LOG"], env=env)
    _write_pidfile(os.environ["MINIO_PID_FILE"], pid)
    rt["minio_pid"] = pid
    if _wait_http(f"http://{endpoint}/minio/health/live"):
        cgast.info(f"  MinIO up (pid {pid})")
        return
    cgast.die("MinIO did not come up (see " + os.environ["MINIO_LOG"] + ")")


def minio_stop(rt: Dict) -> None:
    if not storage_is_minio():
        return
    _stop_by_pid_and_port(rt, "minio_pid", os.environ["MINIO_PID_FILE"],
                          os.environ["MINIO_PORT"], "MinIO")


def db_server_reclaim_port() -> None:
    if db_server_enabled():
        reclaim_port(os.environ["DB_SERVER_PORT"], "DB-server")


def db_server_start(rt: Dict) -> None:
    if not db_server_enabled():
        return
    url = os.environ["MRVA_DB_SERVER_URL"]
    port = os.environ["DB_SERVER_PORT"]
    serve_dir = os.environ["MRVA_DB_SERVE_DIR"]
    cgast.info(f"--- starting CodeQL DB server on :{port} (root {serve_dir}) ---")
    if _http_ok(f"{url}/"):
        cgast.info(f"  DB server already running on {url}")
        return
    Path(serve_dir).mkdir(parents=True, exist_ok=True)
    pid = _spawn_detached(
        [sys.executable, "-m", "http.server", port, "--bind", "127.0.0.1",
         "--directory", serve_dir],
        os.environ["DB_SERVER_LOG"])
    _write_pidfile(os.environ["DB_SERVER_PID_FILE"], pid)
    rt["db_server_pid"] = pid
    if _wait_http(f"{url}/"):
        cgast.info(f"  DB server up (pid {pid})")
        return
    cgast.die("DB server did not come up (see " + os.environ["DB_SERVER_LOG"] + ")")


def db_server_stop(rt: Dict) -> None:
    if not db_server_enabled():
        return
    _stop_by_pid_and_port(rt, "db_server_pid", os.environ["DB_SERVER_PID_FILE"],
                          os.environ["DB_SERVER_PORT"], "DB-server")


def server_start(rt: Dict) -> None:
    port = os.environ["PORT"]
    cgast.info(f"--- starting Go server on :{port} (no Docker) ---")
    minio_start(rt)
    db_server_start(rt)
    cmd = [str(_repo_root() / "server-commander" / "mrvaserver"),
           "--mode=standalone", "--loglevel=info",
           f"--dbpath={os.environ['MRVA_QLDB_DIR']}"]
    if os.environ.get("MRVA_DBG_DUMP_SYSVIEW"):
        cmd.append("--dbg-dump-sysview")
    pid = _spawn_detached(cmd, os.environ["SERVER_LOG"], env=dict(os.environ))
    _write_pidfile(os.environ["SERVER_PID_FILE"], pid)
    rt["server_pid"] = pid
    if os.environ.get("MRVA_DBG_DUMP_SYSVIEW"):
        rt["sysview_dump"] = os.environ["MRVA_SYSVIEW_DUMP_PATH"]
    if _wait_http(_server_url() + "/", tries=20):
        cgast.info(f"  server up (pid {pid})")
        return
    cgast.info("ERROR: server did not come up. Tail:")
    _tail(os.environ["SERVER_LOG"], 30)
    raise SystemExit(1)


def _stop_by_pid_and_port(rt: Dict, rt_key: str, pid_file: str,
                          port: str, label: str) -> None:
    stopped = False
    seen = set()
    for pid in (rt.get(rt_key), _read_pidfile(pid_file)):
        if not pid or pid in seen:
            continue
        seen.add(pid)
        if _alive(pid) and _kill(pid):
            cgast.info(f"  sent SIGTERM to {label} pid {pid}")
            stopped = True
    for pid in pids_on_port(port):
        if _kill(pid):
            cgast.info(f"  killed process on {label} port {port}: {pid}")
            stopped = True
    try:
        os.remove(pid_file)
    except OSError:
        pass
    rt.pop(rt_key, None)
    if not stopped:
        cgast.info(f"  (no running {label} found)")


def server_stop(rt: Dict) -> None:
    cgast.info("--- stopping Go server (keeping state) ---")
    _stop_by_pid_and_port(rt, "server_pid", os.environ["SERVER_PID_FILE"],
                          os.environ["PORT"], "server")
    minio_stop(rt)
    db_server_stop(rt)


# ======================================================================
# Logs
# ======================================================================

def _tail(path: str, n: int) -> None:
    try:
        lines = Path(path).read_text(encoding="utf-8",
                                     errors="replace").splitlines()
    except OSError:
        cgast.info(f"  (no log at {path})")
        return
    for line in lines[-n:]:
        cgast.info(line)


def _error_lines(path: str) -> List[str]:
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    hits = []
    for line in text.splitlines():
        if ("ERROR" in line or "panic" in line or "fatal" in line) \
                and "mrva-project-resolver" not in line \
                and "Unhandled endpoint method=GET uri=/favicon.ico" not in line:
            hits.append(line)
    return hits


def error_check() -> bool:
    """True when the server log contains no non-benign errors."""
    hits = _error_lines(os.environ["SERVER_LOG"])
    if hits:
        cgast.info("errors (excluding known benign development requests):")
        for line in hits[:10]:
            cgast.info(line)
        return False
    cgast.info("NO ERRORS (known development-only warnings are benign)")
    return True


# ======================================================================
# Phases
# ======================================================================

def phase_preflight() -> Dict[str, object]:
    cgast.info("--- preflight ---")
    if not os.environ.get("CODEQL_CLI_PATH"):
        cgast.die("codeql not found on PATH")
    _run(["codeql", "version", "--format=terse"], check=False)
    _run(["go", "version"], check=False)
    findings = postgres_presence_check()
    pg_ensure_running()
    _run(["pg_isready", "-h", os.environ["POSTGRES_HOST"],
          "-p", os.environ["POSTGRES_PORT"]], check=False)
    pg_ensure_role_db()
    reclaim_port(os.environ["PORT"], "server")
    minio_reclaim_port()
    db_server_reclaim_port()
    return findings


def phase_reset(rt: Dict) -> None:
    cgast.info("--- reset (clean slate) ---")
    _drop_tables()
    work = os.environ["MRVA_WORK_DIR"]
    tmp = os.environ["MRVA_TMP_DIR"]
    shutil.rmtree(work, ignore_errors=True)
    shutil.rmtree(tmp, ignore_errors=True)
    for d in (os.environ["MRVA_ARTIFACT_DIR"], os.environ["MRVA_QLDB_DIR"],
              os.environ["MRVA_DB_SERVE_DIR"], tmp):
        Path(d).mkdir(parents=True, exist_ok=True)
    # Runtime pids from a previous run are gone with the wiped work dir.
    for key in ("server_pid", "minio_pid", "db_server_pid", "sysview_dump"):
        rt.pop(key, None)
    cgast.info(f"  dropped tables; wiped {work} and transient files")


def phase_build() -> None:
    cgast.info("--- building server + agent ---")
    rc = _run(["make", "-s", "-C", str(_repo_root() / "server-commander"),
               "mrvaserver", "mrvaagent"], check=False).returncode
    if rc != 0:
        raise SystemExit(rc)


def phase_logs() -> None:
    cgast.info("--- server log tail ---")
    _tail(os.environ["SERVER_LOG"], 25)
    cgast.info("--- errors in server log ---")
    error_check()


def phase_cleanup(rt: Dict) -> None:
    cgast.info("--- 1. stopping Go server ---")
    _stop_by_pid_and_port(rt, "server_pid", os.environ["SERVER_PID_FILE"],
                          os.environ["PORT"], "server")
    time.sleep(1)
    if storage_is_minio():
        cgast.info("--- 1b. stopping MinIO ---")
        minio_stop(rt)
    if db_server_enabled():
        cgast.info("--- 1c. stopping CodeQL DB server ---")
        db_server_stop(rt)

    cgast.info("--- 2. dropping mrva tables ---")
    if psql_mrva(["-c", "SELECT 1;"], stdout=subprocess.DEVNULL,
                 stderr=subprocess.DEVNULL).returncode == 0:
        _drop_tables()
        cgast.info(f"  dropped: {' '.join(MRVA_TABLES)}")
    else:
        cgast.info(f"  (cannot connect to {os.environ['POSTGRES_DB']}; "
                   "nothing dropped)")

    cgast.info("--- 3. removing work dir + logs ---")
    shutil.rmtree(os.environ["MRVA_WORK_DIR"], ignore_errors=True)
    shutil.rmtree(os.environ["MRVA_TMP_DIR"], ignore_errors=True)
    dump = rt.get("sysview_dump") or os.environ.get("MRVA_SYSVIEW_DUMP_PATH")
    if dump:
        try:
            os.remove(dump)
        except OSError:
            pass
    for key in ("server_pid", "minio_pid", "db_server_pid", "sysview_dump"):
        rt.pop(key, None)
    cgast.info(f"  removed {os.environ['MRVA_WORK_DIR']}, "
               f"{os.environ['MRVA_TMP_DIR']} and transient files")
    cgast.info("cleanup complete.")
