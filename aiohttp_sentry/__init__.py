import asyncio
import sys
from pprint import saferepr

from aiohttp import web
from raven import Client


__version__ = '0.0.1'
__all__ = ['setup', 'get_sentry', 'middleware', 'APP_KEY']

APP_KEY = 'aiohttp_sentry_client'


def setup(app, app_key=APP_KEY, dsn='', tags=None, processors=None,
          exclude_paths=None):
    if dsn and not dsn.startswith('aiohttp'):
        dsn = 'aiohttp+' + dsn
    context = {'sys.argv': sys.argv[:]}
    client = Client(dsn, exclude_paths=exclude_paths,
                    processors=processors, tags=tags, context=context)
    app[app_key] = client
    return client


def get_sentry(app, *, app_key=APP_KEY):
    return app.get(app_key)


@asyncio.coroutine
def request_parameters(request):
    data = {}
    if request.method in ('POST', 'PUT', 'PATCH'):
        data = yield from request.post()

    data.update({
        'url': "http://{}{}".format(request.host, request.path),
        'method': request.method,
        'get': [(k, request.GET.getall(k)) for k in request.GET],
        'post': [(k, saferepr(v)) for k, v in request.POST.items()],
        'cookies': [(k, request.cookies.get(k)) for k in request.cookies],
        'attrs': [(k, saferepr(v)) for k, v in request.items()],
        'headers': {k.title(): str(v) for k, v in request.headers.items()},
    })
    return data


@asyncio.coroutine
def middleware(app, handler):

    @asyncio.coroutine
    def sentry_middleware(request):
        try:
            response = yield from handler(request)
            return response

        except (web.HTTPSuccessful, web.HTTPRedirection,
                web.HTTPClientError) as e:
            raise e

        except Exception as exc:
            sentry = get_sentry(app)
            if sentry.dsn:
                exc_info = sys.exc_info()
                data = yield from request_parameters(request)
                sentry.captureException(exc_info, data=data)
            raise exc

    return sentry_middleware
