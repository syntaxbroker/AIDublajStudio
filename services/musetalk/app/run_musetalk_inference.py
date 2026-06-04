from __future__ import annotations

import runpy
import os
import sys

import torch


def main() -> None:
    # MMEngine versions used by MuseTalk register transformers.Adafactor into
    # torch.optim; PyTorch 2.7 already ships that name, so remove it for this
    # child process before importing mmpose.
    if hasattr(torch.optim, "Adafactor"):
        delattr(torch.optim, "Adafactor")
    original_torch_load = torch.load

    def torch_load_with_legacy_default(*args, **kwargs):
        kwargs.setdefault("weights_only", False)
        return original_torch_load(*args, **kwargs)

    torch.load = torch_load_with_legacy_default
    sys.path.insert(0, os.getcwd())
    sys.argv = ["scripts.inference", *sys.argv[1:]]
    runpy.run_module("scripts.inference", run_name="__main__")


if __name__ == "__main__":
    main()
