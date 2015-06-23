import asyncio
import aiohttp_sentry
from aiohttp import web


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
def bad_request(request):
    raise web.HTTPBadRequest()


@asyncio.coroutine
def init(loop):
    app = web.Application(loop=loop, middlewares=[aiohttp_sentry.middleware])

    dsn = 'atiohttp+http://public_key:secret_key@host:9000/project'
    aiohttp_sentry.setup(app, dsn)

    app.router.add_route('GET', '/send-error', send_error)
    app.router.add_route('GET', '/an-error-with-custom-dict-data',
                         send_error_custom_dict)

    handler = app.make_handler()
    srv = yield from loop.create_server(handler, '127.0.0.1', 9000)
    return srv, handler


loop = asyncio.get_event_loop()
srv, handler = loop.run_until_complete(init(loop))
try:
    loop.run_forever()
except KeyboardInterrupt:
    loop.run_until_complete(handler.finish_connections())
