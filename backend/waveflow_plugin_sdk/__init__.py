"""WaveFlow Python Plugin SDK for Plugin API 1.0 and IPC 1.1."""

from .application import ChannelCatalogProvider, PluginApplication, RadioProvider, TVProvider, VisualMetadataProvider
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
from .models import ChannelCatalog, ChannelCatalogItem, RadioReference, ResolveContext, StreamDescriptor, TVReference, VisualMetadata
from .resources import load_resource_text

SDK_VERSION = "0.1.0"

__all__ = [
    "AuthFailure", "CapabilityClient", "CapabilityResponse", "ChannelCatalog", "ChannelCatalogItem",
    "ChannelCatalogProvider", "InvalidResource", "NotLive", "PluginApplication", "PluginError",
    "RadioProvider", "RadioReference",
    "RateLimited", "ResolveContext", "SDK_VERSION", "StreamDescriptor",
    "TVProvider", "TVReference", "VisualMetadata", "VisualMetadataProvider", "TemporaryFailure", "UpstreamFailure",
    "load_resource_text",
]
