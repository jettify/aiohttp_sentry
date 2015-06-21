import asyncio
import unittest
import socket
from unittest import mock
from aiohttp import web
import aiohttp
from functools import wraps
import aiohttp_sentry


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


class SentryTest(unittest.TestCase):
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

    @asyncio.coroutine
    def prepare_app(self, dsn):

        @asyncio.coroutine
        def send_error(request):
            raise Exception("Oops")

        @asyncio.coroutine
        def send_error_custom_dict(request):
            try:
                raise Exception("Damn it!")
            except Exception:
                sentry = aiohttp_sentry.get_sentry(request.app)
                yield from sentry.captureException(
                    True, data={"extra": {"extra_data": "extra data",
                                          "key": 10}})

        @asyncio.coroutine
        def no_error(request):
            payload = 'success'
            return web.Response(status=200, text=payload)

        @asyncio.coroutine
        def bad_request(request):
            raise web.HTTPBadRequest()

        app = web.Application(loop=self.loop,
                              middlewares=[aiohttp_sentry.middleware])
        aiohttp_sentry.setup(app, dsn)

        app.router.add_route('GET', '/send-error', send_error)
        app.router.add_route('GET', '/an-error-with-custom-dict-data',
                             send_error_custom_dict)
        app.router.add_route('GET', '/no-error', no_error)
        app.router.add_route('GET', '/bad-request', bad_request)

        handler = app.make_handler()
        srv = yield from self.loop.create_server(
            handler, '127.0.0.1', self.port)
        self.app = app
        return app, srv, handler

    @mock.patch("aiohttp_sentry.client.FixedAioHttpTransport.async_send")
    @run_until_complete
    def test_send_error_handler(self, async_send):
        dsn = 'http://public_key:secret_key@host:9000/project'
        yield from self.prepare_app(dsn)
        response = yield from aiohttp.request('GET',
                                              self.url + '/send-error?qs=qs',
                                              loop=self.loop)
        self.assertEqual(response.status, 500)
        self.assertEqual(async_send.call_count, 1)

        encoded_data = async_send.call_args[0][0]
        sentry = aiohttp_sentry.get_sentry(self.app)
        data = sentry.decode(encoded_data)

        self.assertEqual(data['method'], 'GET')
        self.assertEqual(data['cookies'], [])
        self.assertEqual(data['attrs'], [])
        self.assertEqual(data['get'], [['qs', ['qs']]])
        self.assertEqual(data['post'], [])
        self.assertEqual(data['url'], self.url + '/send-error')

    @mock.patch("aiohttp_sentry.client.FixedAioHttpTransport.async_send")
    @run_until_complete
    def test_send_error_with_custom_dict_handler(self, async_send):
        dsn = 'http://public_key:secret_key@host:9000/project'
        yield from self.prepare_app(dsn)
        response = yield from aiohttp.request(
            'GET', self.url + '/an-error-with-custom-dict-data',
            loop=self.loop)

        self.assertEqual(response.status, 500)
        self.assertEqual(async_send.call_count, 1)

        encoded_data = async_send.call_args[0][0]
        sentry = aiohttp_sentry.get_sentry(self.app)
        data = sentry.decode(encoded_data)
        self.assertEqual(data['extra']['extra_data'], "'extra data'")
        self.assertEqual(data['extra']['key'], 10)

    @mock.patch("aiohttp_sentry.client.FixedAioHttpTransport.async_send")
    @run_until_complete
    def test_no_error_handler(self, async_send):
        dsn = 'atiohttp+http://public_key:secret_key@host:9000/project'

        yield from self.prepare_app(dsn)
        response = yield from aiohttp.request('GET',
                                              self.url + '/no-error',
                                              loop=self.loop)
        self.assertEqual(response.status, 200)
        self.assertEqual(async_send.call_count, 0)

    @mock.patch("aiohttp_sentry.client.FixedAioHttpTransport.async_send")
    @run_until_complete
    def test_no_dsn(self, async_send):
        dsn = None
        yield from self.prepare_app(dsn)
        response = yield from aiohttp.request('GET',
                                              self.url + '/send-error',
                                              loop=self.loop)
        self.assertEqual(response.status, 500)
        self.assertEqual(async_send.call_count, 0)

    @mock.patch("aiohttp_sentry.client.FixedAioHttpTransport.async_send")
    @run_until_complete
    def test_bad_request_handler(self, async_send):
        dsn = 'atiohttp+http://public_key:secret_key@host:9000/project'

        yield from self.prepare_app(dsn)
        response = yield from aiohttp.request('GET',
                                              self.url + '/bad-request',
                                              loop=self.loop)
        self.assertEqual(response.status, 400)
        # sentry should not catch 400 or <500 errors
        self.assertEqual(async_send.call_count, 0)
