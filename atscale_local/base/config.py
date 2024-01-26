import json
import logging
from configparser import ConfigParser
from pathlib import Path
from pkg_resources import DistributionNotFound, get_distribution
from atscale.errors import atscale_errors


# Generally would like constants in config files, but these are actually to
# support loading config files and generally should not change, so are "real" constants.
ROOT_DIR = Path(__file__).parent.parent.parent
DEFAULT_CONFIG_PATH = ROOT_DIR / "config.ini"
LOCAL_CONFIG_DIR = Path.home() / ".atscale"
LOCAL_CONFIG_PATH = LOCAL_CONFIG_DIR / "config"
LOCAL_CRED_PATH = LOCAL_CONFIG_DIR / "credentials"

DEFAULT_DESIGN_CENTER_PORT = "10500"

logger = logging.getLogger(__name__)


class Config:
    _instance = None

    def __new__(cls):
        """
        Singleton for managing config values. Reads in values from multiple
        files. If keys are repeated in files, then the most recently read values overwrite prior
        values. Values read in last take precedent over files read in first. The order of reading is as follows:
        - default config.ini file at project root
        - local config file in /[user_home]/.atscale/config
        - local credentials file in /[user_home]/.atscale/credentials
        - local .env file

        This class also has a SecretsManager object which will leverage any local .aws credentials to attempt to access secrets if
        they cannot be found in the local credentials file.

        Checkout a description of the singleton pattern explaining use of this __new__ method here: https://python-patterns.guide/gang-of-four/singleton/
        It means only one instance of this class is created in the same python execution no matter how many times the constructor is called.
        """
        if cls._instance is None:
            cls._instance = super(Config, cls).__new__(cls)
            # Put any initialization here, using 'cls._instance' instead of self
            cls._instance._config_parser = ConfigParser()
            # order matters here, as values for the same keys in later files will overwrite ealier values found
            config_files = [DEFAULT_CONFIG_PATH, LOCAL_CONFIG_PATH, LOCAL_CRED_PATH]
            # can inspect found to see which files were found
            cls._instance._config_parser.read(config_files)

        return cls._instance

    @property
    def version(self):
        version = None
        try:
            version = get_distribution("atscale").version
        except DistributionNotFound as err:
            version = "atscale not installed"
        return version

    @classmethod
    def destroy(self):
        self._instance = None

    @property
    def config_parser(self) -> ConfigParser:
        return self._config_parser

    @config_parser.setter
    def config_parser(
        self,
        value,
    ):
        raise atscale_errors.UnsupportedOperationException(
            "Value of config_parser is final; it cannot be altered."
        )

    def read(
        self,
        config_file: str,
    ):
        """Reads in a config file and adds it to configuration properties to be read and used by other classes and methods.
        Any values in config_file will overwrite previous values for the same sections/keys.

        Args:
            config_file (str): an absolute path to a .ini formatted config file to read. See https://docs.python.org/3/library/configparser.html#supported-ini-file-structure
        """
        if config_file is None:
            return
        self._config_parser.read(config_file)

    def get(
        self,
        key: str,
        section: str = "DEFAULT",
        default_value: str = None,
    ) -> str:
        """Gets the value for a property. Note that this method switches the order of section and key parameters from the order in ConfigParser.get() as a convenience to pass in only a key and use default values.

        Args:
            key (str): the key for the configuration property
            section (str, optional): The section specified in any config files where the key is. Defaults to "DEFAULT". Read more on specifying sections here: https://docs.python.org/3/library/configparser.html
            default_value (str, optional): The default value to return if the key is not found. Defaults to None.

        Returns:
            str: the value for the key provided if any is found
        """
        # could extend this to parse string return to non-string values - ConfigParser has getBoolean and similar methods
        if not key:
            logger.warning("you should only call this with a key")
            return None

        # Note that has_section(section) ignores DEFAULT section so we have to add the 'or' clause.
        # If the named section exists or the section is the default section
        if (
            self._config_parser.has_section(section)
            or section == self._config_parser.default_section
        ):
            return self._config_parser.get(section, key, fallback=default_value)
        else:
            logger.warning(f"No section {section} exists.")
            return default_value

    def _get_secret_json(
        self,
        key,
        section="DEFAULT",
        default_value=None,
    ):
        """Retrieves credentials similar to how they are stored in AWS secrets manager from
        a local credential file at /[user_home]/.atscale/credentials. You can define sections
        in this local file, provide that section as a parametere to this method, and this method
        will look for the given key in that section. If the key is not found, this method will
        attempt to attach to a SecretsManager account using any local AWS credentials and look
        for the key. In that case, the section parameter is ignored.

        Args:
            key (str): the key for the secret
            section (str, optional): any section to search within. Defaults to "DEFAULT".
            default_value (str, optional): the default value to return if no value is found for the key. Defaults to None.

        Returns:
            str: None or the value. We'll attempt to load it into json if possible.
        """
        from atscale.base.secrets_manager import SecretsManager

        sm = SecretsManager()

        if not key:
            logger.warning("you should only call this with a key")
            return None
        val = self.get(key, section, default_value)
        if val:
            try:
                return json.loads(val)
            except Exception:
                # then we couldn't parse to json so just return whatever it is
                return val
        else:  # else we couldn't find key in local files so ask SecretsManager
            return sm.get_secret_json(key)
