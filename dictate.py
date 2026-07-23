#!/usr/bin/env python3
import subprocess
import os

FIFO = "/tmp/dictate.fifo"


def main():
    if not os.path.exists(FIFO):
        subprocess.run(["notify-send", "Dictation", "Daemon not running"], check=False)
        return
    with open(FIFO, "w") as f:
        f.write("toggle\n")


if __name__ == "__main__":
    main()
