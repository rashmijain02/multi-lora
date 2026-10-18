from __future__ import annotations

import argparse
import sys
from importlib import import_module
from importlib.metadata import version


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify the local workshop training environment.")
    parser.add_argument("--device", choices=("cpu", "cuda"), required=True)
    args = parser.parse_args()
    if not (3, 11) <= sys.version_info[:2] < (3, 14):
        raise RuntimeError("Python 3.11-3.13 is required.")
    import torch

    # Importing the actual modules catches binary/runtime problems, not only missing metadata.
    for module in ("accelerate", "email_workshop", "peft", "trackio", "transformers"):
        import_module(module)
    for package, expected in {
        "torch": "2.10.0",
        "transformers": "4.57.6",
        "peft": "0.18.1",
        "accelerate": "1.12.0",
        "trackio": "0.7.0",
    }.items():
        actual = version(package)
        if actual.split("+")[0] != expected:
            raise RuntimeError(f"{package}: expected {expected}, found {actual}. Rerun setup.")
        print(f"{package}: {actual}")
    if args.device == "cuda":
        if torch.version.cuda != "12.8" or not torch.cuda.is_available():
            raise RuntimeError("CUDA 12.8 PyTorch or GPU access is unavailable. Check wheel and driver.")
        print(f"GPU: {torch.cuda.get_device_name(0)}")
        print(f"BF16: {torch.cuda.is_bf16_supported()}")
    elif torch.version.cuda is not None:
        raise RuntimeError("CPU setup expected a CPU-only wheel. Rerun setup with the intended device.")
    result = torch.ones(1, device=args.device).sum().item()
    if result != 1:
        raise RuntimeError("Tensor execution verification failed.")
    print(f"PASS: local {args.device} environment imports and executes tensors.")


if __name__ == "__main__":
    main()
