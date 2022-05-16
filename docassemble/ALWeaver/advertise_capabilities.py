# pre-load

import os
from typing import List
from .custom_values import advertise_capabilities

__all__: List[str] = []

# If you want to prevent this script from running in unittests, add an environment variable ISUNITTEST set to TRUE
if not os.environ.get("ISUNITTEST"):
    advertise_capabilities()
