import getpass
import inspect
import cryptocode
import logging
import inspect
import ssl
from typing import Dict, List
import pandas as pd
from inspect import getfullargspec
from atscale.utils.validation_utils import validate_by_type_hints
from atscale.errors import atscale_errors
from atscale.db.sqlalchemy_connection import SQLAlchemyConnection
from atscale.base.enums import (
    PlatformType,
    PysparkTableExistsActionType,
    PandasTableExistsActionType,
)
from atscale.utils import db_utils

logger = logging.getLogger(__name__)


class Snowflake(SQLAlchemyConnection):
    """The child class of SQLConnection whose implementation is meant to handle
    interactions with a Snowflake DB.
    """

    platform_type: PlatformType = PlatformType.SNOWFLAKE

    def __init__(
        self,
        username: str,
        account: str,
        warehouse: str,
        database: str,
        schema: str,
        password: str = None,
        role: str = None,
        authenticator: str = "snowflake",
        private_key: bytes = None,
        token: str = None,
        warehouse_id: str = None,
    ):
        """Constructs an instance of the Snowflake SQLConnection. Takes arguments necessary to find the warehouse, database,
            and schema. If password is not provided, it will prompt the user to login.

        Args:
            username (str): the username necessary for login
            account (str): the account of the intended Snowflake connection
            warehouse (str): the warehouse of the intended Snowflake connection
            database (str): the database of the intended Snowflake connection
            schema (str): the schema of the intended Snowflake connection
            password (str, optional): the password associated with the username. Defaults to None.
            role (str, optional): the role associated with the username. Defaults to None.
            authenticator (str, optional): the authenticator to use when conecting. Defaults to 'snowflake' to use their internal auth.
            private_key (bytes, optional): the DER format private key to authenticate with instead of a password. Defaults to None to use password.
            token (str, optional): the token to use when conecting. Defaults to None.
            warehouse_id (str, optional): The AtScale warehouse id to automatically associate the connection with if writing tables. Defaults to None.
        """

        try:
            from sqlalchemy import create_engine
            from snowflake.connector.pandas_tools import pd_writer
        except ImportError as e:
            raise atscale_errors.AtScaleExtrasDependencyImportError("snowflake", str(e))

        super().__init__(
            warehouse_id
        )  # put super constructor after checking imports since base class doesn't prompt to install
        # since it doesn't know which db is being used

        inspection = getfullargspec(self.__init__)
        validate_by_type_hints(inspection=inspection, func_params=locals())

        self._username = username
        self._account = account
        self._warehouse = warehouse
        self._database = database
        self._schema = schema

        auth_methods = []
        if token:
            self._token = cryptocode.encrypt(token, self.platform_type.value)
            auth_methods.append("token")
        else:
            self._token = None
        if private_key:
            try:
                self._private_key = cryptocode.encrypt(
                    ssl.DER_cert_to_PEM_cert(private_key), self.platform_type.value
                )
            except:
                raise atscale_errors.UserError(
                    "Error parsing private key, make sure it is a valid DER encoded byte string"
                )
            auth_methods.append("private_key")
        else:
            self._private_key = None
        if password:
            self._password = cryptocode.encrypt(password, self.platform_type.value)
            auth_methods.append("password")
        else:
            self._password = None
        if len(auth_methods) > 1:
            logger.warning(
                f"Multiple auth methods passed: {auth_methods} this may result in unintended authorization behavior."
            )
        self._role = role
        self._authenticator = authenticator

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
    def account(self) -> str:
        return self._account

    @account.setter
    def account(
        self,
        value,
    ):
        # validate the non-null inputs
        if value is None:
            raise ValueError(f"The following required parameters are None: value")
        self._account = value
        self.dispose_engine()

    @property
    def warehouse(self) -> str:
        return self._warehouse

    @warehouse.setter
    def warehouse(
        self,
        value,
    ):
        # validate the non-null inputs
        if value is None:
            raise ValueError(f"The following required parameters are None: value")
        self._warehouse = value
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
    def private_key(self) -> str:
        raise atscale_errors.UnsupportedOperationException("Private Key cannot be retrieved.")

    @private_key.setter
    def private_key(
        self,
        value,
    ):
        # validate the non-null inputs
        if value is None:
            raise ValueError(f"The following required parameters are None: value")
        try:
            self._private_key = cryptocode.encrypt(
                ssl.DER_cert_to_PEM_cert(value), self.platform_type.value
            )
        except:
            raise atscale_errors.UserError(
                "Error parsing private key, make sure it is a valid DER encoded byte string"
            )
        self.dispose_engine()

    @property
    def token(self) -> str:
        raise atscale_errors.UnsupportedOperationException("Tokens cannot be retrieved.")

    @password.setter
    def token(
        self,
        value,
    ):
        # validate the non-null inputs
        if value is None:
            raise ValueError(f"The following required parameters are None: value")
        self._token = cryptocode.encrypt(value, self.platform_type.value)
        self.dispose_engine()

    @property
    def role(self) -> str:
        return self._role

    @role.setter
    def role(
        self,
        value,
    ):
        # validate the non-null inputs
        if value is None:
            raise ValueError(f"The following required parameters are None: value")
        self._role = value
        self.dispose_engine()

    @property
    def authenticator(self) -> str:
        return self._authenticator

    @authenticator.setter
    def authenticator(
        self,
        value,
    ):
        if value is None:
            raise ValueError(f"The following required parameters are None: value")
        self._authenticator = value
        self.dispose_engine()

    def clear_auth(self):
        """Clears any authentication information, like password or token from the connection."""
        self._password = None
        self._private_key = None
        self._token = None
        self.dispose_engine()

    @staticmethod
    def _column_quote():
        return '"'

    @staticmethod
    def _lin_reg_str():
        return "::FLOAT AS vals UNION ALL "

    def _warehouse_variance(
        self,
        data_model: "DataModel",
        write_database: str,
        write_schema: str,
        feature: str,
        granularity_levels: List[str],
        if_exists: PandasTableExistsActionType,
        samp: bool,
    ):
        var = db_utils._construct_submit_return_warehouse_stats_one_feat(
            dbconn=self,
            samp_query="SELECT VAR_SAMP({0}) FROM {1}; ",
            pop_query="SELECT VAR_POP({0}) FROM {1}; ",
            data_model=data_model,
            write_database=write_database,
            write_schema=write_schema,
            feature=feature,
            granularity_levels=granularity_levels,
            if_exists=if_exists,
            samp=samp,
        )

        return var

    def _warehouse_std(
        self,
        data_model: "DataModel",
        write_database: str,
        write_schema: str,
        feature: str,
        granularity_levels: List[str],
        if_exists: PandasTableExistsActionType,
        samp: bool,
    ):
        std = db_utils._construct_submit_return_warehouse_stats_one_feat(
            dbconn=self,
            samp_query="SELECT STDDEV_SAMP({0}) FROM {1}; ",
            pop_query="SELECT STDDEV_POP({0}) FROM {1}; ",
            data_model=data_model,
            write_database=write_database,
            write_schema=write_schema,
            feature=feature,
            granularity_levels=granularity_levels,
            if_exists=if_exists,
            samp=samp,
        )

        return std

    def _warehouse_covariance(
        self,
        data_model: "DataModel",
        write_database: str,
        write_schema: str,
        feature_1: str,
        feature_2: str,
        granularity_levels: List[str],
        if_exists: PandasTableExistsActionType,
        samp: bool,
    ):
        cov = db_utils._construct_submit_return_warehouse_stats_two_feat(
            dbconn=self,
            samp_query="SELECT COVAR_SAMP({0}, {1}) FROM {2}; ",
            pop_query="SELECT COVAR_POP({0}, {1}) FROM {2}; ",
            data_model=data_model,
            write_database=write_database,
            write_schema=write_schema,
            feature1=feature_1,
            feature2=feature_2,
            granularity_levels=granularity_levels,
            if_exists=if_exists,
            samp=samp,
        )

        return cov

    def _warehouse_corrcoef(
        self,
        data_model: "DataModel",
        write_database: str,
        write_schema: str,
        feature_1: str,
        feature_2: str,
        granularity_levels: List[str],
        if_exists: PandasTableExistsActionType,
    ):
        corrcoef = db_utils._construct_submit_return_warehouse_stats_two_feat(
            dbconn=self,
            samp_query="SELECT CORR({0}, {1}) FROM {2}; ",
            pop_query="SELECT CORR({0}, {1}) FROM {2}; ",
            data_model=data_model,
            write_database=write_database,
            write_schema=write_schema,
            feature1=feature_1,
            feature2=feature_2,
            granularity_levels=granularity_levels,
            if_exists=if_exists,
        )

        return corrcoef

    def _get_connection_url(self):
        from sqlalchemy.engine import URL

        if self._authenticator == "oauth" and not self._token:
            self._token = cryptocode.encrypt(
                getpass.getpass(prompt="Please enter your oauth token for Snowflake: "),
                self.platform_type.value,
            )
        if not self._private_key and not self._token:
            if not self._password:
                self._password = cryptocode.encrypt(
                    getpass.getpass(prompt="Please enter your password for Snowflake: "),
                    self.platform_type.value,
                )
            password = cryptocode.decrypt(self._password, self.platform_type.value)
            connection_url = URL.create(
                "snowflake",
                username=self._username,
                password=password,
                host=self._account,
                database=self._database + "/" + self._schema,
            )
        else:
            connection_url = URL.create(
                "snowflake",
                username=self._username,
                host=self._account,
                database=self._database + "/" + self._schema,
            )
        return connection_url

    def _get_connection_parameters(self):
        parameters = {"warehouse": self._warehouse, "authenticator": self._authenticator}
        if self._role:
            parameters["role"] = self._role
        if self._token:
            parameters["token"] = cryptocode.decrypt(self._token, self.platform_type.value)
        if self._private_key:
            parameters["private_key"] = ssl.PEM_cert_to_DER_cert(
                cryptocode.decrypt(self._private_key, self.platform_type.value)
            )
        return parameters

    def _fix_table_name(
        self,
        table_name: str,
    ):
        """Required for snowflake, which requires lowercase for writing to a database when method is "replace" if the table exists.

        Args:
            table_name (str): the table name

        Returns:
            str: the table name, potentially changed to upper, lower, or mixed case as required by the implementing database
        """
        return table_name.lower()

    def _fix_column_name(
        self,
        column_name: str,
    ) -> str:
        """Required for snowflake, which requires uppercase column names when writing a dataframe to a table.

        Args:
            column_name (str): the column name

        Returns:
            str: the column name, potentially changed to upper, lower, or mixed case as required by the implementing database
        """
        return column_name.upper()

    def write_df_to_db(
        self,
        table_name,
        dataframe: pd.DataFrame,
        if_exists: PandasTableExistsActionType = PandasTableExistsActionType.FAIL,
        chunksize=10000,
    ):
        inspection = getfullargspec(self.write_df_to_db)
        validate_by_type_hints(inspection=inspection, func_params=locals())

        from snowflake.connector.pandas_tools import pd_writer

        # we want to throw an error if they pass a datetime without a timezone
        dataframe_datatypes = dataframe.dtypes

        bad_time_types = [
            name for name, val in dataframe_datatypes.items() if val.name == "datetime64[ns]"
        ]
        # try to deal with date types that got misconverted
        actual_bad_time_types = []
        convert_times = []
        for colV in bad_time_types:
            unique_times = dataframe[colV].dt.time.unique()
            if len(unique_times) == 1:
                if (dataframe[colV].dt.time.unique()[0].hour == 0) and (
                    dataframe[colV].dt.time.unique()[0].minute == 0
                ):
                    convert_times.append(colV)
                    continue
            actual_bad_time_types.append(colV)

        if len(actual_bad_time_types) > 0:
            raise atscale_errors.UserError(
                f"Please ensure the datetime64 columns {actual_bad_time_types} have timezones for snowflake compatibility."
            )
        for colV in convert_times:
            logger.info(f"Converting column: {colV} to Date type for snowflake")
            dataframe[colV] = dataframe[colV].dt.date

        fixed_df = dataframe.rename(columns=lambda c: self._fix_column_name(c))
        fixed_table_name = self._fix_table_name(table_name)
        fixed_df.to_sql(
            name=fixed_table_name,
            con=self.engine,
            schema=self._schema,
            if_exists=if_exists.value,
            index=False,
            chunksize=chunksize,
            method=pd_writer,
        )

    def _write_pysparkdf_to_external_db(
        self,
        pyspark_dataframe,
        jdbc_format: str,
        jdbc_options: Dict[str, str],
        table_name: str = None,
        if_exists: PysparkTableExistsActionType = PysparkTableExistsActionType.ERROR,
    ):
        from functools import reduce

        try:
            from pyspark.sql import SparkSession
        except ImportError as e:
            raise atscale_errors.AtScaleExtrasDependencyImportError("jdbc", str(e))

        columnsToSwitch = pyspark_dataframe.columns
        newColumnNames = [self._fix_column_name(x) for x in columnsToSwitch]

        pyspark_dataframe_renamed = reduce(
            lambda data, idx: data.withColumnRenamed(columnsToSwitch[idx], newColumnNames[idx]),
            range(len(columnsToSwitch)),
            pyspark_dataframe,
        )

        if table_name is not None:
            fixed_table_name = self._fix_table_name(table_name)
        else:
            fixed_table_name = None

        if jdbc_options.get("dbtable") is not None:
            jdbc_options["dbtable"] = self._fix_table_name(jdbc_options["dbtable"])

        super()._write_pysparkdf_to_external_db(
            pyspark_dataframe_renamed, jdbc_format, jdbc_options, fixed_table_name, if_exists
        )

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

    # def verify(self, project_dataset: dict, connection: dict) -> bool:
    # check the connection information
    #    if connection is None:
    #        return False

    #    if connection.get('platformType') != self.platform_type.value:
    #        return False

    # We cannot use the database value on a connection from the org to verify. This is because the project json
    # can refer to a database that is different from the original one used when setting up the connection for the org.
    # So at this point,  unless we figure out how to check port or host (snowflake does host in a weird way), I don't
    # think we can use any other info from the actual connection info to verify. The rest of the info we have to use from
    # the project, which I do below.

    # check info in the project_dataset which points at the connection (so database should agree)
    #    if project_dataset is None:
    #        return False

    #    phys = project_dataset.get('physical')
    #    if phys is None:
    #        return False

    #    tables = phys.get('tables')
    #    if tables is None:
    #        return False

    # Apparently tables is a list so there can be more than one?
    # Not sure what that means for verification. We'll look for at least one that matches.
    #    for table in tables:
    #        if table.get('database') == self._database and table.get('schema') == self._schema:
    #            return True

    #    return False
