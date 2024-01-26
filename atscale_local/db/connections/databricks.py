from pandas import DataFrame
import cryptocode
import getpass
import inspect
import logging
from inspect import getfullargspec
from atscale.utils.validation_utils import validate_by_type_hints
from atscale.errors import atscale_errors
from atscale.errors.atscale_errors import AtScaleExtrasDependencyImportError
from atscale.db.sqlalchemy_connection import SQLAlchemyConnection
from atscale.base.enums import (
    PlatformType,
    PandasTableExistsActionType,
    PysparkTableExistsActionType,
)
from atscale.utils import validation_utils, db_utils
from typing import List

logger = logging.getLogger(__name__)


class Databricks(SQLAlchemyConnection):
    """The child class of SQLConnection whose implementation is meant to handle
    interactions with Databricks.
    """

    platform_type: PlatformType = PlatformType.DATABRICKS

    conversion_dict = {
        "<class 'numpy.int32'>": "INT",
        "<class 'numpy.int64'>": "BIGINT",
        "<class 'numpy.uint64'>": "BIGINT",
        "<class 'numpy.float64'>": "DOUBLE",
        "<class 'str'>": "STRING",
        "<class 'numpy.bool_'>": "BOOLEAN",
        "<class 'pandas._libs.tslibs.timestamps.Timestamp'>": "TIMESTAMP",
        "<class 'datetime.date'>": "DATE",
        "<class 'decimal.Decimal'>": "DECIMAL",
        "<class 'numpy.datetime64'>": "TIMESTAMP",
    }

    def __init__(
        self,
        host: str,
        catalog: str,
        schema: str,
        http_path: str,
        token: str = None,
        port: int = 443,
        warehouse_id: str = None,
    ):
        """Constructs an instance of the Databricks SQLConnection. Takes arguments necessary to find the host
            and schema. Since prompting login is not viable, this requires an authorization token.

        Args:
            host (str): The host of the intended Databricks connections
            catalog (str): The catalog of the intended Databricks connections
            schema (str): The schema of the intended Databricks connections
            http_path (str): The web path of the intended Databricks connections
            token (str, optional): The authorization token needed to interact with Databricks. Will prompt if None
            port (int, optional): A port for the connection. Defaults to 443.
            warehouse_id (str, optional): The AtScale warehouse id to automatically associate the connection with if writing tables. Defaults to None.
        """

        try:
            from sqlalchemy import create_engine
            from databricks import sql
        except ImportError as e:
            raise AtScaleExtrasDependencyImportError("databricks", str(e))

        super().__init__(warehouse_id)

        inspection = getfullargspec(self.__init__)
        validate_by_type_hints(inspection=inspection, func_params=locals())

        if token:
            self._token = cryptocode.encrypt(token, self.platform_type.value)
        else:
            self._token = None
        self._host = host
        self._catalog = catalog
        self._schema = schema
        self._http_path = http_path
        self._port = port
        try:
            validation_connection = self.engine.connect()
            validation_connection.close()
            self.dispose_engine()
        except:
            logger.error("Unable to create database connection, please verify the inputs")
            raise

    @property
    def token(self) -> str:
        raise atscale_errors.UnsupportedOperationException("Token cannot be retrieved.")

    @token.setter
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
    def catalog(self) -> str:
        return self._catalog

    @catalog.setter
    def catalog(
        self,
        value,
    ):
        # validate the non-null inputs
        if value is None:
            raise ValueError(f"The following required parameters are None: value")
        self._catalog = value
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
    def http_path(self) -> str:
        return self._http_path

    @http_path.setter
    def http_path(
        self,
        value,
    ):
        # validate the non-null inputs
        if value is None:
            raise ValueError(f"The following required parameters are None: value")
        self._http_path = value
        self.dispose_engine()

    @property
    def port(self) -> int:
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
    def _database(self):
        return self._catalog

    def clear_auth(self):
        """Clears any authentication information, like password or token from the connection."""
        self._token = None
        self.dispose_engine()

    def _get_connection_url(self):
        from sqlalchemy.engine import URL

        if not self._token:
            self._token = cryptocode.encrypt(
                getpass.getpass(prompt="Please enter your Databricks token: "),
                self.platform_type.value,
            )
        token = cryptocode.decrypt(self._token, self.platform_type.value)
        connection_url = URL.create(
            "databricks+connector",
            username="token",
            password=token,
            host=self._host,
            port=self._port,
            database=self._catalog,
        )
        return connection_url

    def _get_connection_parameters(self):
        parameters = {"http_path": self._http_path}
        return parameters

    @staticmethod
    def _format_types(
        dataframe: DataFrame,
    ) -> dict:
        types = {}
        for i in dataframe.columns:
            if (
                str(type(dataframe[i].loc[~dataframe[i].isnull()].iloc[0]))
                in Databricks.conversion_dict
            ):
                types[i] = Databricks.conversion_dict[
                    str(type(dataframe[i].loc[~dataframe[i].isnull()].iloc[0]))
                ]
            else:
                types[i] = Databricks.conversion_dict["<class 'str'>"]
        return types

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
            samp_query="select var_samp({0}) from {1}; ",
            pop_query="select var_pop({0}) from {1}; ",
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
            samp_query="select stddev_samp({0}) from {1}; ",
            pop_query="select stddev_pop({0}) from {1}; ",
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
            samp_query="select covar_samp({0}, {1}) from {2}; ",
            pop_query="select covar_pop({0}, {1}) from {2}; ",
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
            samp_query="select corr({0}, {1}) from {2}; ",
            pop_query="select corr({0}, {1}) from {2}; ",
            data_model=data_model,
            write_database=write_database,
            write_schema=write_schema,
            feature1=feature_1,
            feature2=feature_2,
            granularity_levels=granularity_levels,
            if_exists=if_exists,
        )

        return corrcoef

    def submit_query(
        self,
        query,
    ):
        # validate the non-null inputs
        if query is None:
            raise ValueError(f"The following required parameters are None: query")
        return self.submit_queries([query])[0]

    def submit_queries(
        self,
        query_list: list,
    ) -> list:
        inspection = getfullargspec(self.submit_queries)
        validate_by_type_hints(inspection=inspection, func_params=locals())

        from databricks import sql

        connection = sql.connect(
            server_hostname=self._host,
            http_path=self._http_path,
            access_token=cryptocode.decrypt(self._token, self.platform_type.value),
        )
        cursor = connection.cursor()

        results = []
        for query in query_list:
            cursor.execute(query)
            result = cursor.fetchall_arrow()
            df = result.to_pandas()
            results.append(df)
        cursor.close()
        connection.close()
        return results

    def _create_table(
        self,
        table_name: str,
        types: dict,
        cursor,
    ):
        # If the table exists we'll just let this fail and raise the appropriate exception.
        # Related checking to handle gracefully is within calling methods.
        operation = f"CREATE TABLE {self._create_table_path(table_name)} ("
        for key, value in types.items():
            operation += f"`{key}` {value}, "
        operation = operation[:-2]
        operation += ")"
        cursor.execute(operation)
        # autocommit should be on by default

    def write_df_to_db(
        self,
        table_name: str,
        dataframe: DataFrame,
        if_exists: PandasTableExistsActionType = PandasTableExistsActionType.FAIL,
        chunksize: int = 1000,
    ):
        inspection = getfullargspec(self.write_df_to_db)
        validate_by_type_hints(inspection=inspection, func_params=locals())
        from databricks import sql

        connection = sql.connect(
            server_hostname=self._host,
            http_path=self._http_path,
            access_token=cryptocode.decrypt(self._token, self.platform_type.value),
        )
        cursor = connection.cursor()

        tables = cursor.tables(
            table_name=table_name, schema_name=self.schema, catalog_name=self.catalog
        ).fetchall()
        if len(tables) > 1:
            raise ValueError(
                f"{table_name} already exists in schema: {self.schema} for catalog: "
                f"{self.catalog} with type {tables[0].asDict().get('TABLE_TYPE')} "
                f"and must be dropped to create a table with the same name"
            )
        if len(tables) == 1:
            if tables[0].asDict().get("TABLE_TYPE") != "TABLE":
                raise ValueError(
                    f"{table_name} already exists in schema: {self.schema} for catalog: "
                    f"{self.catalog} with type {tables[0].asDict().get('TABLE_TYPE')} and "
                    f"must be dropped to create a table with the same name"
                )
            exists = True
        else:
            exists = False

        if exists and if_exists == PandasTableExistsActionType.FAIL:
            raise ValueError(
                f"A table or view named: {table_name} already exists in schema: {self.schema} for catalog: {self.catalog}"
            )

        types = self._format_types(dataframe)

        if exists and if_exists == PandasTableExistsActionType.REPLACE:
            operation = f"DROP TABLE {self._create_table_path(table_name)}"
            cursor.execute(operation)
            self._create_table(table_name, types, cursor)
        elif not exists:
            self._create_table(table_name, types, cursor)

        # add in break characters
        for key, value in types.items():
            if "STRING" in value:
                dataframe[key] = dataframe[key].str.replace(r"'", r"\'")

        operation = f"INSERT INTO {self._create_table_path(table_name)} VALUES ("

        list_df = [dataframe[i : i + chunksize] for i in range(0, dataframe.shape[0], chunksize)]
        for df in list_df:
            op_copy = operation
            for index, row in df.iterrows():
                for col in df.columns:
                    if "STRING" in types[col] or "DATE" in types[col] or "TIMESTAMP" in types[col]:
                        op_copy += f"'{row[col]}', "
                    else:
                        op_copy += f"{row[col]}, ".replace("nan", "null")
                op_copy = op_copy[:-2]
                op_copy += "), ("
            op_copy = op_copy[:-3]
            cursor.execute(op_copy)
        # adding close of cursor which I didn't see before
        cursor.close()
        connection.close()

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
        return f"{self._column_quote()}{self.catalog}{self._column_quote()}.{self._column_quote()}{self.schema}{self._column_quote()}.{self._column_quote()}{table_name}{self._column_quote()}"
