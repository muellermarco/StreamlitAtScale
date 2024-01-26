from atscale.errors.atscale_errors import EDAException, UserError, UnsupportedOperationException
from atscale.base.enums import PandasTableExistsActionType
from atscale.base.enums import PandasTableExistsActionType, CheckFeaturesErrMsg, FeatureType
from atscale.utils.query_utils import _generate_atscale_query, _generate_db_query
from atscale.utils.model_utils import _check_features
from atscale.db.sql_connection import SQLConnection
from atscale.data_model import DataModel
from atscale.utils.validation_utils import validate_no_duplicates_in_list
from atscale.utils.metadata_utils import (
    _get_all_numeric_feature_names,
    _get_all_categorical_feature_names,
)
from atscale.data_model.data_model_helpers import _get_draft_features
from atscale.base.enums import PlatformType, FeatureType
from typing import List
from re import search
import random
import string
import logging


logger = logging.getLogger(__name__)


def _eda_check(
    data_model: DataModel,
    numeric_features: List[str],
    granularity_levels: List[str],
    if_exists: PandasTableExistsActionType,
):
    """Implements common checks across our EDA functionality

    Args:
        data_model (DataModel): The data model corresponding to the features provided
        numeric_features (List[str]): The query names of the numeric features corresponding to the EDA inputs
        granularity_levels (List[str]): The query names of the categorical features corresponding to the level of
                                        granularity desired in numeric_features
        if_exists (PandasTableExistsActionType): The default action the function takes when creating
                                                 process tables that already exist. Does not accept APPEND. Defaults to FAIL.

    Raises:
        UserError: Functionality only currently supported for Snowflake
        UserError: Only REPLACE and FAIL are valid PandasTableExistsActionTypes
    """
    # make sure the user inputs a valid action type
    if if_exists == PandasTableExistsActionType.APPEND:
        raise UserError(
            f"The ActionType of APPEND is not valid for this function; only REPLACE AND FAIL are valid."
        )

    proj_dict = data_model.project._get_dict()

    all_numeric_features = list(
        _get_draft_features(
            project_dict=proj_dict,
            data_model_name=data_model.name,
            feature_type=FeatureType.NUMERIC,
        ).keys()
    )

    all_categorical_features = list(
        _get_draft_features(
            project_dict=proj_dict,
            data_model_name=data_model.name,
            feature_type=FeatureType.CATEGORICAL,
        ).keys()
    )

    # Error checking
    ### Check that features exist in the given DataModel in the first place
    _check_features(
        features=numeric_features + granularity_levels,
        check_list=all_numeric_features + all_categorical_features,
        errmsg=CheckFeaturesErrMsg.ALL.get_errmsg(is_published=False),
    )

    ### Check that numeric/categorical features are in correct categories
    _check_features(
        features=numeric_features,
        check_list=all_numeric_features,
        errmsg=CheckFeaturesErrMsg.NUMERIC.get_errmsg(is_published=False),
    )
    _check_features(
        features=granularity_levels,
        check_list=all_categorical_features,
        errmsg=CheckFeaturesErrMsg.CATEGORICAL.get_errmsg(is_published=False),
    )

    # Make sure no duplicate features exist among those passed
    numeric_dupes_dict = validate_no_duplicates_in_list(numeric_features)
    cat_dupes_dict = validate_no_duplicates_in_list(granularity_levels)

    if numeric_dupes_dict != {}:
        raise UserError(
            f"Duplicate features: {list(numeric_dupes_dict.keys())} passed via numeric_features"
        )

    if cat_dupes_dict != {}:
        raise UserError(
            f"Duplicate features: {list(cat_dupes_dict.keys())} passed via granularity_levels"
        )


def _generate_base_table_name() -> str:
    """Generates a base table name for the EDA functionality

    Returns:
        str: The base table name generated
    """
    uuid_str = "".join(random.choice(string.ascii_lowercase + string.digits) for _ in range(6))
    base_table_name = f"atscale_eda_tbl_{uuid_str}"
    logger.info(f"generating temp eda tables: {base_table_name}")

    return base_table_name


def _construct_and_submit_base_table_query(
    dbconn: SQLConnection,
    data_model: DataModel,
    base_table_name: str,
    numeric_features: List[str],
    granularity_levels: List[str],
    if_exists: PandasTableExistsActionType,
):
    """Constructs and submits the base table query for EDA functionality

    Args:
        dbconn (SQLConnection): The database connection that the EDA function will interact with
        data_model (DataModel): The data model corresponding to the features provided
        base_table_name (str): The base table name for the EDA functionality
        numeric_features (List[str]): The query names of the numeric features corresponding to the EDA inputs
        granularity_levels (List[str]): The query names of the categorical features corresponding to the level of
                                        granularity desired in numeric_features
        if_exists (PandasTableExistsActionType): The default action the function takes when creating
                                                 process tables that already exist. Does not accept APPEND. Defaults to FAIL.

    Raises:
        UserError: Name collisiom
    """
    base_table_atscale_query = _generate_db_query(
        data_model=data_model,
        atscale_query=_generate_atscale_query(
            data_model=data_model, feature_list=numeric_features + granularity_levels
        ),
    )
    base_table_query = f"CREATE TABLE {base_table_name} AS ({base_table_atscale_query}); "

    try:
        dbconn.submit_query(base_table_query)
    except Exception as e:
        err_msg = str(e)
        if "already exists." in err_msg:
            if if_exists == PandasTableExistsActionType.REPLACE:
                try:
                    dbconn.submit_query(f"DROP TABLE IF EXISTS {base_table_name}; ")
                    dbconn.submit_query(base_table_query)
                except Exception as e:
                    raise e
            else:
                table_name = search("Object (.*?) already exists", err_msg).group(1)
                raise UserError(
                    f"A table already exists with name: {table_name}. Name collisions between runs are rare "
                    f"but can happen. You can avoid this error by setting if_exists to REPLACE"
                )
        else:
            raise e


def _execute_with_name_collision_handling(
    dbconn: SQLConnection,
    query_list: List[str],
    drop_list: List[str],
    base_table_name: str,
    if_exists: bool,
):
    """Executes a list of queries to run the EDA process with coverage for potential errors (detailed below)

    Args:
        dbconn (SQLConnection): The database connection that the EDA function will interact with
        query_list (List[str]): The list of queries to execute the EDA functionality
        drop_list (List[str]): The list of queries to drop process tables
        base_table_name (str): The base table name for the EDA functionality
        if_exists (PandasTableExistsActionType): The default action the function takes when creating
                                                 process tables that already exist. Does not accept APPEND. Defaults to FAIL.

    Raises:
        UserError: Name collision
        EDAException: Constant-valued feature passed; this is a problem for PCA
    """
    try:
        dbconn.execute_statements(statement_list=query_list)
    except Exception as e:
        err_msg = str(e)
        if "already exists." in err_msg:
            # Initial drops if REPLACE, then run off of base table
            if if_exists == PandasTableExistsActionType.REPLACE:
                dbconn.execute_statements(statement_list=drop_list)
                try:
                    dbconn.execute_statements(statement_list=query_list)
                except Exception as e:
                    raise e
            elif if_exists == PandasTableExistsActionType.FAIL:
                table_name = search("Object (.*?) already exists", err_msg).group(1)
                raise UserError(
                    f"A table already exists with name: {table_name}. Name collisions between runs are rare "
                    f"but can happen. You can avoid this error by setting if_exists to REPLACE"
                )
        # Constant-valued features will create a divide by zero error in the case of PCA
        elif "Division by zero" in err_msg:
            # Drop any tables created prior to error firing
            dbconn.execute_statements(statement_list=drop_list)
            dbconn.submit_query(f"DROP TABLE IF EXISTS {base_table_name}; ")
            raise EDAException("Make sure no constant-valued features are passed to pca")

        else:
            raise e


class _Stats:
    def __init__(self):
        self.base_table_granularity_levels = []
        self.base_table_numeric_features = set()
        self.query_dict = {
            "var": {},  # Populated with features as keys if variance is requested, None values –
            # these values to be set with actual variance
            "cov": None,  # Value set to list of two features if covariance is requested
        }


def _stats_connection_wrapper(
    dbconn: SQLConnection,
    data_model: DataModel,
    write_database: str,
    write_schema: str,
    stats_obj: _Stats,
    sample: bool = True,
    if_exists: PandasTableExistsActionType = PandasTableExistsActionType.FAIL,
) -> None:
    """Wrapper to minimize db connections when below functions are called
    dbconn (SQLConnection): The database connection to interact with.
    data_model (DataModel): The data model corresponding to the features provided.
    write_database (str): The database that the functionality will write tables to
    write_schema (str): The schema that the functionality will write tables to
    stats_obj (_Stats): Stores variance and covariance values for a given connection.
    sample (bool, optional): Whether to calculate the sample variance. Defaults to True; otherwise,
                            calculates the population variance.
    if_exists (PandasTableExistsActionType, optional): The default action that taken when creating
                                                    a table with a preexisting name. Does not accept APPEND. Defaults to FAIL.
    """
    base_table_name = _generate_base_table_name()
    three_part_name = f"{write_database}.{write_schema}.{base_table_name}"

    _construct_and_submit_base_table_query(
        dbconn=dbconn,
        data_model=data_model,
        base_table_name=three_part_name,
        numeric_features=list(stats_obj.base_table_numeric_features),
        granularity_levels=stats_obj.base_table_granularity_levels,
        if_exists=if_exists,
    )

    for query_key in stats_obj.query_dict:
        if query_key == "var":
            if stats_obj.query_dict[query_key] != {}:
                for var_key in stats_obj.query_dict[query_key]:
                    if sample:
                        var = (
                            f"SELECT (SELECT (1. / (COUNT({var_key}) - 1)) FROM {three_part_name}) * "
                            f"SUM(POWER((SELECT AVG({var_key}) FROM {three_part_name}) - {var_key}, 2)) "
                            f"FROM {three_part_name}; "
                        )
                    else:
                        var = (
                            f"SELECT (SELECT (1. / COUNT({var_key})) FROM {three_part_name}) * "
                            + f"SUM(POWER((SELECT AVG({var_key}) FROM {three_part_name}) - {var_key}, 2))"
                            + f"FROM {three_part_name}; "
                        )
                    stats_obj.query_dict[query_key][var_key] = dbconn.submit_query(var)

        elif query_key == "cov":
            if stats_obj.query_dict[query_key] is not None:
                fl = stats_obj.query_dict[query_key]
                f1 = fl[0]
                f2 = fl[1]
                if sample:
                    cov = (
                        f"SELECT (SELECT (1. / (COUNT(*) - 1)) FROM {three_part_name}) * SUM( "
                        + f"((SELECT AVG({f1}) FROM {three_part_name}) - {f1}) * "
                        + f"((SELECT AVG({f2}) FROM {three_part_name}) - {f2})) "
                        + f"FROM {three_part_name}; "
                    )

                else:
                    cov = (
                        f"SELECT (SELECT (1. / COUNT(*)) FROM {three_part_name}) * SUM( "
                        + f"((SELECT AVG({f1}) FROM {three_part_name}) - {f1}) * "
                        + f"((SELECT AVG({f2}) FROM {three_part_name}) - {f2})) "
                        + f"FROM {three_part_name}; "
                    )

                stats_obj.query_dict["cov"] = dbconn.submit_query(cov)

        else:
            raise EDAException(
                f'query_key: "{query_key}" is invalid. Valid options are "var" and "cov".'
            )

    # Drop base table
    dbconn.submit_query(f"DROP TABLE {three_part_name};")


def _stats_checks(
    dbconn: SQLConnection,
    data_model: DataModel,
    feature_list: List[str],
    granularity_levels: List[str],
    if_exists: PandasTableExistsActionType = PandasTableExistsActionType.FAIL,
) -> None:
    """Runs checks on parameters passed to the below functions.
    Args:
        dbconn (SQLConnection): The database connection to interact with.
        data_model (DataModel): The data model corresponding to the features provided.
        feature_list (List[str]): The feature(s) involved in the calculation.
        granularity_levels (List[str]): The categorical features corresponding to the level of
                                        granularity desired in the given feature.
        if_exists (PandasTableExistsActionType): The default action that taken when creating
                                                    a table with a preexisting name. Does not accept APPEND. Defaults to FAIL.

    Raises:
        UserError: Given dbconn must be to Snowflake or Databricks at this point.
        UserError: User can't select APPEND as an ActionType.

    Returns:
        None.
    """
    if (
        dbconn.platform_type != PlatformType.SNOWFLAKE
        and dbconn.platform_type != PlatformType.DATABRICKS
    ):
        raise UnsupportedOperationException(
            f"This function is only supported for Snowflake and Databricks at this time."
        )

    if if_exists == PandasTableExistsActionType.APPEND:
        raise UserError(
            f"The ActionType of APPEND is not valid for this function, only REPLACE AND FAIL are valid."
        )

    proj_dict = data_model.project._get_dict()

    all_numeric_features = list(
        _get_draft_features(
            project_dict=proj_dict,
            data_model_name=data_model.name,
            feature_type=FeatureType.NUMERIC,
        ).keys()
    )

    all_categorical_features = list(
        _get_draft_features(
            project_dict=proj_dict,
            data_model_name=data_model.name,
            feature_type=FeatureType.CATEGORICAL,
        ).keys()
    )

    # Check that features exist in the given DataModel in the first place
    _check_features(
        features=feature_list + granularity_levels,
        check_list=all_numeric_features + all_categorical_features,
        errmsg=CheckFeaturesErrMsg.ALL.get_errmsg(is_published=False),
    )

    # Check that numeric/categorical features are in correct categories
    _check_features(
        features=feature_list,
        check_list=all_numeric_features,
        errmsg=CheckFeaturesErrMsg.NUMERIC.get_errmsg(is_published=False),
    )

    _check_features(
        features=granularity_levels,
        check_list=all_categorical_features,
        errmsg=CheckFeaturesErrMsg.CATEGORICAL.get_errmsg(is_published=False),
    )
