class DataError(Exception):
    """Safe, classified error; never include credentials or raw HTTP errors."""


class ValidationError(DataError):
    pass


class PermissionDenied(DataError):
    pass


class IntegrityError(DataError):
    pass


class ProviderError(DataError):
    retryable = False


class TransientProviderError(ProviderError):
    retryable = True

    def __init__(self, message="temporary provider failure", retry_after=0.0):
        super().__init__(message)
        self.retry_after = max(0.0, retry_after)


class ProviderAuthError(ProviderError):
    pass


class ProviderSchemaError(ProviderError):
    pass


class ProviderUnavailable(ProviderError):
    pass
