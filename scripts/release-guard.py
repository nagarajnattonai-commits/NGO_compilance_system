"""Small CI guard for accidental release artifacts, secrets, and skipped Phase 25 tests."""
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_NAMES = re.compile(r"(^|/)(\.env($|\.)|.*\.(dump|bak|pem|key)$)")
PRIVATE_KEY = re.compile(rb"BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY")


def main() -> None:
    tracked = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).split(b"\0")
    problems = []
    for raw in tracked:
        if not raw:
            continue
        name = raw.decode()
        if name == "deploy/.env.white-label.example":
            continue
        if FORBIDDEN_NAMES.search(name):
            problems.append("forbidden tracked release artifact: " + name)
        path = ROOT / name
        if path.is_file() and PRIVATE_KEY.search(path.read_bytes()):
            problems.append("private key material detected: " + name)
        if "phase25" in name.lower() and path.is_file():
            text = path.read_text("utf-8", errors="ignore")
            if re.search(r"(?:test\.(?:skip|only|fixme)|pytest\.mark\.skip)", text):
                problems.append("focused release test is skipped or isolated: " + name)
    if problems:
        raise SystemExit("\n".join(problems))
    print("Release guard passed: no tracked env/dump/key artifacts, private keys, or skipped Phase 25 tests.")


if __name__ == "__main__":
    main()
