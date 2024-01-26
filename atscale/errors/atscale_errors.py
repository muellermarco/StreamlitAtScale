class AtScaleExtrasDependencyImportError(Exception):
    """Takes an import error and tells the user to install the dependencies for the extras_type
    (ex. No module named 'snowflake-sqlalchemy'. You may need to run pip install 'atscale[snowflake]')
    """

    def __init__(
        self,
        extras_type: str,
        nested_error: str,
    ):
        message = f"{nested_error}\nYou may need to run pip " f"install 'atscale[{extras_type}]'"
        super().__init__(message)


class ValidationError(Exception):
    """This error occurs when a request to the AtScale server was rejected due to being an invalid request.
    This includes but is not limited to: invalid or missing request parameters, and the project JSON being invalid.
    """

    def __init__(
        self,
        message,
    ):
        self.message = message
        super().__init__(message)


class AuthenticationError(Exception):
    """This error occurs when a request to the AtScale server was rejected due to an invalid authentication.
    Often resulting from a bad username/password or an expired token."""

    def __init__(
        self,
        message,
    ):
        self.message = message
        super().__init__(message)


class InsufficientAccessError(Exception):
    """This error occurs when a request is sent to the AtScale server by a user who does not have access to the
    requested resource."""

    def __init__(
        self,
        message,
    ):
        self.message = message
        super().__init__(message)


class InaccessibleAPIError(Exception):
    """This error occurs when a user without API access sends a request to the AtScale API, or one of the request
    parameter id's does not exist."""

    def __init__(
        self,
        message,
    ):
        self.message = message
        super().__init__(message)


class AtScaleServerError(Exception):
    """This error accounts for a slew of server errors, all of which send the response code 500."""

    def __init__(
        self,
        message,
    ):
        self.message = message
        super().__init__(message)


class DisabledDesignCenterError(Exception):
    """This error comes from the response code 503 and almost exclusively occurs when design center api's are not
    enabled."""

    def __init__(
        self,
        message,
    ):
        self.message = message
        super().__init__(message)


class UserError(Exception):
    """This error occurs when the user inputs something that throws an error, specifically something they should
    have known to avoid according to the doc string of that given function/class"""
    def __init__(
        self,
        message,
    ):
        self.message = message
        super().__init__(message)


class DependentMeasureException(Exception):
    """This error occurs when a user tries to delete an object while attempting to perserve
    its children."""
    def __init__(
        self,
        message,
    ):
        self.message = message
        super().__init__(message)


class EDAException(Exception):
    """This error occurs when the EDA module throws an exception, specifically occuring due to SQL 
    ML operations throwing an error."""
    def __init__(
        self,
        message,
    ):
        self.message = message
        super().__init__(message)


class UnsupportedOperationException(Exception):
    """This error occurs when the user tries to perform an unsupported action."""
    def __init__(
        self,
        message,
    ):
        self.message = message
        super().__init__(message)