"""A background process that shares the backend image with the API."""

import os
import time


def main() -> None:
    interval = int(os.environ.get("WORKER_INTERVAL", "60"))
    while True:
        time.sleep(interval)


if __name__ == "__main__":
    main()
