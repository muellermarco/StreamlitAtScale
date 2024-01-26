from abc import abstractmethod
from pandas import DataFrame, read_sql_query
import inspect
import logging
from inspect import getfullargspec
from atscale.utils.validation_utils import validate_by_type_hints
from atscale.errors.atscale_errors import UserError
from atscale.db.sql_connection import SQLConnection
from atscale.base.enums import PandasTableExistsActionType
from atscale.utils import validation_utils

logger = logging.getLogger(__name__)


class SQLAlchemyConnection(SQLConnection):
    """An abstract class that adds common functionality for SQLAlchemy to reduce duplicate code in implementing classes.
    SQLAlchemy does not support all databases, so some classes may need to implement SQLConnection directly.
    """

    def __init__(self, warehouse_id: str = None):
        """Constructs an instance of the SQLAlchemyConnection SQLConnection

        Args:
            warehouse_id (str, optional): The AtScale warehouse id to automatically associate the connection with if writing tables. Defaults to None.
        """
        import sqlalchemy

        super().__init__(warehouse_id)
        self._engine = None

    @property
    def engine(self):
        if self._engine is not None:
            return self._engine
        from sqlalchemy import create_engine

        url = self._get_connection_url()
        parameters = self._get_connection_parameters()
        self._engine = create_engine(url, connect_args=parameters)
        return self._engine

    @engine.setter
    def engine(
        self,
        value,
    ):
        """Setter for the engine instance variable. If passing an engine, using other setters may dispose of the engine
        and require it to be set again because the required info to construct it will not be present.

        Args:
            value: a sqlalchemy engine.

        """
        from sqlalchemy.engine.base import Engine

        logger.warning(
            "Using setters on the database connection object will dispose the engine and will require it to be reset."
        )
        if not isinstance(value, Engine):
            raise ValueError("Value passed is not a sqlalchemy engine")
        self._engine = value

    @abstractmethod
    def _get_connection_url(self):
        """Constructs a connection url from the instance variables needed to interact with the DB

        Returns:
            str: The connection url to the DB of interest
        """
        raise NotImplementedError

    def _get_connection_parameters(self):
        """Constructs a connection parameters from the instance variables needed to interact with the DB

        Returns:
            dict: The connection parameters to the DB of interest
        """
        return {}

    def dispose_engine(self):
        """
        Use this method to close the engine and any associated connections in its connection pool.

        If the user changes the connection parameters on an sql_connection object then  dispose() should be called so any current
        connections (and engine) is cleared of all state before establishing a new connection (and engine and connection pool). Probably
        don't want to call this in other situations. From the documentation: https://docs.sqlalchemy.org/en/13/core/connections.html#engine-disposal

        <The Engine is intended to normally be a permanent fixture established up-front and maintained throughout the lifespan of an application.
        It is not intended to be created and disposed on a per-connection basis>
        """
        if self._engine is not None:
            self._engine.dispose()
            # setting none will cause the getter for engine to grab the connection
            # URL anew and create the engine rather than hanging onto a diposed one
            self._engine = None

    def submit_query(
        self,
        query: str,
    ) -> DataFrame:
        """This submits a single query and reads the results into a DataFrame. It closes the connection after each query.

        Args:
            query (str): SQL statement to be executed

        Returns:
            DataFrame: the results of executing the SQL statement or query parameter, read into a DataFrame
        """
        inspection = getfullargspec(self.submit_query)
        validate_by_type_hints(inspection=inspection, func_params=locals())

        return self.submit_queries([query])[0]

    def submit_queries(
        self,
        query_list: list,
    ) -> list:
        """Submits a list of queries, collecting the results in a list of dictionaries.

        Args:
            query_list (list): a list of queries to submit.

        Returns:
            list(DataFrame): A list of pandas DataFrames containing the results of the queries.
        """
        inspection = getfullargspec(self.submit_queries)
        validate_by_type_hints(inspection=inspection, func_params=locals())

        results = []
        # This uses "with" for transaction management on the connection. If this is unfamiliar,
        # please see: https://docs.sqlalchemy.org/en/14/core/connections.html#using-transactions
        with self.engine.connect() as connection:
            for query in query_list:
                # read_sql_query is a pandas function,  but takes an SQLAlchemy connection object (or a couple other types).
                # https://pandas.pydata.org/docs/reference/api/pandas.read_sql_query.html
                # see test_snowflake.test_quoted_columns for discussion related to any potential changes to using read_sql_query
                results.append(read_sql_query(query, connection))
        return results

    def execute_statements(
        self,
        statement_list: list,
    ):
        """Executes a list of SQL statements. Does not return any results but may trigger an exception.

        Args:
            statement_list (list): a list of SQL statements to execute.
        """
        from sqlalchemy import text

        inspection = getfullargspec(self.execute_statements)
        validate_by_type_hints(inspection=inspection, func_params=locals())

        with self.engine.connect() as connection:
            for statement in statement_list:
                connection.execute(text(statement))

    def write_df_to_db(
        self,
        table_name: str,
        dataframe: DataFrame,
        dtypes: dict = None,
        if_exists: PandasTableExistsActionType = PandasTableExistsActionType.FAIL,
        chunksize: int = 1000,
    ):
        """Writes the provided pandas DataFrame into the provided table name. Can pass in if_exists to indicate the intended behavior if
            the provided table name is already taken.

        Args:
            table_name (str): What table to write the dataframe into
            dataframe (DataFrame): The pandas DataFrame to write into the table
            dtypes (dict, optional): the datatypes of the passed dataframe. Keys should match the column names. Defaults to None
                and type will be text.
            if_exists (PandasTableExistsActionType, optional): The intended behavior in case of table name collisions.
                Defaults to PandasTableExistsActionType.FAIL.
            chunksize (int, optional): the chunksize for the write operation.
        """
        inspection = getfullargspec(self.execute_statements)
        validate_by_type_hints(inspection=inspection, func_params=locals())

        with self.engine.connect() as connection:
            dataframe.to_sql(
                name=table_name,
                con=connection,
                schema=self._schema,
                method="multi",
                index=False,
                dtype=dtypes,
                chunksize=chunksize,
                if_exists=if_exists.value,
            )
