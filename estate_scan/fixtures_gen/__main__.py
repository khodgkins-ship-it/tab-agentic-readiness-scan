"""Generate the fixtures on disk.

    python -m estate_scan.fixtures_gen [--out tests/fixtures] [profile ...]

With no profiles, generates all three (median, small, hostile).
"""

import argparse
import sys

from estate_scan.fixtures_gen.generate import BUILDERS, write_fixture


def main(argv=None):
    # type: (list) -> int
    p = argparse.ArgumentParser(prog="estate_scan.fixtures_gen")
    p.add_argument("--out", default="tests/fixtures",
                   help="output directory (default: tests/fixtures)")
    p.add_argument("profiles", nargs="*", choices=list(BUILDERS) + [],
                   help="profiles to build; default all")
    args = p.parse_args(argv)
    profiles = args.profiles or list(BUILDERS)
    for profile in profiles:
        estate_path, manifest_path = write_fixture(profile, args.out)
        print("wrote %s" % estate_path)
        print("wrote %s" % manifest_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
