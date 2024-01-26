from abc import ABC, abstractmethod
from typing import Dict, List
import pandas as pd
from pandas import DataFrame
from numpy import array, sqrt
from atscale.base.enums import PlatformType, PandasTableExistsActionType
from atscale.base.enums import PysparkTableExistsActionType
from atscale.errors import atscale_errors
from copy import deepcopy


class SQLConnection(ABC):
    """The abstract class meant to standardize functionality related to various DB systems that AI-Link supports.
    This includes submitting queries, writeback, and engine disposal.
    """

    def __init__(self, warehouse_id: str = None):
        """Constructs an instance of the SQLAlchemyConnection SQLConnection

        Args:
            warehouse_id (str, optional): The AtScale warehouse id to automatically associate the connection with if writing tables. Defaults to None.
        """
        self._warehouse_id = warehouse_id

    @property
    def warehouse_id(self) -> str:
        return self._warehouse_id

    @warehouse_id.setter
    def warehouse_id(self, value):
        self._warehouse_id = value

    platform_type: PlatformType
    """The enum representing platform type. Used in validating connections between AtScale DataModels and their 
        source databases"""

    @property
    def platform_type(self) -> PlatformType:
        """Getter for the instance type of this SQLConnection

        Returns:
            PlatformType: Member of the PlatformType enum
        """
        return SQLConnection.platform_type

    @platform_type.setter
    def platform_type(
        self,
        value,
    ):
        """Setter for the platform_type instance variable. This variable is final, please construct a new SQLConnection.

        Args:
            value: setter cannot be used.

        Raises:
            Exception: Raises a value if the setter is attempted.
        """
        raise atscale_errors.UnsupportedOperationException(
            "The platform type of a SQLConnection class is final; it cannot be altered."
        )

    @abstractmethod
    def clear_auth(self):
        """Clears any authentication information, like password or token from the connection."""
        raise NotImplementedError

    @abstractmethod
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
        raise NotImplementedError

    @abstractmethod
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
        raise NotImplementedError

    @abstractmethod
    def execute_statements(
        self,
        statements_list: list,
    ):
        """Executes a list of SQL statements. Does not return any results but may trigger an exception.

        Args:
            statements_list (list): a list of SQL statements to execute.
        """
        raise NotImplementedError

    def _fix_table_name(
        self,
        table_name: str,
    ):
        return table_name

    def _fix_column_name(
        self,
        column_name: str,
    ):
        return column_name

    @abstractmethod
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
        raise NotImplementedError

    def _write_pysparkdf_to_external_db(
        self,
        pyspark_dataframe,
        jdbc_format: str,
        jdbc_options: Dict[str, str],
        table_name: str = None,
        if_exists: PysparkTableExistsActionType = PysparkTableExistsActionType.ERROR,
    ):
        """Writes the provided pyspark DataFrame into the provided table name via jdbc. Can pass in if_exists to indicate the intended behavior if
            the provided table name is already taken.

        Args:
            pyspark_dataframe (pyspark.sql.dataframe.DataFrame): The pyspark dataframe to write
            jdbc_format (str): the driver class name. For example: 'jdbc', 'net.snowflake.spark.snowflake', 'com.databricks.spark.redshift'
            jdbc_options (Dict[str,str]): Case-insensitive to specify connection options for jdbc
            table_name (str): What table to write the dataframe into, can be none if 'dbtable' option specified
            if_exists (PysparkTableExistsActionType, optional): The intended behavior in case of table name collisions.
                Defaults to PysparkTableExistsActionType.ERROR.
        """
        try:
            from pyspark.sql import SparkSession
        except ImportError as e:
            raise atscale_errors.AtScaleExtrasDependencyImportError("spark", str(e))

        # we want to avoid editing the source dictionary
        jdbc_copy = deepcopy(jdbc_options)

        # quick check on passed tablename parameters
        if jdbc_copy.get("dbtable") is None:
            if table_name is None:
                raise atscale_errors.UserError(
                    "A table name must be specified for the written table. This can be done "
                    'either through the jdbc_options key "dbtable" or the table_name function parameter'
                )
            else:
                jdbc_copy["dbtable"] = table_name
        elif table_name is not None:
            if table_name != jdbc_copy.get("dbtable"):
                raise atscale_errors.UserError(
                    'Different table names passed via the jdbc_options key "dbtable" '
                    "and the table_name function parameter. Please get one of the 2 options"
                )

        pyspark_dataframe.write.format(jdbc_format).options(**jdbc_copy).mode(
            if_exists.value
        ).save()

    def _verify(
        self,
        con: dict,
    ) -> bool:
        if con is None:
            return False

        return self.platform_type.value == con.get("platformType")

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
        return table_name

    def _generate_date_table(self):
        df_date = pd.DataFrame()
        df_date["date"] = pd.date_range("1/1/1900", "12/31/2099")
        df_date["year"] = df_date["date"].dt.year
        df_date["month"] = df_date["date"].dt.month
        df_date["month_name"] = df_date["date"].dt.month_name()
        df_date["day_name"] = df_date["date"].dt.day_name()
        df_date["date"] = df_date["date"].dt.date
        self.write_df_to_db("atscale_date_table", df_date)

    @staticmethod
    def _column_quote():
        return "`"

    @staticmethod
    def _lin_reg_str():
        return " AS vals UNION ALL "

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
        from atscale.utils.eda_utils import _Stats, _stats_connection_wrapper

        stats_obj = _Stats()
        stats_obj.base_table_granularity_levels = granularity_levels
        stats_obj.base_table_numeric_features = {feature}
        stats_obj.query_dict = {"var": {feature: 0.0}, "cov": None}

        _stats_connection_wrapper(
            dbconn=self,
            stats_obj=stats_obj,
            data_model=data_model,
            write_database=write_database,
            write_schema=write_schema,
            sample=samp,
            if_exists=if_exists,
        )

        var = array(stats_obj.query_dict["var"][feature])[0][0]

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
        return sqrt(
            self._warehouse_variance(
                dbconn=self,
                data_model=data_model,
                write_database=write_database,
                write_schema=write_schema,
                feature=feature,
                granularity_level=granularity_levels,
                if_exists=if_exists,
                samp=samp,
            )
        )

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
        from atscale.utils.eda_utils import _Stats, _stats_connection_wrapper

        stats_obj = _Stats()
        stats_obj.base_table_granularity_levels = granularity_levels
        stats_obj.base_table_numeric_features = {feature_1, feature_2}
        stats_obj.query_dict = {"var": {}, "cov": [feature_1, feature_2]}

        _stats_connection_wrapper(
            dbconn=self,
            data_model=data_model,
            stats_obj=stats_obj,
            write_database=write_database,
            write_schema=write_schema,
            sample=samp,
            if_exists=if_exists,
        )

        cov = array(stats_obj.query_dict["cov"])[0][0]

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
        from atscale.utils.eda_utils import _Stats, _stats_connection_wrapper

        stats_obj = _Stats()
        stats_obj.base_table_granularity_levels = granularity_levels
        stats_obj.base_table_numeric_features = {feature_1, feature_2}
        stats_obj.query_dict = {
            "var": {feature_1: 0.0, feature_2: 0.0},
            "cov": [feature_1, feature_2],
        }

        _stats_connection_wrapper(
            dbconn=self,
            data_model=data_model,
            stats_obj=stats_obj,
            write_database=write_database,
            write_schema=write_schema,
            if_exists=if_exists,
        )

        v1 = array(stats_obj.query_dict["var"][feature_1])[0][0]
        v2 = array(stats_obj.query_dict["var"][feature_2])[0][0]
        cov = array(stats_obj.query_dict["cov"])[0][0]

        return cov / sqrt(v1 * v2)
