"""Fail closed unless all production security configuration gates validate."""

from __future__ import annotations

import os
import sys

from pulseiq.production_config import ProductionConfigurationError, load_production_security_config


def main() -> int:
    try:
        load_production_security_config(os.environ)
    except ProductionConfigurationError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print("Production security configuration passed structural validation.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
