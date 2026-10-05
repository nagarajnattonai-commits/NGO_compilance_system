"""Restore a PostgreSQL backup into an explicitly isolated rehearsal database."""
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import unquote, urlsplit, urlunsplit


def safe_cli_url(value: str) -> tuple[str, dict[str, str]]:
    parsed = urlsplit(value.replace("postgresql+psycopg://", "postgresql://", 1))
    host = parsed.hostname or ""
    netloc = ((unquote(parsed.username) + "@") if parsed.username else "") + host
    if parsed.port:
        netloc += ":" + str(parsed.port)
    environment = dict(os.environ)
    if parsed.password:
        environment["PGPASSWORD"] = unquote(parsed.password)
    return urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, "")), environment


def main() -> None:
    source = os.getenv("SOURCE_DATABASE_URL", "")
    target = os.getenv("RESTORE_DATABASE_URL", "")
    target_name = urlsplit(target.replace("postgresql+psycopg://", "postgresql://", 1)).path.lower()
    if not source.startswith("postgresql") or not target.startswith("postgresql"):
        raise SystemExit("SOURCE_DATABASE_URL and RESTORE_DATABASE_URL must be PostgreSQL URLs")
    if source == target or not any(marker in target_name for marker in ("rehearsal", "restore")):
        raise SystemExit("Restore target must be a separate database named with 'rehearsal' or 'restore'")
    source_cli, source_environment = safe_cli_url(source)
    target_cli, target_environment = safe_cli_url(target)
    with tempfile.TemporaryDirectory(prefix="setu-restore-") as directory:
        dump = Path(directory) / "backup.dump"
        subprocess.run(["pg_dump", "--format=custom", "--file", str(dump), "--dbname", source_cli],
                       env=source_environment, check=True)
        subprocess.run(["pg_restore", "--exit-on-error", "--no-owner", "--no-privileges",
                        "--dbname", target_cli, str(dump)], env=target_environment, check=True)
        environment = dict(os.environ, DATABASE_URL=target)
        subprocess.run([sys.executable, "-m", "app.production_ops", "--check"],
                       cwd=Path(__file__).resolve().parents[1] / "apps" / "api", env=environment, check=True)
    print("Restore rehearsal passed against the isolated target database; temporary dump removed.")


if __name__ == "__main__":
    main()
