"""Interactive API acceptance test. The key is read without echo and never stored."""
from getpass import getpass
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from whitedot.provider import PRESETS, Provider, ProviderError


def main():
    provider = Provider(PRESETS["DeepSeek"], getpass("DeepSeek API key: "))
    provider.validate()
    print("Connection and model validation passed.", flush=True)
    text = "She go to teh library every day."
    issues = provider.check(text)
    print("Validated suggestions:", [(i.original, i.suggestions) for i in issues], flush=True)
    rewritten = provider.rewrite(text)
    print("Rewrite:", rewritten, flush=True)
    if not issues or rewritten == text:
        raise SystemExit("Fixture did not produce an edit.")


if __name__ == "__main__":
    try:
        main()
    except ProviderError as error:
        raise SystemExit(str(error)) from None
