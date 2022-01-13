# pre-load

import os
from .custom_values import advertise_capabilities

__all__ = []

# If you want to prevent this script from running in unittests, add an environment variable ISUNITTEST set to TRUE
if not os.environ.get("ISUNITTEST"):
    advertise_capabilities()
