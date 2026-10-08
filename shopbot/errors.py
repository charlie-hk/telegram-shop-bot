"""Domain errors. `code` is an i18n key so the bot can show them in the user's language."""


class ShopError(Exception):
    def __init__(self, code: str, **params):
        super().__init__(code)
        self.code = code
        self.params = params
