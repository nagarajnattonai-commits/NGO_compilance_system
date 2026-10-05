"""Shared graceful-stop control for separately supervised background processes."""
import signal
from threading import Event

stop_event = Event()


def install_signal_handlers() -> None:
    def request_stop(_signum, _frame):
        stop_event.set()

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)


def wait(seconds: float) -> bool:
    """Return true when shutdown was requested while waiting."""
    return stop_event.wait(seconds)
