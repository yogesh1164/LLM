"""Create one non-overwriting Fernet key; operator controls separate key custody/ACLs."""
import argparse
import os
from pathlib import Path

from cryptography.fernet import Fernet


def create(path):
    descriptor = os.open(Path(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(Fernet.generate_key() + b"\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path")
    args = parser.parse_args()
    create(args.path)
    print("New key created; verify separate custody and restricted filesystem ACLs")
