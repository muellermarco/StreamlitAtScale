import getpass
import cryptocode
import logging
import inspect
from atscale.errors import atscale_errors
from inspect import getfullargspec
from atscale.utils.validation_utils import validate_by_type_hints
from atscale.db.sqlalchemy_connection import SQLAlchemyConnection
from atscale.base.enums import PlatformType
from atscale.utils import validation_utils

logger = logging.getLogger(__name__)


class MSSQL(SQLAlchemyConnection):
    """The child class of SQLConnection whose implementation is meant to handle interactions with MSSQL. Notes that
    a different class is required for interacting with Synapse SQL DW at this point in time.
    For this to work, in addition to dependencies indicated in setup.py, it is necessary to install an ODBC driver.

    For MAC, you can use Brew to install unixodbc via
    brew install unixodbc
    You can then follow Microsoft instructions for the rest of pyodbc here:
    https://www.microsoft.com/en-us/sql-server/developer-get-started/python/mac/?rtc=1
    Specifically for the following:
    brew tap microsoft/mssql-release https://github.com/Microsoft/homebrew-mssql-release
    brew update
    HOMEBREW_NO_ENV_FILTERING=1 ACCEPT_EULA=Y brew install msodbcsql17 mssql-tools
    Common errors are discussed here: https://stackoverflow.com/questions/44527452/cant-open-lib-odbc-driver-13-for-sql-server-sym-linking-issue
    And other places. If you experience driver/connection issues, it is suggested that you first try and connect directly using sqlcmd
    as indicated in the Microsoft instructions posted above. Once you're able to connect, you can inspect run the command odbcinst -j
    to inspect the file: odbcinst.ini which should indicate what string you should use to pass in for the driver parameter to this class.
    At present time, the string is "ODBC Driver 17 for SQL Server"
    """

    platform_type: PlatformType = PlatformType.MSSQL

    def __init__(
        self,
        username: str,
        host: str,
        database: str,
        driver: str,
        schema: str,
        port: int = 1433,
        password: str = None,
        warehouse_id: str = None,
    ):
        """Constructs an instance of an SQLConnection that should work with any database that pyodbc works with.
        Takes arguments necessary to find the database, driver, and schema. If password is not provided,
        it will prompt the user to login.

        Args:
            username (str): the username necessary for login
            host (str): the host of the intended Synapse connection
            database (str): the database of the intended Synapse connection
            driver (str): the driver of the intended Synapse connection
            schema (str): the schema of the intended Synapse connection
            port (int, optional): A port if non-default is configured. Defaults to 1433.
            password (str, optional): the password associated with the username. Defaults to None.
            warehouse_id (str, optional): The AtScale warehouse id to automatically associate the connection with if writing tables. Defaults to None.

        """

        try:
            from sqlalchemy.engine import URL
            from sqlalchemy import create_engine
        except ImportError as e:
            raise atscale_errors.AtScaleExtrasDependencyImportError("mssql", str(e))

        super().__init__(warehouse_id)

        inspection = getfullargspec(self.__init__)
        validate_by_type_hints(inspection=inspection, func_params=locals())

        self._username = username
        self._host = host
        self._database = database
        self._driver = driver
        self._schema = schema
        self._port = port
        if password:
            self._password = cryptocode.encrypt(password, self.platform_type.value)
        else:
            self._password = None

        try:
            validation_connection = self.engine.connect()
            validation_connection.close()
            self.dispose_engine()
        except:
            logger.error("Unable to create database connection, please verify the inputs")
            raise

    @property
    def username(self) -> str:
        return self._username

    @username.setter
    def username(
        self,
        value,
    ):
        # validate the non-null inputs
        if value is None:
            raise ValueError(f"The following required parameters are None: value")
        self._username = value
        self.dispose_engine()

    @property
    def host(self) -> str:
        return self._host

    @host.setter
    def host(
        self,
        value,
    ):
        # validate the non-null inputs
        if value is None:
            raise ValueError(f"The following required parameters are None: value")
        self._host = value
        self.dispose_engine()

    @property
    def database(self) -> str:
        return self._database

    @database.setter
    def database(
        self,
        value,
    ):
        # validate the non-null inputs
        if value is None:
            raise ValueError(f"The following required parameters are None: value")
        self._database = value
        self.dispose_engine()

    @property
    def driver(self) -> str:
        return self._driver

    @database.setter
    def driver(
        self,
        value,
    ):
        # validate the non-null inputs
        if value is None:
            raise ValueError(f"The following required parameters are None: value")
        self._driver = value
        self.dispose_engine()

    @property
    def schema(self) -> str:
        return self._schema

    @schema.setter
    def schema(
        self,
        value,
    ):
        # validate the non-null inputs
        if value is None:
            raise ValueError(f"The following required parameters are None: value")
        self._schema = value
        self.dispose_engine()

    @property
    def port(self) -> str:
        return self._port

    @port.setter
    def port(
        self,
        value,
    ):
        # validate the non-null inputs
        if value is None:
            raise ValueError(f"The following required parameters are None: value")
        self._port = value
        self.dispose_engine()

    @property
    def password(self) -> str:
        raise atscale_errors.UnsupportedOperationException("Passwords cannot be retrieved.")

    @password.setter
    def password(
        self,
        value,
    ):
        # validate the non-null inputs
        if value is None:
            raise ValueError(f"The following required parameters are None: value")
        self._password = cryptocode.encrypt(value, self.platform_type.value)
        self.dispose_engine()

    @property
    def engine(self):
        from sqlalchemy import create_engine

        if self._engine is not None:
            return self._engine
        url = self._get_connection_url()
        # Little customization to deal with an issue when connecting to azure data warehouse;
        # See here for more info: https://docs.sqlalchemy.org/en/14/dialects/mssql.html?highlight=pyodbc#avoiding-transaction-related-exceptions-on-azure-synapse-analytics
        self._engine = create_engine(url).execution_options(
            isolation_level="AUTOCOMMIT", ignore_no_transaction_on_rollback=True
        )
        return self._engine

    def clear_auth(self):
        """Clears any authentication information, like password or token from the connection."""
        self._password = None
        self.dispose_engine()

    def _get_connection_url(self):
        from sqlalchemy.engine import URL

        if not self._password:
            self._password = cryptocode.encrypt(
                getpass.getpass(prompt="Please enter your Synapse password: "),
                self.platform_type.value,
            )
        password = cryptocode.decrypt(self._password, self.platform_type.value)

        # Below is an example of passing through the exact string to pyodbc. I'm using the sqlalchemy URL to pass in autocommit becuase of an azure issue.
        # There may be another way to do that with the pass through approach but not sure, as that has to be set not just on connectino but driver I think,
        # according to docs.
        # connection_string = f'DRIVER={{{self.driver}}};SERVER={self.host};PORT={self.port};DATABASE={self.database};UID={self.username};PWD={password}'
        # connection_url = URL.create("mssql+pyodbc", query={"odbc_connect": connection_string})

        connection_url = URL.create(
            "mssql+pyodbc",
            username=self._username,
            password=password,
            host=self._host,
            database=self._database,
            query={
                "driver": self._driver,
                "autocommit": "True",
            },
        )

        return connection_url

    def _create_table_path(
        self,
        table_name: str,
    ) -> str:
        """generates a full table file path using instance variables.

        Args:
            table_name (str): the table name to append

        Returns:
            str: the queriable location of the table
        """
        return f"{self._column_quote()}{self.database}{self._column_quote()}.{self._column_quote()}{self.schema}{self._column_quote()}.{self._column_quote()}{table_name}{self._column_quote()}"
