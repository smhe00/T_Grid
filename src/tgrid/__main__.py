"""Allow ``python -m tgrid`` to run the offline CLI."""

import sys

from tgrid.main import main

if __name__ == "__main__":
    sys.exit(main())
