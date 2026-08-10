"""WaveFlow Python Plugin SDK for Plugin API 1.0 and IPC 1.1."""

from .application import PluginApplication, RadioProvider, TVProvider
from .capabilities import CapabilityClient, CapabilityResponse
from .errors import (
    AuthFailure,
    InvalidResource,
    NotLive,
    PluginError,
    RateLimited,
    TemporaryFailure,
    UpstreamFailure,
)
from .models import RadioReference, ResolveContext, StreamDescriptor, TVReference

SDK_VERSION = "0.1.0"

__all__ = [
    "AuthFailure", "CapabilityClient", "CapabilityResponse", "InvalidResource",
    "NotLive", "PluginApplication", "PluginError", "RadioProvider", "RadioReference",
    "RateLimited", "ResolveContext", "SDK_VERSION", "StreamDescriptor",
    "TVProvider", "TVReference", "TemporaryFailure", "UpstreamFailure",
]
