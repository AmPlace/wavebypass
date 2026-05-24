import argparse
import os
import uvicorn


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18765)
    parser.add_argument("--data-dir", default="")
    args = parser.parse_args()

    if args.data_dir:
        os.makedirs(args.data_dir, exist_ok=True)
        os.environ.setdefault(
            "WAVEBYPASS_DB_PATH",
            os.path.join(args.data_dir, "wavebypass.db"),
        )
        os.environ.setdefault(
            "RTSP_HLS_ROOT",
            os.path.join(args.data_dir, "rtsp_hls"),
        )

    from main import app

    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
