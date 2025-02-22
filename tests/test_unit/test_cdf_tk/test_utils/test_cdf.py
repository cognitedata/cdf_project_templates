import pytest
from cognite.client.data_classes import ClientCredentials, OidcCredentials

from cognite_toolkit._cdf_tk.utils.cdf import try_find_error


class TestTryFindError:
    @pytest.mark.parametrize(
        "credentials, expected",
        [
            pytest.param(
                ClientCredentials("${ENVIRONMENT_VAR}", "1234"),
                "The environment variable is not set: ENVIRONMENT_VAR.",
                id="Missing environment variable",
            ),
            pytest.param(
                ClientCredentials("${ENV1}", "${ENV2}"),
                "The environment variables are not set: ENV1 and ENV2.",
                id="Missing environment variable",
            ),
            pytest.param(
                OidcCredentials("my-client-id", "123", ["https://cognite.com"], "not-valid-uri", "my-project"),
                "The tokenUri 'not-valid-uri' is not a valid URI.",
            ),
            pytest.param(None, None, id="empty"),
        ],
    )
    def test_try_find_error(self, credentials: OidcCredentials | ClientCredentials | None, expected: str | None):
        assert try_find_error(credentials) == expected
