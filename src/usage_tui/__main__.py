"""Allow python -m usage_tui to use the installed command implementation."""

from usage_tui.cli import main

raise SystemExit(main())
