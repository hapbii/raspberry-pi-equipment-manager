from __future__ import annotations

import gc
import socket
import threading
import unittest
import weakref
from unittest.mock import patch

from waitress import create_server
from waitress.server import TcpWSGIServer
from waitress.task import ThreadedTaskDispatcher

from equipment_manager.web_server import run_web_server


class Application:
    def __call__(self, environ, start_response):
        start_response("200 OK", [("Content-Type", "text/plain")])
        return [b"ok"]


class WebServerLifecycleTestCase(unittest.TestCase):
    def test_repeated_bind_failures_leave_no_threads_sockets_or_app_references(self):
        baseline = set(threading.enumerate())
        references = []
        with socket.socket() as occupied:
            occupied.bind(("127.0.0.1", 0))
            occupied.listen()
            for _ in range(40):
                app = Application()
                references.append(weakref.ref(app))
                channels = {}

                def create(*args, **kwargs):
                    nonlocal channels
                    channels = kwargs["map"]
                    return create_server(*args, **kwargs)

                with patch("equipment_manager.web_server.create_server", side_effect=create):
                    with self.assertRaises(OSError):
                        run_web_server(app, host="127.0.0.1", port=occupied.getsockname()[1])
                self.assertEqual(channels, {})
                del app
        gc.collect()
        self.assertTrue(all(reference() is None for reference in references))
        self.assertEqual(set(threading.enumerate()), baseline)

    def test_normal_exit_and_loop_error_close_listener_and_workers(self):
        baseline = set(threading.enumerate())
        for error in (None, RuntimeError("loop failed"), KeyboardInterrupt()):
            with self.subTest(error=type(error).__name__):
                servers = []

                def create(*args, **kwargs):
                    server = create_server(*args, **kwargs)
                    servers.append(server)
                    return server

                with patch("equipment_manager.web_server.create_server", side_effect=create), \
                     patch.object(TcpWSGIServer, "run", side_effect=error):
                    if error is None:
                        run_web_server(Application(), host="127.0.0.1", port=0)
                    else:
                        with self.assertRaises(type(error)):
                            run_web_server(Application(), host="127.0.0.1", port=0)
                server = servers[0]
                self.assertEqual(server._map, {})
                self.assertEqual(len(server.task_dispatcher.threads), 0)
                with socket.socket() as listener:
                    listener.bind(("127.0.0.1", int(server.effective_port)))
        self.assertEqual(set(threading.enumerate()), baseline)

    def test_worker_start_failure_closes_already_bound_sockets(self):
        original = ThreadedTaskDispatcher.set_thread_count
        channels = {}

        def fail_start(dispatcher, count):
            if count:
                raise RuntimeError("no worker available")
            return original(dispatcher, count)

        def create(*args, **kwargs):
            nonlocal channels
            channels = kwargs["map"]
            return create_server(*args, **kwargs)

        with patch("equipment_manager.web_server.create_server", side_effect=create), \
             patch.object(ThreadedTaskDispatcher, "set_thread_count", fail_start):
            with self.assertRaisesRegex(RuntimeError, "no worker"):
                run_web_server(Application(), host="127.0.0.1", port=0)
        self.assertEqual(channels, {})
