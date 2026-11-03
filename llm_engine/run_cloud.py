"""Cloud entry point: run the SAME queue pipeline against OpenCode Go.

    python -m llm_engine.run_cloud --once      # cloud (deepseek-v4.1-flash)
    python -m llm_engine --once                # local (Ollama) — unchanged

No existing file is modified: this entry rebinds the LLM call sites inside
llm_engine.synthesis / llm_engine.security from the local Ollama client to
llm_engine.cloud_client (same signatures). Prompts, dossier math, finding
validation, reporting and the DB stay the single shared copy.
"""
import argparse
import sys

from llm_engine import cloud_client
from llm_engine import security as security_mod
from llm_engine import service
from llm_engine import synthesis as synthesis_mod


def use_cloud() -> None:
    """Swap the transport the workers resolved at import time."""
    synthesis_mod.generate = cloud_client.generate
    synthesis_mod.generate_json = cloud_client.generate_json
    security_mod.generate_json = cloud_client.generate_json


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="llm_engine.run_cloud",
        description="Analyze the queue with OpenCode Go "
                    f"(model {cloud_client.CLOUD_MODEL}); "
                    "needs OPENCODE_GO_API_KEY in .env")
    parser.add_argument("--once", action="store_true",
                        help="drain everything PROCESSED, then exit")
    args = parser.parse_args(argv)
    use_cloud()
    print(f"cloud model: {cloud_client.CLOUD_MODEL}")
    if args.once:
        service.run_once()
    else:
        service.run_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
