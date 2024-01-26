import json
import logging
from datetime import timedelta

import boto3
from aws_secretsmanager_caching import SecretCache, SecretCacheConfig
from botocore.exceptions import ClientError

# We're not using named loggers anywhere. I threw one here as an example.
# This grabs names based on modules so it's more clear where log messages
# are coming from. In this case, since tests is at the same level of atscale
# it's not super useful. However, this pattern can be used for submodules
# of atscale as the code base grows.
logger = logging.getLogger(__name__)


class SecretsManager:
    """Encapsulates Secrets Manager functions."""

    _instance = None

    def __new__(cls):
        """
        Checkout the singleton pattern explaining this: https://python-patterns.guide/gang-of-four/singleton/
        Seemed like the right thing to do but now can't remember why I made this a class instead of leaving
        a module which would have accomplished the same thing of ensuring only one instance¸
        """
        if cls._instance is None:
            cls._instance = super(SecretsManager, cls).__new__(cls)
            # Put any initialization here.
            cls._instance.client = boto3.client("secretsmanager")
            # Cacheing secrets using the scheme described here:
            # https://docs.aws.amazon.com/secretsmanager/latest/userguide/retrieving-secrets_cache-python.html
            # Setting the config so secrets are refreshed every day, this is in seconds
            ar = {"secret_refresh_interval": timedelta(days=1).total_seconds()}
            cache_config = SecretCacheConfig(**ar)
            cls._instance.cache = SecretCache(config=cache_config, client=cls._instance.client)
        return cls._instance

    def get_secret_names(self):
        """
        Lists secrets for the current account. To optimize caching and reduce calls it would be better not
        to call this and just grab the key directly, but left here as a convenience.

        :return: the secrets
        """
        try:
            return self.client.list_secrets()
        except ClientError:
            #logger.exception("Couldn't list secrets.")
            logger.warning("Couldn't list secrets.")
            raise

    def get_secret_json(
        self,
        key,
    ):
        if not key:
            logger.warning("You should only call this with a key")
            return None
        return json.loads(self.cache.get_secret_string(key))
