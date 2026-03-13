import base64
import http.client
import json
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

import pymongo


HOST = "127.0.0.1"
WARMUP_REQUESTS = 5
TOTAL_REQUESTS = 200
CONCURRENCY = 10
YAML_PATH = "examples/auth-users.yaml"


@dataclass(frozen=True)
class ServerConfig:
    name: str
    port: int
    db_name: str
    cmd: list[str]
    cwd: str | None
    env_vars: dict[str, str]
    # Runtime mounts at /users, compiled at /api/v1/users
    base_path: str = "/api/v1"


@dataclass
class BenchmarkResult:
    name: str
    requests: int
    rps: float
    p50_ms: float
    p95_ms: float
    avg_ms: float


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = int((len(ordered) - 1) * pct)
    return ordered[index]


def _send_request(
    port: int,
    method: str,
    path: str,
    headers: dict[str, str] | None = None,
    body: dict | None = None,
) -> tuple[int, float]:
    body_bytes = b""
    req_headers = dict(headers) if headers else {}
    if body is not None:
        body_bytes = json.dumps(body).encode("utf-8")
        req_headers["content-type"] = "application/json"
        req_headers["content-length"] = str(len(body_bytes))

    start = time.perf_counter()
    connection = http.client.HTTPConnection(HOST, port, timeout=10)
    try:
        connection.request(
            method,
            path,
            body=body_bytes if body_bytes else None,
            headers=req_headers,
        )
        response = connection.getresponse()
        response.read()
        latency_ms = (time.perf_counter() - start) * 1000
        return response.status, latency_ms
    finally:
        connection.close()


def _wait_until_ready(port: int, base_path: str, timeout_seconds: float = 30.0) -> None:
    deadline = time.time() + timeout_seconds
    probe_payload = {
        "email": "probe@bench.test",
        "password": "probepass123",
        "displayName": "Probe",
    }
    while time.time() < deadline:
        try:
            status, _ = _send_request(port, "POST", f"{base_path}/users", body=probe_payload)
            if status in (200, 201):
                return
        except OSError:
            pass
        time.sleep(0.2)
    raise RuntimeError(f"Server on port {port} did not start in time")


def _login_user(port: int, base_path: str, email: str, password: str) -> str | None:
    """Login and return JWT token, or None if login endpoint is not available."""
    login_payload = {"email": email, "password": password}
    try:
        status_code, _ = _send_request(port, "POST", f"{base_path}/users/login")
        # Just test connectivity; now do the real login
    except OSError:
        return None

    connection = http.client.HTTPConnection(HOST, port, timeout=10)
    try:
        body_bytes = json.dumps(login_payload).encode("utf-8")
        connection.request(
            "POST",
            f"{base_path}/users/login",
            body=body_bytes,
            headers={"content-type": "application/json", "content-length": str(len(body_bytes))},
        )
        response = connection.getresponse()
        if response.status not in (200, 201):
            response.read()
            return None
        data = json.loads(response.read())
        return data.get("token")
    except Exception:
        return None
    finally:
        connection.close()


def _seed_user(port: int, base_path: str) -> tuple[str, str]:
    payload = {
        "email": "seed@bench.test",
        "password": "benchpass123",
        "displayName": "Seed User",
    }
    connection = http.client.HTTPConnection(HOST, port, timeout=10)
    try:
        body_bytes = json.dumps(payload).encode("utf-8")
        connection.request(
            "POST",
            f"{base_path}/users",
            body=body_bytes,
            headers={"content-type": "application/json", "content-length": str(len(body_bytes))},
        )
        response = connection.getresponse()
        data = json.loads(response.read())
        user_id = data["id"]

        token = _login_user(port, base_path, "seed@bench.test", "benchpass123")
        if token:
            auth_header = f"Bearer {token}"
        else:
            auth_header = "Basic " + base64.b64encode(b"seed@bench.test:benchpass123").decode("ascii")

        return user_id, auth_header
    finally:
        connection.close()


def _benchmark_public(port: int, base_path: str) -> BenchmarkResult:
    latencies_ms: list[float] = []
    started = time.perf_counter()
    request_count = 0

    def _create_post(i: int) -> tuple[int, float]:
        payload = {
            "title": f"Benchmark Post {i}",
            "content": f"Content for post {i}",
        }
        return _send_request(port, "POST", f"{base_path}/posts", body=payload)

    with ThreadPoolExecutor(max_workers=CONCURRENCY) as pool:
        futures = [pool.submit(_create_post, i) for i in range(TOTAL_REQUESTS)]
        for future in as_completed(futures):
            status, latency = future.result()
            if status not in (200, 201):
                raise RuntimeError(f"Unexpected status code {status} in public benchmark")
            latencies_ms.append(latency)
            request_count += 1

    elapsed_seconds = time.perf_counter() - started
    return BenchmarkResult(
        name="public",
        requests=request_count,
        rps=request_count / elapsed_seconds,
        p50_ms=_percentile(latencies_ms, 0.50),
        p95_ms=_percentile(latencies_ms, 0.95),
        avg_ms=statistics.fmean(latencies_ms),
    )


def _benchmark_authenticated(
    port: int, base_path: str, seed_id: str, auth_header: str,
) -> BenchmarkResult:
    latencies_ms: list[float] = []
    started = time.perf_counter()
    request_count = 0

    # PUT replace excluded: it mutates the user ID and breaks concurrent auth
    operations = [
        ("GET", f"{base_path}/users", None),
        ("GET", f"{base_path}/users/{seed_id}", None),
        ("PATCH", f"{base_path}/users/{seed_id}", {"displayName": "Updated"}),
    ]

    def _exec_operation(i: int) -> tuple[int, float]:
        method, path, body = operations[i % len(operations)]
        return _send_request(port, method, path, headers={"authorization": auth_header}, body=body)

    with ThreadPoolExecutor(max_workers=CONCURRENCY) as pool:
        futures = [pool.submit(_exec_operation, i) for i in range(TOTAL_REQUESTS)]
        for future in as_completed(futures):
            status, latency = future.result()
            if status != 200:
                raise RuntimeError(f"Unexpected status code {status} in authenticated benchmark")
            latencies_ms.append(latency)
            request_count += 1

    elapsed_seconds = time.perf_counter() - started
    return BenchmarkResult(
        name="authenticated",
        requests=request_count,
        rps=request_count / elapsed_seconds,
        p50_ms=_percentile(latencies_ms, 0.50),
        p95_ms=_percentile(latencies_ms, 0.95),
        avg_ms=statistics.fmean(latencies_ms),
    )


def _drop_database(db_name: str) -> None:
    client = pymongo.MongoClient("mongodb://localhost:27017")
    try:
        client.drop_database(db_name)
    finally:
        client.close()


def _run_warmup(port: int, base_path: str, auth_header: str, seed_id: str) -> None:
    operations = [
        ("POST", f"{base_path}/users", {"email": f"warmup-{i}@bench.test", "password": "warmup123", "displayName": "Warmup"})
        if i % 2 == 0
        else ("GET", f"{base_path}/users/{seed_id}", None)
        for i in range(WARMUP_REQUESTS)
    ]
    for method, path, body in operations:
        headers = {"authorization": auth_header} if method == "GET" else None
        _send_request(port, method, path, headers=headers, body=body)


def _benchmark_server(config: ServerConfig) -> tuple[BenchmarkResult, BenchmarkResult]:
    print(f"\n=== {config.name} (port {config.port}) ===")
    print("Starting server...")

    env = os.environ.copy()
    env.update(config.env_vars)

    process = subprocess.Popen(
        config.cmd,
        cwd=config.cwd,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    try:
        _wait_until_ready(config.port, config.base_path)
        print("Server ready.")

        print("Seeding test user...")
        seed_id, auth_header = _seed_user(config.port, config.base_path)

        print("Running warmup...")
        _run_warmup(config.port, config.base_path, auth_header, seed_id)

        print(f"Running public benchmark ({TOTAL_REQUESTS} requests)...")
        public_result = _benchmark_public(config.port, config.base_path)

        print(f"Running authenticated benchmark ({TOTAL_REQUESTS} requests)...")
        auth_result = _benchmark_authenticated(config.port, config.base_path, seed_id, auth_header)

        return public_result, auth_result
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)

        _drop_database(config.db_name)


def _print_results_table(title: str, results: list[tuple[str, BenchmarkResult]]) -> None:
    print(f"\n=== {title} ===")
    print(f"{'name':<20}{'req/s':<10}{'p50(ms)':<10}{'p95(ms)':<10}{'avg(ms)':<10}")
    print("-" * 60)
    for name, result in results:
        print(
            f"{name:<20}{result.rps:<10.2f}{result.p50_ms:<10.2f}"
            f"{result.p95_ms:<10.2f}{result.avg_ms:<10.2f}"
        )


def main() -> None:
    print(f"Benchmark: {YAML_PATH}")
    print(
        f"Config: requests={TOTAL_REQUESTS}/category, concurrency={CONCURRENCY}, warmup={WARMUP_REQUESTS}"
    )

    fastapi_dir = tempfile.mkdtemp(prefix="bench_fastapi_")
    drf_dir = tempfile.mkdtemp(prefix="bench_drf_")
    raw_dir = tempfile.mkdtemp(prefix="bench_raw_")

    try:
        print("\nCompiling targets...")
        print(f"  fastapi -> {fastapi_dir}")
        subprocess.run(
            ["yaml-api", "compile", YAML_PATH, "--target", "fastapi", "--output", fastapi_dir],
            check=True,
        )

        print(f"  drf -> {drf_dir}")
        subprocess.run(
            ["yaml-api", "compile", YAML_PATH, "--target", "drf", "--output", drf_dir],
            check=True,
        )

        print(f"  raw -> {raw_dir}")
        subprocess.run(
            ["yaml-api", "compile", YAML_PATH, "--target", "raw", "--output", raw_dir],
            check=True,
        )

        print("Installing DRF dependencies...")
        subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "-r",
                os.path.join(drf_dir, "requirements.txt"),
                "-q",
            ],
            check=True,
        )

        servers = [
            ServerConfig(
                name="runtime-fastapi",
                port=8101,
                db_name="bench_runtime",
                cmd=["yaml-api", "dev", YAML_PATH, "--port", "8101", "--host", HOST],
                cwd=None,
                env_vars={"YAML_API_MONGO_DB": "bench_runtime"},
                base_path="",
            ),
            ServerConfig(
                name="runtime-raw",
                port=8104,
                db_name="bench_runtime_raw",
                cmd=["yaml-api", "dev", YAML_PATH, "--port", "8104", "--host", HOST, "--raw"],
                cwd=None,
                env_vars={"YAML_API_MONGO_DB": "bench_runtime_raw"},
                base_path="",
            ),
            ServerConfig(
                name="compiled-fastapi",
                port=8102,
                db_name="bench_fastapi",
                cmd=[
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "app:app",
                    "--host",
                    HOST,
                    "--port",
                    "8102",
                    "--log-level",
                    "warning",
                    "--no-access-log",
                ],
                cwd=fastapi_dir,
                env_vars={"MONGO_DB": "bench_fastapi"},
            ),
            ServerConfig(
                name="compiled-drf",
                port=8103,
                db_name="bench_drf",
                cmd=[
                    sys.executable,
                    "-m",
                    "gunicorn",
                    "project.wsgi",
                    "--bind",
                    f"{HOST}:8103",
                    "--log-level",
                    "warning",
                    "--access-logfile",
                    "/dev/null",
                ],
                cwd=drf_dir,
                env_vars={"MONGO_DB": "bench_drf"},
            ),
            ServerConfig(
                name="compiled-raw",
                port=8105,
                db_name="bench_raw",
                cmd=[
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "app:app",
                    "--host",
                    HOST,
                    "--port",
                    "8105",
                    "--log-level",
                    "warning",
                    "--no-access-log",
                ],
                cwd=raw_dir,
                env_vars={"MONGO_DB": "bench_raw"},
            ),
        ]

        all_results: dict[str, tuple[BenchmarkResult, BenchmarkResult]] = {}
        for server in servers:
            public_result, auth_result = _benchmark_server(server)
            all_results[server.name] = (public_result, auth_result)

        _print_results_table(
            "Results: Public Endpoints (POST /api/v1/posts)",
            [(name, res[0]) for name, res in all_results.items()],
        )

        _print_results_table(
            "Results: Authenticated Endpoints (GET/PATCH with JWT Bearer)",
            [(name, res[1]) for name, res in all_results.items()],
        )

    finally:
        print("\nCleaning up...")
        shutil.rmtree(fastapi_dir, ignore_errors=True)
        shutil.rmtree(drf_dir, ignore_errors=True)
        shutil.rmtree(raw_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
