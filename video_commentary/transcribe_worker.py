from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .config import load_config
from .models import to_plain
from .transcribe import transcribe_audio


def main() -> int:
    parser = argparse.ArgumentParser(description="Run ASR in an isolated process.")
    parser.add_argument("--audio", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--config", default=None)
    args = parser.parse_args()

    output = Path(args.output)
    os.environ["VIDEO_COMMENTARY_TRANSCRIBE_CHECKPOINT"] = str(output)
    cfg = load_config(args.config)

    def progress(ratio: float, message: str) -> None:
        print(json.dumps({"type": "progress", "ratio": ratio, "message": message}, ensure_ascii=False), flush=True)

    segments = transcribe_audio(Path(args.audio), cfg, progress)
    output.write_text(json.dumps([to_plain(item) for item in segments], ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"type": "done", "segments": len(segments)}, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({"type": "error", "message": str(exc)}, ensure_ascii=False), file=sys.stderr, flush=True)
        raise
