"""Stable public exception hierarchy for the Amosclaud Agent SDK."""


class AmosclaudSDKError(RuntimeError):
    """Base SDK error."""


class AmosclaudConnectionError(AmosclaudSDKError):
    """The Amosclaud host could not be reached."""


class AmosclaudAuthenticationError(AmosclaudSDKError):
    """The session or API key was rejected."""


class AmosclaudProcessError(AmosclaudSDKError):
    """A governed execution completed unsuccessfully."""


class AmosclaudResponseError(AmosclaudSDKError):
    """The host returned an invalid response contract."""


class ToolPermissionError(AmosclaudSDKError):
    """A local tool invocation was denied by policy or a hook."""
