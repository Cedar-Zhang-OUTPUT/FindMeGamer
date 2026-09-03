from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys


class CommandInterrupted(Exception):
    def __init__(self, signum: int) -> None:
        self.signum = signum


def stop_process_group(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=2)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        pass


def main() -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--timeout", type=float, required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    arguments = parser.parse_args()
    command = arguments.command
    if command[:1] == ["--"]:
        command = command[1:]
    if arguments.timeout <= 0 or not command:
        parser.error("a positive timeout and command are required")

    def interrupt(signum: int, _frame: object) -> None:
        raise CommandInterrupted(signum)

    signal.signal(signal.SIGINT, interrupt)
    signal.signal(signal.SIGTERM, interrupt)
    process = subprocess.Popen(command, start_new_session=True)
    try:
        return process.wait(timeout=arguments.timeout)
    except subprocess.TimeoutExpired:
        stop_process_group(process)
        print(
            f"bounded command timed out after {arguments.timeout:g}s",
            file=sys.stderr,
        )
        return 124
    except CommandInterrupted as error:
        stop_process_group(process)
        return 128 + error.signum


if __name__ == "__main__":
    raise SystemExit(main())
