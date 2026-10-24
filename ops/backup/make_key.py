"""Create a non-overwriting age identity; legacy Fernet generation is explicit."""
import argparse
import os
from pathlib import Path

import backup as tool
from cryptography.fernet import Fernet


def create(path, *, format="fernet", age_keygen="age-keygen"):
    if format not in ("age", "fernet"):
        raise tool.BackupError("Unsupported key format")
    descriptor = os.open(Path(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            if format == "age":
                tool.run([str(age_keygen)], output=stream, timeout=30)
            else:
                stream.write(Fernet.generate_key() + b"\n")
    except (OSError, tool.BackupError):
        Path(path).unlink(missing_ok=True)
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path")
    parser.add_argument("--format", choices=["age", "fernet"], default="age")
    parser.add_argument("--age-keygen", default="age-keygen")
    args = parser.parse_args()
    create(args.path, format=args.format, age_keygen=args.age_keygen)
    print("New key created; verify separate custody and restricted filesystem ACLs")
