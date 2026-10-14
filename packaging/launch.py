"""Entry point for the frozen builds (PyInstaller runs this file on both OSes)."""

import sys

if "--lumenspar-engine-worker" in sys.argv:   # damage.ENGINE_FLAG
    from lumenspar.damage_worker import main as worker_main

    raise SystemExit(worker_main())

from lumenspar.ui.app import main

raise SystemExit(main())
