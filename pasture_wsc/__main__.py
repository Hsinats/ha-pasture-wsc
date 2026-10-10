"""Single-day CLI with explicit experimental/scenario metadata."""
import argparse
from dataclasses import asdict
import json

from .model import SoilIndex, MoistureMode, calculate


def main():
    parser = argparse.ArgumentParser(description="Experimental modeled WSC (% dry matter); no grazing safety decision")
    parser.add_argument("--daylength", type=float, required=True)
    parser.add_argument("--temperature", type=float)
    parser.add_argument("--radiation", type=float)
    parser.add_argument("--spechr", type=float, help="Cumulative INCLUDING this day, supplied independently")
    parser.add_argument("--wi", type=float)
    parser.add_argument("--soil-semantics")
    parser.add_argument("--compatible-index", action="store_true", help="Explicit caller attestation; no calibration implied")
    parser.add_argument("--scenario", action="store_true")
    parser.add_argument("--moisture-mode", choices=list(MoistureMode))
    args = parser.parse_args()
    if args.wi is not None and not args.soil_semantics:
        parser.error("--wi requires --soil-semantics")
    try:
        soil = None if args.wi is None else SoilIndex(args.wi, args.soil_semantics, args.compatible_index, args.scenario)
        result = calculate(args.daylength, args.temperature, args.radiation, args.spechr,
                           soil, args.moisture_mode, scenario=args.scenario)
    except ValueError as error:
        parser.error(str(error))
    print(json.dumps(asdict(result), indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
