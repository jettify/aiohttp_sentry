import asyncio
import unittest
import socket
from unittest import mock
from raven import Client
from aiohttp import web

from functools import wraps
from aiohttp_sentry import get_sentry, middleware, setup

def run_until_complete(fun):
    if not asyncio.iscoroutinefunction(fun):
        fun = asyncio.coroutine(fun)

    @wraps(fun)
    def wrapper(test, *args, **kw):
        loop = test.loop
        ret = loop.run_until_complete(
            asyncio.wait_for(fun(test, *args, **kw), 15, loop=loop))
        return ret
    return wrapper


def find_unused_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    return port


class BaseTest(unittest.TestCase):
    """Base test case for unittests.
    """
    def setUp(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(None)
        self.port = find_unused_port()
        self.url = "http://127.0.0.1:{}".format(self.port)

    def tearDown(self):
        self.loop.close()
        del self.loop

    def prepare_app(self):

        @asyncio.coroutine
        def error(request):
            try:
                raise Exception("Damn it!")
            except Exception:
                sentry = get_sentry(request.app)
                sentry.captureException(True)

        @asyncio.coroutine
        def send_error(request):
            raise Exception("Oops")

        @asyncio.coroutine
        def send_error_custom_dict(request):
            try:
                raise Exception("Damn it!")
            except Exception:
                sentry = get_sentry(request.app)
                sentry.captureException(
                    True, data={'extra': {'extra_data': 'extra data'}})


        app = web.Application(loop=self.loop, middlewares=[middleware])
        setup(app, 'http://public_key:secret_key@host:9000/project')

        app.router.add_route('GET', '/an-error', error)
        app.router.add_route('GET', '/send-error', send_error)
        app.router.add_route('GET', '/an-error-with-custom-dict-data',
                             send_error_custom_dict)
        handler = app.make_handler()
        srv = yield from self.loop.create_server(
            handler, '127.0.0.1', self.port)
        return app, srv, handler
