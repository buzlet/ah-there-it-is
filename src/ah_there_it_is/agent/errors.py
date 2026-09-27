"""Agent/tool boundary errors."""


class AgentError(RuntimeError):
    pass


class ToolExecutionError(AgentError):
    pass


class ToolPreconditionError(ToolExecutionError):
    pass


class ToolClarificationRequiredError(ToolPreconditionError):
    """A safe write needs a user clarification before it can be attempted."""


class AgentLoopLimitError(AgentError):
    pass


class AgentTurnFailedError(AgentError):
    """A tool error or empty post-mutation response invalidated the turn."""


class ProviderRequestError(AgentError):
    """A model provider could not complete the HTTP request."""


class ProviderProtocolError(AgentError):
    """A model provider returned a response that violates its contract."""
