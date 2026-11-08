import json
import sys

from report import build_report

if __name__ == "__main__":
    with open(sys.argv[1]) as f:
        print(build_report(json.load(f)))
