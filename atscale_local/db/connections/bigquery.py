import inspect
import os
import logging
from pandas import DataFrame
from inspect import getfullargspec
from atscale.utils.validation_utils import validate_by_type_hints
from atscale.errors import atscale_errors
from atscale.db.sql_connection import SQLConnection
from atscale.base.enums import PlatformType, PandasTableExistsActionType
from atscale.utils import validation_utils

logger = logging.getLogger(__name__)


class BigQuery(SQLConnection):
    """The implements SQLConnection to handle interactions with Google BigQuery."""

    platform_type: PlatformType = PlatformType.GBQ

    def __init__(
        self,
        gbq_project_id: str,
        dataset: str,
        credentials_path: str = None,
        warehouse_id: str = None,
    ):
        """Constructs an instance of the BigQuery SQLConnection. Takes arguments necessary to find the project
            and dataset. If credentials_path is not provided, it will prompt the user to login.

        Args:
            gbq_project_id (str): the gbq project id to connect to
            dataset (str): the name of the dataset within gbq
            credentials_path (str, optional): The path to a credentials file. If provided,
                this method will set the environment variable GOOGLE_APPLICATION_CREDENTIALS to
                this value which is used automatically by GBQ auth methods.
                See: https://googleapis.dev/python/google-api-core/latest/auth.html
                Defaults to None.
            warehouse_id (str, optional): The AtScale warehouse id to automatically associate the connection with if writing tables. Defaults to None.
        """

        try:
            import pandas_gbq
            from google.cloud import bigquery
        except ImportError as e:
            raise atscale_errors.AtScaleExtrasDependencyImportError("gbq", str(e))

        super().__init__(warehouse_id)

        inspection = getfullargspec(self.__init__)
        validate_by_type_hints(inspection=inspection, func_params=locals())

        if credentials_path:
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = credentials_path

        self._gbq_project_id = gbq_project_id
        self._dataset = dataset

        try:
            validation_client = bigquery.Client(project=self._gbq_project_id)
            validation_client.close()
        except:
            logger.error("Unable to create database connection, please verify the inputs")
            raise

    @property
    def gbq_project_id(self) -> str:
        return self._gbq_project_id

    @gbq_project_id.setter
    def gbq_project_id(
        self,
        value,
    ):
        # validate the non-null inputs
        if value is None:
            raise ValueError(f"The following required parameters are None: value")
        self._gbq_project_id = value

    @property
    def dataset(self) -> str:
        return self._dataset

    @dataset.setter
    def dataset(
        self,
        value,
    ):
        # validate the non-null inputs
        if value is None:
            raise ValueError(f"The following required parameters are None: value")
        self._dataset = value

    @property
    def _database(self):
        return self._gbq_project_id

    @property
    def _schema(self):
        return self._dataset

    def clear_auth(self):
        """Clears any authentication information, in the case of GBQ does nothing."""
        logger.warning(
            f"The credential_path is not stored by AI-Link. To avoid potential conflict "
            f"with other services, the GOOGLE_APPLICATION_CREDENTIALS environment variable has not been cleared"
        )

    # Perhaps bad form, but leaving this code snippet here for future potential purposes. This class used to implement
    # SQLAlchemyConnection. By uncommenting this it can again. This worked fine, however, the dialect version as of me
    # writing this generated a bunch of warnings from the main library. We were already using pandas_gbq for most things
    # anyway so I just wrote up an execute_statements that used the gbq client directly and removed the SQLAlchemy stuff.
    # def _get_connection_url(self):
    #     if self._credentials_path is not None:
    #         connection_url = f'bigquery://{self._gbq_project_id}/{self._dataset}?credentials_path={self._credentials_path}'
    #     else:
    #         connection_url = f'bigquery://{self._gbq_project_id}/{self._dataset}'
    #     return connection_url
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
        # see: https://pandas-gbq.readthedocs.io/en/latest/reading.html#
        # not using an SQLAlchemy engine or connection for this, but rather using the built
        # in pandas_gbq support.
        inspection = getfullargspec(self.submit_queries)
        validate_by_type_hints(inspection=inspection, func_params=locals())

        import pandas_gbq

        results = []
        for query in query_list:
            results.append(pandas_gbq.read_gbq(query, project_id=self.gbq_project_id))
        return results

    def write_df_to_db(
        self,
        table_name: str,
        dataframe: DataFrame,
        if_exists: PandasTableExistsActionType = PandasTableExistsActionType.FAIL,
    ):
        # The code combined sqlalchemy with builtin pandas options if we have pandas_gbq installed.
        # I just went with pandas_gbq approaches direclty on a dataframe and removed sqlalchemy for now.
        # We're only wrapping pandas_gbq methods and not adding anythning here - the only reason to have this
        # is so we can pass in this object to a writeback method, along with a model, to verify the db and tables line up
        # and so that we control the actual table writing and then joining with the model in one method (to ensure those things line up).

        inspection = getfullargspec(self.write_df_to_db)
        validate_by_type_hints(inspection=inspection, func_params=locals())

        import pandas_gbq
        import datetime
        import pandas as pd
        from pyarrow.lib import ArrowTypeError

        schema_edits = []
        first_valid_indexes = dataframe.apply(pd.Series.first_valid_index)

        # run a query to see if the table exists, verified that an empty table will be marked as existing
        check_table_exists = self.submit_query(
            f"SELECT size_bytes FROM {self._column_quote()}{self.gbq_project_id}{self._column_quote()}.{self._column_quote()}{self.dataset}{self._column_quote()}.__TABLES__ WHERE table_id='{table_name}'"
        )
        table_exists = False
        if len(check_table_exists) > 0:
            table_exists = True

        for col in dataframe.columns:
            first_valid_index = first_valid_indexes.loc[col]
            if pd.notnull(first_valid_index):
                val_to_check = dataframe[col][first_valid_index]
                if isinstance(val_to_check, datetime.date) and not isinstance(
                    val_to_check, datetime.datetime
                ):
                    schema_edits.append({"name": col, "type": "DATE"})

        try:
            pandas_gbq.to_gbq(
                dataframe,
                f"{self.dataset}.{table_name}",
                project_id=self.gbq_project_id,
                if_exists=if_exists.value,
                table_schema=schema_edits,
            )
        except ArrowTypeError as err:
            if table_exists == False:
                sql = f"DROP TABLE {self._create_table_path(table_name)}"
                self.execute_statements([sql])
                logger.error("Issue with column types of inbound dataframe, dropping table")
                raise (err)

    def execute_statements(
        self,
        statement_list: list,
    ):
        """Executes a list of SQL statements. Does not return any results but may trigger an exception.

        Args:
            statement_list (list): a list of SQL statements to execute.
        """
        inspection = getfullargspec(self.execute_statements)
        validate_by_type_hints(inspection=inspection, func_params=locals())

        from google.cloud import bigquery

        client = bigquery.Client(project=self._gbq_project_id)
        for statement in statement_list:
            query_job = client.query(statement)
            # Waits for job to complete, but currently we do nothing with result
            results = query_job.result()

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
        return f"{self._column_quote()}{self.gbq_project_id}{self._column_quote()}.{self._column_quote()}{self.dataset}{self._column_quote()}.{self._column_quote()}{table_name}{self._column_quote()}"
