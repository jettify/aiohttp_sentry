import asyncio
import time
import aiohttp
from raven.transport.aiohttp import AioHttpTransport

from functools import partial

from raven import Client
import raven
from raven.exceptions import APIError, RateLimited
from raven.utils import get_auth_header


class FixedAioHttpTransport(AioHttpTransport):
    def async_send(self, data, headers, success_cb, failure_cb):
        @asyncio.coroutine
        def f():
            try:
                resp = yield from asyncio.wait_for(
                    aiohttp.request('POST',
                                    self._url, data=data,
                                    headers=headers,
                                    connector=self._connector,
                                    loop=self._loop),
                    self.timeout,
                    loop=self._loop)
                yield from resp.release()
                code = resp.status
                if code != 200:
                    msg = resp.headers.get('x-sentry-error')
                    if code == 429:
                        try:
                            retry_after = int(resp.headers.get('retry-after'))
                        except (ValueError, TypeError):
                            retry_after = 0
                        failure_cb(RateLimited(msg, retry_after))
                    else:
                        failure_cb(APIError(msg, code))
                else:
                    success_cb()
            except Exception as exc:
                failure_cb(exc)

        return asyncio.async(f(), loop=self._loop)


class AioClient(Client):
    def __init__(self, dsn=None, raise_send_errors=False,
                 transport=FixedAioHttpTransport, loop=None, **options):
        self._loop = loop or asyncio.get_event_loop()
        transport_with_loop = partial(transport, loop=self._loop)

        super().__init__(dsn=dsn, raise_send_errors=raise_send_errors,
                         transport=transport_with_loop, **options)

    def send_remote(self, url, data, headers=None):
        # If the client is configured to raise errors on sending,
        # the implication is that the backoff and retry strategies
        # will be handled by the calling application
        if headers is None:
            headers = {}

        if not self.raise_send_errors and not self.state.should_try():
            data = self.decode(data)
            self._log_failed_submission(data)
            return

        self.logger.debug('Sending message of length %d to %s', len(data), url)

        def failed_send(e):
            self._failed_send(e, url, self.decode(data))

        transport = self.remote.get_transport()
        fut = transport.async_send(data, headers, self._successful_send,
                                   failed_send)
        f = partial(self._send_callback, failed_send_clb=failed_send)
        fut.add_done_callback(f)
        return fut

    def _send_callback(self, future, *, failed_send_clb):
        if not future.exception:
            self._successful_send()
        else:
            failed_send_clb(future.exception)

    def send_encoded(self, message, auth_header=None, **kwargs):
        """
        Given an already serialized message, signs the message and passes the
        payload off to ``send_remote`` for each server specified in the servers
        configuration.
        """
        client_string = 'raven-python/%s' % (raven.VERSION,)

        if not auth_header:
            timestamp = time.time()
            auth_header = get_auth_header(
                protocol=self.protocol_version,
                timestamp=timestamp,
                client=client_string,
                api_key=self.remote.public_key,
                api_secret=self.remote.secret_key,
            )

        headers = {
            'User-Agent': client_string,
            'X-Sentry-Auth': auth_header,
            'Content-Type': 'application/octet-stream',
        }

        return self.send_remote(
            url=self.remote.store_endpoint,
            data=message,
            headers=headers,
            **kwargs
        )

    def capture(self, event_type, data=None, date=None, time_spent=None,
                extra=None, stack=None, tags=None, **kwargs):

        if not self.is_enabled():
            return

        data = self.build_msg(
            event_type, data, date, time_spent, extra, stack, tags=tags,
            **kwargs)

        return self.send(**data)

    def capture_exceptions(self, function_or_exceptions, **kwargs):
        raise NotImplementedError('Will be implemented with pep492')
