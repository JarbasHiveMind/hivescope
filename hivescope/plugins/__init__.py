from hivescope.plugins.agent import TestAgentProtocol
from hivescope.plugins.binary import TestBinaryProtocol
from hivescope.plugins.network import TestNetworkProtocol

# Optional — requires ovoscope + ovos-core
try:
    from hivescope.plugins.ovoscope_agent import (
        OvoscopeAgentProtocol,
        _HarnessCaptureSession,
    )
except ImportError:
    pass
