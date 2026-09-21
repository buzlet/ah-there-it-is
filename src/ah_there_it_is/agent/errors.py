"""Agent/tool boundary errors."""


class AgentError(RuntimeError):
    pass


class ToolExecutionError(AgentError):
    pass


class ToolPreconditionError(ToolExecutionError):
    pass


class AgentLoopLimitError(AgentError):
    pass


class ProviderRequestError(AgentError):
    """A model provider could not complete the HTTP request."""


class ProviderProtocolError(AgentError):
    """A model provider returned a response that violates its contract."""
