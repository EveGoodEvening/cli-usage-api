"""Allow python -m cli_usage_api to use the installed command implementation."""

from cli_usage_api.cli import main

raise SystemExit(main())
