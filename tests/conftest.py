# Copyright (c) Spectro Cloud
# SPDX-License-Identifier: Apache-2.0

from pathlib import Path
import sys


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))
