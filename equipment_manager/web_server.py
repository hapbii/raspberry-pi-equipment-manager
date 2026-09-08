"""Own Waitress resources even when binding or starting workers fails."""
from __future__ import annotations

from waitress import create_server, wasyncore
from waitress.task import ThreadedTaskDispatcher

from .deployment import WAITRESS_OPTIONS


def run_web_server(app, **overrides) -> None:
    options = WAITRESS_OPTIONS | overrides
    channels = {}
    dispatcher = ThreadedTaskDispatcher()
    try:
        # Supply our own dispatcher so it remains available on partial startup.
        # Start workers only after all listening sockets have been bound.
        server = create_server(app, map=channels, _dispatcher=dispatcher, **options)
        dispatcher.set_thread_count(options["threads"])
        server.print_listen("Serving on http://{}:{}")
        server.run()
    finally:
        try:
            dispatcher.shutdown()
        finally:
            # Includes partially initialized listeners, wakeup sockets and clients.
            wasyncore.close_all(map=channels)
