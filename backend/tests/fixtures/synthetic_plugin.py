#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys


def read_frame():
    headers = {}
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            return None
        if line == b"\r\n":
            break
        name, value = line.decode("ascii").rstrip("\r\n").split(": ", 1)
        headers[name.lower()] = value
    return json.loads(sys.stdin.buffer.read(int(headers["content-length"])).decode("utf-8"))


def write_frame(payload):
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    sys.stdout.buffer.write(
        f"Content-Length: {len(body)}\r\nContent-Type: application/json; charset=utf-8\r\n\r\n".encode("ascii") + body
    )
    sys.stdout.buffer.flush()


def response(request, result=None, *, request_id=None, error=None):
    return {
        "protocol_version": "1.0",
        "request_id": request_id or request["request_id"],
        "status": "error" if error else "ok",
        "result": None if error else result,
        "error": error,
        "diagnostics": {},
    }


def descriptor(transport="hls"):
    suffix = {"hls": "m3u8", "dash": "mpd", "http_flv": "flv", "mpegts": "ts",
              "rtsp": "stream", "audio_http": "mp3", "probe_only": ""}[transport]
    url = "" if transport == "probe_only" else (
        f"rtsp://example.invalid/{suffix}" if transport == "rtsp" else f"https://example.invalid/live.{suffix}"
    )
    return {
        "descriptor_version": "1.0", "transport": transport, "url": url,
        "headers": {"Referer": "https://example.invalid/"}, "credential_refs": [],
        "ttl_seconds": 120, "expires_at": None, "volatile_url": True,
        "requires_proxy": False, "warnings": [],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", default="normal")
    parser.add_argument("--identity", default="org.waveflow/synthetic")
    parser.add_argument("--version", default="1.0.0")
    parser.add_argument("--scheme", default="synthetic")
    parser.add_argument("--schemes", default="")
    parser.add_argument("--permissions", default="")
    parser.add_argument("--tv-only", action="store_true")
    args = parser.parse_args()
    schemes = [value for value in args.schemes.split(",") if value] or [args.scheme]
    deferred = {}
    while True:
        request = read_frame()
        if request is None:
            return
        method = request["method"]
        if method == "runtime.hello":
            permissions = [v for v in args.permissions.split(",") if v]
            if args.mode == "hello_escalation":
                permissions.append("subprocess")
            provider_contracts = [
                {"contract": "tv_provider", "contract_version": "1.0", "features": ["resolve_stream"]},
            ]
            capabilities = ["tv.resolve_stream"]
            if not args.tv_only:
                provider_contracts.append(
                    {"contract": "radio_provider", "contract_version": "1.0", "features": ["catalog", "resolve_stream"]}
                )
                capabilities.extend(["radio.catalog", "radio.resolve_stream"])
            result = {
                "protocol_version": "1.0", "plugin": args.identity, "version": args.version,
                "provider_contracts": provider_contracts,
                "owned_schemes": [{"scheme": scheme, "contract": "tv_provider"} for scheme in schemes],
                "capabilities": capabilities,
                "permissions": permissions,
            }
            write_frame(response(request, result))
        elif method == "runtime.health":
            write_frame(response(request, {"healthy": args.mode != "health_fail"}))
        elif method == "runtime.shutdown":
            write_frame(response(request, {"accepted": True}))
            return
        elif method == "runtime.cancel":
            target = request["payload"].get("request_id")
            if target in deferred:
                write_frame(response(deferred.pop(target), descriptor()))
            # Cancellation is a notification: no response is required by the fixture.
        elif method == "tv.resolve_stream":
            if args.mode == "crash":
                os._exit(23)
            if args.mode == "hang":
                deferred[request["request_id"]] = request
                continue
            if args.mode == "malformed_frame":
                sys.stdout.buffer.write(b"garbage\r\n\r\n")
                sys.stdout.buffer.flush()
                continue
            result = descriptor(request["payload"].get("transport", "hls"))
            if args.mode == "invalid_descriptor":
                result["headers"] = {"Authorization": "redacted-fixture"}
            if args.mode == "wrong_request_id":
                write_frame(response(request, result, request_id="unknown-request"))
                continue
            write_frame(response(request, result))
            if args.mode == "duplicate_response":
                write_frame(response(request, result))
        elif method == "radio.catalog":
            write_frame(response(request, {"stations": [
                {"station_ref": {"provider_key": "synthetic", "provider_station_id": "one"}, "name": "Same Name"},
                {"station_ref": {"provider_key": "synthetic", "provider_station_id": "two"}, "name": "Same Name"},
            ], "next_cursor": None}))
        elif method == "radio.resolve_stream":
            write_frame(response(request, descriptor("audio_http")))
        else:
            write_frame(response(request, error={"code": "RESOURCE_NOT_FOUND", "message": "Unknown method",
                                                    "retryable": False, "category": "request", "details": {}}))


if __name__ == "__main__":
    main()
