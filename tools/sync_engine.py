"""Bundle the independent engine into the installable custom component."""
from pathlib import Path
import argparse

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    target = ROOT / "custom_components/pasture_wsc/engine"
    target.mkdir(parents=True, exist_ok=True)
    for source in (ROOT / "pasture_wsc").glob("*.py"):
        output = target / source.name
        if args.check:
            if not output.exists() or output.read_bytes() != source.read_bytes():
                raise SystemExit(f"Engine bundle out of date: {output.name}")
        else:
            output.write_bytes(source.read_bytes())


if __name__ == "__main__":
    main()
