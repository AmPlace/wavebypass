import asyncio
import unittest
from unittest import mock



def _main_module():
    import main

    return main


class FakeRequest:
    def __init__(self, disconnected_after=10_000):
        self.calls = 0
        self.disconnected_after = disconnected_after

    async def is_disconnected(self):
        self.calls += 1
        return self.calls > self.disconnected_after


class FakeUpstreamResponse:
    def __init__(self, chunks):
        self.chunks = list(chunks)
        self.headers = {}
        self.chunk_size_seen = object()
        self.raw_calls = 0
        self.closed = False
        self.started = asyncio.Event()

    def raise_for_status(self):
        return None

    async def aiter_raw(self, chunk_size=None):
        self.raw_calls += 1
        self.chunk_size_seen = chunk_size
        self.started.set()
        for chunk in self.chunks:
            yield chunk

    async def aclose(self):
        self.closed = True


class GatedUpstreamResponse(FakeUpstreamResponse):
    def __init__(self, first_chunk, remaining_chunks, release_event):
        super().__init__([first_chunk, *remaining_chunks])
        self.first_chunk = first_chunk
        self.remaining_chunks = list(remaining_chunks)
        self.release_event = release_event
        self.first_chunk_yielded = asyncio.Event()

    async def aiter_raw(self, chunk_size=None):
        self.raw_calls += 1
        self.chunk_size_seen = chunk_size
        self.started.set()
        self.first_chunk_yielded.set()
        yield self.first_chunk
        await self.release_event.wait()
        for chunk in self.remaining_chunks:
            yield chunk


class FakeAsyncClient:
    instances = []

    def __init__(self, *args, response=None, **kwargs):
        self.response = response if response is not None else FakeUpstreamResponse([])
        self.closed = False
        self.requests = []
        FakeAsyncClient.instances.append(self)

    def build_request(self, method, url, headers=None):
        request = {"method": method, "url": url, "headers": headers or {}}
        self.requests.append(request)
        return request

    async def send(self, request, stream=False):
        self.stream = stream
        return self.response

    async def aclose(self):
        self.closed = True


async def _make_stream_response(upstream, stream_type="http_flv", request=None):
    # The production stream proxy reconnects live streams after EOF. Unit tests use
    # finite fake streams, so the fake client disconnects after the current fake
    # upstream has been fully consumed and the loop checks for disconnection.
    request = request or FakeRequest(disconnected_after=len(getattr(upstream, "chunks", [])) + 1)

    main_mod = _main_module()

    def client_factory(*args, **kwargs):
        return FakeAsyncClient(*args, response=upstream, **kwargs)

    async def fake_stream(client, method, url, *, headers=None, **_kwargs):
        request = client.build_request(method, url, headers=headers)
        return await client.send(request, stream=True)

    with mock.patch.object(main_mod.httpx, "AsyncClient", client_factory):
        with mock.patch.object(main_mod, "stream_with_safe_redirects", new=fake_stream):
            response = await main_mod.serve_iptv_proxy_stream_response(
                request=request,
                upstream_url="https://stream.example.test/live.flv",
                upstream_headers={"User-Agent": "UA"},
                stream_type=stream_type,
            )
    return response


async def _consume_response(response):
    body = []
    async for chunk in response.body_iterator:
        body.append(chunk)
    return body


class IptvProxyStreamResponseTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        FakeAsyncClient.instances.clear()

    async def test_http_flv_does_not_force_64k_chunking_and_preserves_bytes(self):
        chunks = [b"flv", b"\x00" * 512, b"tail"]
        upstream = FakeUpstreamResponse(chunks)

        response = await _make_stream_response(upstream, stream_type="http_flv")
        out_chunks = await _consume_response(response)

        self.assertIsNone(upstream.chunk_size_seen)
        self.assertEqual(out_chunks, chunks)
        self.assertEqual(b"".join(out_chunks), b"".join(chunks))
        self.assertEqual(upstream.raw_calls, 1)
        self.assertTrue(upstream.closed)
        self.assertEqual(response.media_type, "video/x-flv")
        self.assertTrue(FakeAsyncClient.instances[-1].closed)

    async def test_small_chunk_is_delivered_before_later_chunks_are_available(self):
        release = asyncio.Event()
        first = b"a" * 512
        rest = [b"b" * 1024, b"c"]
        upstream = GatedUpstreamResponse(first, rest, release)

        response = await _make_stream_response(upstream, stream_type="http_flv")
        iterator = response.body_iterator.__aiter__()

        first_task = asyncio.create_task(iterator.__anext__())
        first_out = await asyncio.wait_for(first_task, timeout=0.5)

        self.assertEqual(first_out, first)
        self.assertTrue(upstream.first_chunk_yielded.is_set())
        self.assertFalse(release.is_set())
        self.assertIsNone(upstream.chunk_size_seen)

        second_task = asyncio.create_task(iterator.__anext__())
        await asyncio.sleep(0)
        self.assertFalse(second_task.done())

        release.set()
        remaining = [await asyncio.wait_for(second_task, timeout=0.5)]
        async for chunk in iterator:
            remaining.append(chunk)

        self.assertEqual([first_out, *remaining], [first, *rest])
        self.assertEqual(b"".join([first_out, *remaining]), first + b"".join(rest))
        self.assertTrue(upstream.closed)

    async def test_http_flv_and_mpegts_share_streaming_loop_contract(self):
        for stream_type, media_type in (("http_flv", "video/x-flv"), ("mpegts", "video/MP2T")):
            with self.subTest(stream_type=stream_type):
                chunks = [b"one", b"two", b"three"]
                upstream = FakeUpstreamResponse(chunks)

                response = await _make_stream_response(upstream, stream_type=stream_type)
                out_chunks = await _consume_response(response)

                self.assertIsNone(upstream.chunk_size_seen)
                self.assertEqual(out_chunks, chunks)
                self.assertEqual(b"".join(out_chunks), b"onetwothree")
                self.assertTrue(upstream.closed)
                self.assertEqual(response.media_type, media_type)
                self.assertTrue(FakeAsyncClient.instances[-1].closed)

    async def test_upstream_closes_when_consumer_cancels_iteration(self):
        release = asyncio.Event()
        upstream = GatedUpstreamResponse(b"first", [b"second"], release)
        response = await _make_stream_response(upstream, stream_type="http_flv")
        iterator = response.body_iterator.__aiter__()

        self.assertEqual(await asyncio.wait_for(iterator.__anext__(), timeout=0.5), b"first")
        await iterator.aclose()

        self.assertTrue(upstream.closed)
        self.assertTrue(FakeAsyncClient.instances[-1].closed)

    async def test_client_disconnect_stops_without_reading_forever(self):
        chunks = [b"first", b"second"]
        upstream = FakeUpstreamResponse(chunks)
        request = FakeRequest(disconnected_after=0)

        response = await _make_stream_response(upstream, stream_type="http_flv", request=request)
        out_chunks = await _consume_response(response)

        self.assertEqual(out_chunks, [])
        self.assertEqual(upstream.raw_calls, 0)
        self.assertTrue(upstream.closed)
        self.assertTrue(FakeAsyncClient.instances[-1].closed)

    async def test_upstream_iteration_exception_propagates_and_closes(self):
        class BrokenUpstream(FakeUpstreamResponse):
            async def aiter_raw(self, chunk_size=None):
                self.raw_calls += 1
                self.chunk_size_seen = chunk_size
                yield b"first"
                raise RuntimeError("boom")

        upstream = BrokenUpstream([])
        response = await _make_stream_response(upstream, stream_type="http_flv", request=FakeRequest(disconnected_after=10))
        iterator = response.body_iterator.__aiter__()

        self.assertEqual(await asyncio.wait_for(iterator.__anext__(), timeout=0.5), b"first")
        with self.assertRaises(RuntimeError):
            await iterator.__anext__()
        self.assertTrue(upstream.closed)
        self.assertTrue(FakeAsyncClient.instances[-1].closed)

if __name__ == "__main__":
    unittest.main()
