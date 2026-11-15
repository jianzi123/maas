"""Assemble one committed repository snapshot; never fetch or overlay old branches."""
import argparse
import json
from unified_sources import ROOT, assemble_repository


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    parser.add_argument('--ref', default='HEAD', help='One local repository revision; defaults to HEAD')
    args = parser.parse_args()
    print(json.dumps(assemble_repository(ROOT, args.output, args.ref)))


if __name__ == '__main__':
    main()
