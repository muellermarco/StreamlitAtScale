import getpass
from typing import Dict
import cryptocode
import logging
from pandas import DataFrame, read_sql_query
from inspect import getfullargspec

from atscale.utils import validation_utils
from atscale.errors import atscale_errors
from atscale.db.sql_connection import SQLConnection
from atscale.base import enums

logger = logging.getLogger(__name__)


class Synapse(SQLConnection):
    """The child class of SQLConnection whose implementation is meant to handle
    interactions with a Synapse DB.
    """

    platform_type_str: str = "azuresqldw"

    conversion_dict = {
        "<class 'numpy.int32'>": "int",
        "<class 'numpy.int64'>": "bigint",
        "<class 'numpy.uint64'>": "bigint",
        "<class 'numpy.float64'>": "real",
        "<class 'str'>": "nvarchar(4000)",
        "<class 'numpy.bool_'>": "bit",
        "<class 'pandas._libs.tslibs.timestamps.Timestamp'>": "datetime",
        "<class 'datetime.date'>": "date",
        "<class 'decimal.Decimal'>": "decimal",
        "<class 'numpy.datetime64'>": "datetime",
    }

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
        """Constructs an instance of the Synapse SQLConnection. Takes arguments necessary to find the database, driver,
            and schema. If password is not provided, it will prompt the user to login.

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
            import pyodbc as po
        except ImportError as e:
            raise atscale_errors.AtScaleExtrasDependencyImportError("synapse", str(e))

        super().__init__(warehouse_id)

        inspection = getfullargspec(self.__init__)
        validation_utils.validate_by_type_hints(inspection=inspection, func_params=locals())

        self.username = username
        self.host = host
        self.database = database
        self.driver = driver
        self.schema = schema
        self.port = port
        if password:
            self._password = cryptocode.encrypt(password, self.platform_type_str)
        else:
            self._password = None

        try:
            validation_connection = po.connect(self._get_connection_url(), autommit=True)
            validation_connection.close()
        except:
            logger.error("Unable to create database connection, please verify the inputs")
            raise

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
        self._password = cryptocode.encrypt(value, self.platform_type_str)

    @property
    def _database(self) -> str:
        return self.database

    @property
    def _schema(self) -> str:
        return self.schema

    def clear_auth(self):
        """Clears any authentication information, like password or token from the connection."""
        self._password = None

    def _get_connection_url(self):
        if not self._password:
            self._password = cryptocode.encrypt(
                getpass.getpass(prompt="Please enter your Synapse password: "),
                self.platform_type_str,
            )
        password = cryptocode.decrypt(self._password, self.platform_type_str)
        connection_url = f"DRIVER={self.driver};SERVER={self.host};PORT={self.port};DATABASE={self.database};UID={self.username};PWD={password}"
        return connection_url

    @staticmethod
    def _format_types(
        dataframe: DataFrame,
    ) -> Dict:
        types = {}
        for i in dataframe.columns:
            if (
                str(type(dataframe[i].loc[~dataframe[i].isnull()].iloc[0]))
                in Synapse.conversion_dict
            ):
                types[i] = Synapse.conversion_dict[
                    str(type(dataframe[i].loc[~dataframe[i].isnull()].iloc[0]))
                ]
            else:
                types[i] = Synapse.conversion_dict["<class 'str'>"]
        return types

    def submit_queries(
        self,
        query_list: list,
    ) -> list:
        inspection = getfullargspec(self.submit_queries)
        validation_utils.validate_by_type_hints(inspection=inspection, func_params=locals())

        import pyodbc as po

        results = []
        with po.connect(self.connection_string, autocommit=True) as connection:
            for query in query_list:
                results.append(read_sql_query(query, connection))
        return results

    def execute_statements(
        self,
        statement_list: list,
    ):
        inspection = getfullargspec(self.execute_statements)
        validation_utils.validate_by_type_hints(inspection=inspection, func_params=locals())

        # same implementation is in IRIS, so if you need to change one please change the other
        import pyodbc as po

        with po.connect(self.connection_string, autocommit=False) as connection:
            with connection.cursor() as cursor:
                for statement in statement_list:
                    cursor.execute(statement)
                    connection.commit()

    def _create_table(
        self,
        table_name: str,
        types: Dict,
        cursor,
    ):
        # If the table exists we'll just let this fail and raise the appropriate exception.
        # Related checking to handle gracefully is within calling methods.
        operation = f"CREATE TABLE {self._create_table_path(table_name)} ("
        for key, value in types.items():
            operation += f"{key} {value}, "
        operation = operation[:-2]
        operation += ")"
        cursor.execute(operation)

    def write_df_to_db(
        self,
        table_name: str,
        dataframe: DataFrame,
        if_exists: enums.TableExistsAction = enums.TableExistsAction.ERROR,
        chunksize: int = 10000,
    ):
        inspection = getfullargspec(self.write_df_to_db)
        validation_utils.validate_by_type_hints(inspection=inspection, func_params=locals())

        if if_exists == enums.TableExistsAction.IGNORE:
            raise ValueError(
                "IGNORE action type is not supported for this operation, please adjust if_exists parameter"
            )

        import pyodbc

        connection = pyodbc.connect(self._get_connection_url(), autommit=True)
        cursor = connection.cursor()

        tables = cursor.tables(
            table_name=table_name, schema_name=self.schema, catalog_name=self.database
        ).fetchall()
        if len(tables) > 1:
            raise atscale_errors.CollisionError(
                f"{table_name} already exists in schema: {self.schema} for catalog: "
                f"{self.catalog} with type {tables[0].asDict().get('TABLE_TYPE')} "
                f"and must be dropped to create a table with the same name"
            )
        if len(tables) == 1:
            if tables[0].asDict().get("TABLE_TYPE") != "TABLE":
                raise atscale_errors.CollisionError(
                    f"{table_name} already exists in schema: {self.schema} for catalog: "
                    f"{self.catalog} with type {tables[0].asDict().get('TABLE_TYPE')} and "
                    f"must be dropped to create a table with the same name"
                )
            exists = True
        else:
            exists = False

        if exists and if_exists == enums.TableExistsAction.ERROR:
            raise atscale_errors.CollisionError(
                f"A table named: {table_name} already exists in schema: {self.schema}"
            )

        types = self._format_types(dataframe)

        if (
            exists and if_exists == enums.TableExistsAction.OVERWRITE
        ):  # if replace, then drop and recreate the table
            operation = f"DROP TABLE {self._create_table_path(table_name)}"
            cursor.execute(operation)
            self._create_table(table_name, types, cursor)
        elif not exists:
            self._create_table(table_name, types, cursor)

        operation = f"INSERT INTO {self._create_table_path(table_name)} ("
        for col in dataframe.columns:
            operation += f"{col}, "
        operation = operation[:-2]
        operation += ") "

        list_df = [dataframe[i : i + chunksize] for i in range(0, dataframe.shape[0], chunksize)]
        for df in list_df:
            op_copy = operation
            for index, row in df.iterrows():
                op_copy += "SELECT "
                for cl in df.columns:
                    if "nvarchar" in types[cl] or "date" in types[cl]:
                        op_copy += f"'{row[cl]}', "
                    else:
                        op_copy += f"{row[cl]}, "
                op_copy = op_copy[:-2]
                op_copy += " UNION ALL "
            op_copy = op_copy[:-11]
            cursor.execute(op_copy)
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
        return f"{self._column_quote()}{self.database}{self._column_quote()}.{self._column_quote()}{self.schema}{self._column_quote()}.{self._column_quote()}{table_name}{self._column_quote()}"

    @staticmethod
    def _sql_expression_day_or_less(
        sql_name: str,
        column_name: str,
    ):
        return f"DATETRUNC({sql_name}, {column_name})"

    @staticmethod
    def _sql_expression_week_or_more(
        sql_name: str,
        column_name: str,
    ):
        return f"DATEPART({sql_name}, {column_name})"
