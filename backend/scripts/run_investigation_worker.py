"""CLI entrypoint to run the ClaimSage PostgreSQL investigation worker."""

import logging
import sys

from claimsage.workers.investigation_worker import InvestigationWorker

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


def main() -> None:
    if "--check-readiness" in sys.argv:
        try:
            worker = InvestigationWorker()
            info = worker.check_readiness()
            print(f"Worker readiness check passed: {info}")
            sys.exit(0)
        except Exception as exc:
            print(f"Worker readiness check failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            sys.exit(1)

    worker = InvestigationWorker()
    try:
        worker.start()
    except KeyboardInterrupt:
        worker.request_stop()
        sys.exit(0)


if __name__ == "__main__":
    main()
