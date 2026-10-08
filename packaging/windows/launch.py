"""Entry point for the frozen Windows build (PyInstaller runs this file)."""

from lumenspar.ui.app import main

raise SystemExit(main())
