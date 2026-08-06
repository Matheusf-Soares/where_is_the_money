"""Permite `python -m financas <comando>` além de `python -m financas.cli`."""

import sys

from financas.cli import main

sys.exit(main())
