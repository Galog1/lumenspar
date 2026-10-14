import sys

if "--lumenspar-engine-worker" in sys.argv:   # damage.ENGINE_FLAG
    from .damage_worker import main as worker_main

    raise SystemExit(worker_main())

from .ui.app import main

raise SystemExit(main())
