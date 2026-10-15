"""CLI: python -m dashboard.snapshot --label base_v1 [--note "..."] [--force]"""
import argparse
import sys

from dashboard.data import versions


def main(argv=None):
    ap = argparse.ArgumentParser(description="Snapshot current GAMS results into runs/<label>/")
    ap.add_argument("--label", required=True)
    ap.add_argument("--note", default="")
    ap.add_argument("--force", action="store_true", help="overwrite an existing label")
    a = ap.parse_args(argv)
    try:
        dest = versions.snapshot(a.label, a.note, a.force)
    except (ValueError, FileExistsError, FileNotFoundError) as e:
        print("Error:", e)
        return 1
    print("Saved snapshot to", dest)
    return 0


if __name__ == "__main__":
    sys.exit(main())
