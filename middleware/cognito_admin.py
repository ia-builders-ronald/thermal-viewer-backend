"""Disable / enable Cognito users (blocks sign-in and revokes refresh tokens)."""


class CognitoAdmin:
    def __init__(self, client, user_pool_id: str):
        self._client = client
        self._pool = user_pool_id

    def disable(self, username: str) -> None:
        self._client.admin_disable_user(UserPoolId=self._pool, Username=username)
        self._client.admin_user_global_sign_out(UserPoolId=self._pool, Username=username)

    def enable(self, username: str) -> None:
        self._client.admin_enable_user(UserPoolId=self._pool, Username=username)
