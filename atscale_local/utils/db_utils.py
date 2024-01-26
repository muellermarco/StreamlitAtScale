import logging
from typing import List, Tuple, Dict, Union, Set, Any
from atscale.connection.connection import _Connection
from atscale.db.sql_connection import SQLConnection
from atscale.db.connections import bigquery, databricks, iris, mssql, redshift, snowflake, synapse
from atscale.errors import atscale_errors
from atscale.base import enums


def enum_to_dbconn(
    platform_type: enums.PlatformType,
) -> SQLConnection:
    """takes enums.PlatformType enum and returns an uninstantiated object of the associated SQLConnection class"""
    mapping = {
        enums.PlatformType.GBQ: bigquery.BigQuery,
        enums.PlatformType.DATABRICKS: databricks.Databricks,
        enums.PlatformType.IRIS: iris.Iris,
        enums.PlatformType.MSSQL: mssql.MSSQL,
        enums.PlatformType.REDSHIFT: redshift.Redshift,
        enums.PlatformType.SNOWFLAKE: snowflake.Snowflake,
        enums.PlatformType.SYNAPSE: synapse.Synapse,
    }
    return mapping[platform_type]


def get_atscale_tablename(
    atconn: _Connection,
    warehouse_id: str,
    database: str,
    schema: str,
    table_name: str,
) -> str:
    """Determines the tablename as referenced by AtScale.

    Args:
        atconn (_Connection):  The AtScale connection to use
        warehouse_id (str): The id in AtScale of the data warehouse to use
        database (str): The name of the database for the table
        schema (str): The name of the schema for the table
        table_name (str): The name of the table

    Raises:
        atscale_errors.UserError: If Atscale is unable to find the table this error will be raised

    Returns:
        str: The name AtScale shows for the table
    """
    atscale_tables = atconn._get_connected_tables(warehouse_id, database, schema)
    atscale_name, missing_name = _convert_names_to_atscale_names(
        names=[table_name], aliases=atscale_tables, warning_message="Table name: {} appears as {}"
    )
    if len(missing_name) > 0:
        raise atscale_errors.UserError(
            f"Unable to find table: {table_name}. If the table exists make sure AtScale has access to it"
        )
    return atscale_name[0]


def get_database_and_schema(
    dbconn: SQLConnection,
) -> Tuple[str, str]:
    """Returns a tuple of the (database property, schema property) of the sqlconn object. For those objects that don't natively
    have those properties, a private property was created that maps the native terminology to database and schema

    Args:
        dbconn (SQLConnection): The connection object to get properies from

    Returns:
        Tuple[str, str]: the (database, schema)
    """
    return dbconn._database, dbconn._schema


def get_column_dict(
    atconn: _Connection,
    dbconn: SQLConnection,
    warehouse_id: str,
    atscale_table_name: str,
    dataframe_columns: List[str],
) -> Dict:
    """Grabs columns from the AtScale table corresponding to the dataframe and compares columns from each, returning a dict where the
    keys are column names from the dataframe and the values are the column names as they appear in the atscale_table_name.

    Args:
        atconn (_Connection):  The AtScale connection to use
        dbconn (SQLConnection): The sql connection to use to connect to interact with the data warehouse. Primary used here to get any database and schema references for the connection.
        warehouse_id (str): The id of the warehouse for AtScale to use to reach the new table
        atscale_table_name (str): the name of the table in the data warehouse as recognized by atscale that corresponds to the dataframe
        dataframe_columns (List[str]): the DataFrame columns that corresponds to the atscale_table_name

    Raises:
        atscale_errors.UserError: Potential error if the dataframe features columns that are not found within the table referenced by atscale_table_name
    Returns:
        Dict: a Dict object where keys are the column names within the dataframe and the values are the columns as they appear in atscale_table_name as seen by AtScale.
    """

    database, schema = get_database_and_schema(dbconn=dbconn)
    atscale_columns = [
        c[0]
        for c in atconn._get_table_columns(
            warehouse_id=warehouse_id,
            table_name=atscale_table_name,
            database=database,
            schema=schema,
            expected_columns=dataframe_columns,
        )
    ]
    column_dict = {}
    missing_columns = []
    # iterate over the dataframe columns, looking for near matches to accomodate databases auto capitalizing names
    proper_columns: List[str] = dataframe_columns.copy()
    proper_columns, missing_columns = _convert_names_to_atscale_names(
        names=proper_columns,
        aliases=atscale_columns,
        warning_message="Column name: {} appears as {}",
    )
    if missing_columns:
        raise atscale_errors.UserError(
            f"Unable to find columns: {missing_columns} in table: {atscale_table_name}."
        )
    column_dict = {original: proper for original, proper in zip(dataframe_columns, proper_columns)}

    return column_dict


def _get_key_cols(
    key_dict: dict,
    dbconn: SQLConnection = None,
    spark_session=None,
):
    """If the provided key_dict requires a multi-column key (or has a key different from then value), then
        run a query to get the contents of the other join columns.

    Args:
        key_dict (dict): The dictionary describing the necessary key columns
        dbconn (SQLConnection): The connection object to query if necessary. Defaults to None.
        sparkSession (pyspark.sql.SparkSession): The pyspark SparkSession to execute the query with. Defaults to None.


    Returns:
        dataframe (pd.DataFrame): The additional columns information needed for the join
    """
    if dbconn is None and spark_session is None:
        raise ValueError("dbconn or spark_session must be provided.")
    if dbconn is not None:
        quote = dbconn._column_quote()
    else:
        quote = "`"
    # check the keys for the feature. If there are more than one or only one and it doesn't match the value we will need to pull in the columns we don't have
    if len(key_dict["key_cols"]) > 1 or key_dict["key_cols"][0] != key_dict["value_col"]:
        # if it is a qds we need to select from the query
        if key_dict["query"]:
            table = f'({key_dict["query"]})'
        # if not we want to build the fully qualified table name
        else:
            table = f'{quote}{key_dict["table_name"]}{quote}'
            if key_dict["schema"]:
                table = f'{quote}{key_dict["schema"]}{quote}.{table}'
            if key_dict["database"]:
                table = f'{quote}{key_dict["database"]}{quote}.{table}'
        needed_cols = key_dict["key_cols"]
        # the value column may or may not be one of the keys so add it if it is missing
        if key_dict["value_col"] not in needed_cols:
            needed_cols.append(key_dict["value_col"])
        column_string = f"{quote}, {quote}".join(needed_cols)
        query = f"SELECT DISTINCT {quote}{column_string}{quote} FROM {table}"
        df_key = dbconn.submit_query(query)
        df_key.columns = needed_cols
        return df_key
    return None


def _convert_names_to_atscale_names(
    names: List[str],
    aliases: Union[List[str], Dict[str, Any], Set[str]],
    warning_message: str = None,
) -> Tuple[List[str], List[str]]:
    """Returns a tuple of converted (if possible) names to aliases as well as the sublist of items that do not exist
    in the aliases parameter either as is or upper or lower cased."""
    aliases = set(aliases)  # convert to a set for constant time lookups
    missing_names = []
    fixed_names = []
    for original_name in names:
        if original_name in aliases:
            fixed_names.append(original_name)
        else:
            for fixed_name in [original_name.upper(), original_name.lower()]:
                if fixed_name in aliases:
                    fixed_names.append(fixed_name)
                    if warning_message is not None:
                        logging.warning(warning_message.format(original_name, fixed_name))
                    break
            else:  # this means if the for loop never hit the break statement
                fixed_names.append(original_name)
                missing_names.append(original_name)
    return fixed_names, missing_names


def _construct_submit_return_warehouse_stats_one_feat(
    dbconn: SQLConnection,
    samp_query: str,
    pop_query: str,
    data_model: "DataModel",
    write_database: str,
    write_schema: str,
    feature: str,
    granularity_levels: List[str],
    if_exists: enums.PandasTableExistsActionType,
    samp: bool,
) -> float:
    """Constructs and submits a stats query concerning one feature.

    Args:
        dbconn (SQLConnection): The database connection that the query will interact with
        samp_query (str): The query for the sample calculation
        pop_query (str): The query for the population calculation
        data_model (DataModel): The data model corresponding to the feature provided
        write_database (str): The database that the query will write tables to
        write_schema (str): The schema that the query will write tables to
        feature (str): The feature for which calculations are being executed
        granularity_levels (List[str]): The query names of the categorical features corresponding to the level of
                                        granularity desired in the numeric feature passed
        if_exists (enums.PandasTableExistsActionType): The default action that the query takes when creating
                                                       a table with a preexisting name
        samp (bool): Whether or not a sample calculation is being calculated

    Returns:
        float: The output of the calculation
    """
    from atscale.utils.eda_utils import (
        _construct_and_submit_base_table_query,
        _generate_base_table_name,
    )

    base_table_name = _generate_base_table_name()
    three_part_name = f"{write_database}.{write_schema}.{base_table_name}"

    _construct_and_submit_base_table_query(
        dbconn=dbconn,
        data_model=data_model,
        base_table_name=three_part_name,
        numeric_features=[feature],
        granularity_levels=granularity_levels,
        if_exists=if_exists,
    )

    if samp:
        q = dbconn.submit_query(samp_query.format(feature, three_part_name))
    else:
        q = dbconn.submit_query(pop_query.format(feature, three_part_name))

    dbconn.submit_query(f"drop table {three_part_name}; ")

    return q


def _construct_submit_return_warehouse_stats_two_feat(
    dbconn: SQLConnection,
    samp_query: str,
    pop_query: str,
    data_model: "DataModel",
    write_database: str,
    write_schema: str,
    feature1: str,
    feature2: str,
    granularity_levels: List[str],
    if_exists: enums.PandasTableExistsActionType,
    samp: bool = True,
):
    """Constructs and submits a stats query concerning two features.

    Args:
        dbconn (SQLConnection): The database connection that the query will interact with
        samp_query (str): The query for the sample calculation
        pop_query (str): The query for the population calculation
        data_model (DataModel): The data model corresponding to the features provided
        write_database (str): The database that the query will write tables to
        write_schema (str): The schema that the query will write tables to
        feature (str): The feature for which calculations are being executed
        granularity_levels (List[str]): The query names of the categorical features corresponding to the level of
                                        granularity desired in the numeric features passed
        if_exists (enums.PandasTableExistsActionType): The default action that the query takes when creating
                                                       a table with a preexisting name
        samp (bool): Whether or not a sample calculation is being calculated

    Returns:
        float: The output of the calculation
    """
    from atscale.utils.eda_utils import (
        _construct_and_submit_base_table_query,
        _generate_base_table_name,
    )

    base_table_name = _generate_base_table_name()
    three_part_name = f"{write_database}.{write_schema}.{base_table_name}"

    _construct_and_submit_base_table_query(
        dbconn=dbconn,
        data_model=data_model,
        base_table_name=three_part_name,
        numeric_features=[feature1, feature2],
        granularity_levels=granularity_levels,
        if_exists=if_exists,
    )

    if samp:
        q = dbconn.submit_query(samp_query.format(feature1, feature2, three_part_name))
    else:
        q = dbconn.submit_query(pop_query.format(feature1, feature2, three_part_name))

    dbconn.submit_query(f"drop table {three_part_name}; ")

    return q
