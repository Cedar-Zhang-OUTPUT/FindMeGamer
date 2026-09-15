"""Add only /v1 to the known existing proxy, preserving a rollback copy."""

from pathlib import Path
import os
import subprocess
import time


def run(*args):
    subprocess.run(args, check=True)


def main():
    if os.geteuid() != 0:
        raise SystemExit("Run as root on EC2")
    path = Path("/opt/find-me-gamer/Caddyfile")
    old = path.read_text()
    if "handle /v1/*" in old:
        raise SystemExit("Route already exists; inspect first")
    needle = "\thandle @backend {"
    if old.count(needle) != 1:
        raise SystemExit("Unexpected proxy configuration")
    content = old.replace(
        needle,
        "\thandle /v1/* {\n\t\treverse_proxy fmg-agent-api-1:8000\n\t}\n\n" + needle,
    )
    backup = Path("/var/backups/find-me-gamer-agent")
    backup.mkdir(mode=0o700, parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    original = backup / ("Caddyfile-" + stamp)
    with original.open("x") as f:
        os.fchmod(f.fileno(), 0o600)
        f.write(old)
    candidate = backup / ("Caddyfile-candidate-" + stamp)
    candidate.write_text(content)
    candidate.chmod(0o600)
    run(
        "docker", "cp", str(candidate), "find-me-gamer-proxy-1:/tmp/fmg-caddy-candidate"
    )
    run(
        "docker",
        "exec",
        "find-me-gamer-proxy-1",
        "caddy",
        "validate",
        "--config",
        "/tmp/fmg-caddy-candidate",
        "--adapter",
        "caddyfile",
    )
    try:
        # Preserve the existing bind-mounted inode.
        path.write_text(content)
        mounted = subprocess.run(
            ["docker", "exec", "find-me-gamer-proxy-1", "cat", "/etc/caddy/Caddyfile"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        if mounted != content:
            # Earlier atomic host replacement can leave a stale file bind mount.
            # A maintenance-window restart refreshes it without starting old API.
            run("docker", "restart", "find-me-gamer-proxy-1")
        run(
            "docker",
            "exec",
            "find-me-gamer-proxy-1",
            "caddy",
            "reload",
            "--config",
            "/etc/caddy/Caddyfile",
            "--adapter",
            "caddyfile",
        )
    except Exception:
        path.write_text(old)
        run(
            "docker",
            "exec",
            "find-me-gamer-proxy-1",
            "caddy",
            "reload",
            "--config",
            "/etc/caddy/Caddyfile",
            "--adapter",
            "caddyfile",
        )
        raise
    print("Enabled /v1; previous proxy retained at " + str(original))


if __name__ == "__main__":
    main()
