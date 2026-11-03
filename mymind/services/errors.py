class ServiceError(Exception):
    """An external provider failed or is unavailable. `user_message` is safe to show."""
    def __init__(self, user_message, detail=""):
        super().__init__(detail or user_message)
        self.user_message = user_message
