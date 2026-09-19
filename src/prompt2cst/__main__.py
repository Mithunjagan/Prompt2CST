from __future__ import annotations

import sys

from .cli import main as cli_main


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--gui":
        from .gui import main as gui_main
        gui_main()
    else:
        sys.exit(cli_main())


if __name__ == "__main__":
    main()
