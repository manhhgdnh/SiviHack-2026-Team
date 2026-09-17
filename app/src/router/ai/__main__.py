import argparse
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

from .errors import ReviewError
from .service import ProposalService


def main():
    parser = argparse.ArgumentParser(description="Review a Markdown proposal against an RFP")
    parser.add_argument("rfp", type=Path)
    parser.add_argument("proposal", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    load_dotenv()
    try:
        result = ProposalService().review(
            {
                "rfp": args.rfp.read_text(encoding="utf-8"),
                "proposal": args.proposal.read_text(encoding="utf-8"),
            }
        )
        text = result.model_dump_json(by_alias=True, indent=2)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(text + "\n", encoding="utf-8")
        else:
            print(text)
    except (OSError, UnicodeError):
        print(
            json.dumps(
                {
                    "error": {
                        "code": "file_error",
                        "message": "Cannot read/write the requested UTF-8 files.",
                        "retryable": False,
                    }
                }
            ),
            file=sys.stderr,
        )
        return 1
    except ReviewError as exc:
        print(json.dumps(exc.payload()), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
