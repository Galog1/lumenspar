"""Child process that runs the damage engine (Qt's QJSEngine + go_engine.js).

Why it exists: PySide6 does not release Python's GIL while a QJSEngine call
runs, so an engine call on a worker thread (about 1.4 s) still blocks every
Python property read QML makes on the GUI thread, and the UI froze after each
change. A child process has its own interpreter and its own GIL.

Protocol (UTF-8 text, one JSON object per line):
  stdin:  {"id": int, "fn": str, "payload": object}
  stdout: {"id": int, "ok": true, "result": ...}
       or {"id": int, "ok": false, "error": "message"}
The process exits with 0 at end of input. Started by damage.Engine with
damage.ENGINE_FLAG.
"""

from __future__ import annotations

import json
import sys


def main() -> int:
    from PySide6.QtCore import QCoreApplication
    from PySide6.QtQml import QJSEngine

    from . import damage

    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    app = QCoreApplication.instance() or QCoreApplication([sys.argv[0]])
    engine = QJSEngine()
    load_error = None
    try:
        res = engine.evaluate(damage.load_source(), str(damage.ENGINE_PATH))
        if res.isError():
            load_error = res.toString()
        else:
            engine._go_loaded = True
    except Exception as exc:
        load_error = str(exc) or type(exc).__name__

    def reply(obj: dict) -> None:
        sys.stdout.write(json.dumps(obj) + "\n")
        sys.stdout.flush()

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        req_id = None
        try:
            req = json.loads(line)
            req_id = req["id"]
            if load_error is not None:
                raise RuntimeError(f"engine failed to load: {load_error}")
            result = damage.run_sync(req["fn"], req.get("payload"), engine)
            reply({"id": req_id, "ok": True, "result": result})
        except Exception as exc:
            reply({"id": req_id, "ok": False, "error": str(exc) or type(exc).__name__})
    del app
    return 0
