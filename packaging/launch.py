"""Entry point for the frozen builds (PyInstaller runs this file on both OSes)."""

from lumenspar.ui.app import main

raise SystemExit(main())
