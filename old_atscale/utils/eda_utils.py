from typing import List
from re import search
import random
import string
import logging

from atscale.db.connections import databricks, snowflake
from atscale.errors import atscale_errors
from atscale.base import enums
from atscale.parsers import dictionary_parser
from atscale.utils import query_utils, model_utils, validation_utils
from atscale.db.sql_connection import SQLConnection
from atscale.data_model import DataModel, data_model_helpers


logger = logging.getLogger(__name__)


def _eda_check(
    data_model: DataModel,
    numeric_features: List[str],
    granularity_levels: List[str],
    if_exists: enums.TableExistsAction,
):
    """Implements common checks across our EDA functionality

    Args:
        data_model (DataModel): The data model corresponding to the features provided
        numeric_features (List[str]): The query names of the numeric features corresponding to the EDA inputs
        granularity_levels (List[str]): The query names of the categorical features corresponding to the level of
                                        granularity desired in numeric_features
        if_exists (enums.TableExistsAction): The default action the function takes when creating
                                        process tables that already exist. Does not accept APPEND or IGNORE. Defaults to ERROR.
    """
    # make sure the user inputs a valid action type
    if if_exists in [enums.TableExistsAction.APPEND, enums.TableExistsAction.IGNORE]:
        raise ValueError(
            f"The ActionType provided is not valid for this function; only REPLACE AND FAIL are valid."
        )

    proj_dict = data_model.project._get_dict()
    all_features_info = data_model_helpers._get_draft_features(
        proj_dict, data_model_name=data_model.name
    )
    all_numeric_features = dictionary_parser.filter_dict(
        to_filter=all_features_info,
        val_filters=[lambda i: i["feature_type"] == enums.FeatureType.NUMERIC.name_val],
    )
    all_categorical_features = dictionary_parser.filter_dict(
        to_filter=all_features_info,
        val_filters=[lambda i: i["feature_type"] == enums.FeatureType.CATEGORICAL.name_val],
    )

    # Error checking
    ### Check that features exist in the given DataModel in the first place
    model_utils._check_features(
        features=numeric_features + granularity_levels,
        check_list=all_features_info,
        errmsg=enums.CheckFeaturesErrMsg.ALL.get_errmsg(is_published=False),
    )

    ### Check that numeric/categorical features are in correct categories
    model_utils._check_features(
        features=numeric_features,
        check_list=all_numeric_features,
        errmsg=enums.CheckFeaturesErrMsg.NUMERIC.get_errmsg(is_published=False),
    )
    model_utils._check_features(
        features=granularity_levels,
        check_list=all_categorical_features,
        errmsg=enums.CheckFeaturesErrMsg.CATEGORICAL.get_errmsg(is_published=False),
    )

    # Make sure no duplicate features exist among those passed
    numeric_dupes_dict = validation_utils.validate_no_duplicates_in_list(numeric_features)
    cat_dupes_dict = validation_utils.validate_no_duplicates_in_list(granularity_levels)

    if numeric_dupes_dict != {}:
        raise ValueError(
            f"Duplicate features: {list(numeric_dupes_dict.keys())} passed via numeric_features"
        )

    if cat_dupes_dict != {}:
        raise ValueError(
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
    if_exists: enums.TableExistsAction,
):
    """Constructs and submits the base table query for EDA functionality

    Args:
        dbconn (SQLConnection): The database connection that the EDA function will interact with
        data_model (DataModel): The data model corresponding to the features provided
        base_table_name (str): The base table name for the EDA functionality
        numeric_features (List[str]): The query names of the numeric features corresponding to the EDA inputs
        granularity_levels (List[str]): The query names of the categorical features corresponding to the level of
                                        granularity desired in numeric_features
        if_exists (enums.TableExistsAction): The default action the function takes when creating
                                                 process tables that already exist. Does not accept APPEND. Defaults to ERROR.
    """
    base_table_atscale_query = query_utils._generate_db_query(
        data_model=data_model,
        atscale_query=query_utils._generate_atscale_query(
            data_model=data_model, feature_list=numeric_features + granularity_levels
        ),
    )
    base_table_query = f"CREATE TABLE {base_table_name} AS ({base_table_atscale_query}); "

    try:
        dbconn.submit_query(base_table_query)
    except Exception as e:
        err_msg = str(e)
        if "already exists." in err_msg:
            if if_exists == enums.TableExistsAction.OVERWRITE:
                dbconn.submit_query(f"DROP TABLE IF EXISTS {base_table_name}; ")
                dbconn.submit_query(base_table_query)
            else:
                table_name = search("Object (.*?) already exists", err_msg).group(1)
                raise atscale_errors.CollisionError(
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
        if_exists (enums.TableExistsAction): The default action the function takes when creating
                                                 process tables that already exist. Does not accept APPEND. Defaults to ERROR.
    """
    try:
        dbconn.execute_statements(statement_list=query_list)
    except Exception as e:
        err_msg = str(e)
        if "already exists." in err_msg:
            # Initial drops if REPLACE, then run off of base table
            if if_exists == enums.TableExistsAction.OVERWRITE:
                dbconn.execute_statements(statement_list=drop_list)
                try:
                    dbconn.execute_statements(statement_list=query_list)
                except Exception as e:
                    raise e
            elif if_exists == enums.TableExistsAction.ERROR:
                table_name = search("Object (.*?) already exists", err_msg).group(1)
                raise atscale_errors.CollisionError(
                    f"A table already exists with name: {table_name}. Name collisions between runs are rare "
                    f"but can happen. You can avoid this error by setting if_exists to REPLACE"
                )
        # Constant-valued features will create a divide by zero error in the case of PCA
        elif "Division by zero" in err_msg:
            # Drop any tables created prior to error firing
            dbconn.execute_statements(statement_list=drop_list)
            dbconn.submit_query(f"DROP TABLE IF EXISTS {base_table_name}; ")
            raise ValueError("Make sure no constant-valued features are passed to pca")

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
    if_exists: enums.TableExistsAction = enums.TableExistsAction.ERROR,
) -> None:
    """Wrapper to minimize db connections when below functions are called
    dbconn (SQLConnection): The database connection to interact with.
    data_model (DataModel): The data model corresponding to the features provided.
    write_database (str): The database that the functionality will write tables to
    write_schema (str): The schema that the functionality will write tables to
    stats_obj (_Stats): Stores variance and covariance values for a given connection.
    sample (bool, optional): Whether to calculate the sample variance. Defaults to True; otherwise,
                            calculates the population variance.
    if_exists (enums.TableExistsAction, optional): The default action that taken when creating
                            a table with a preexisting name. Does not accept APPEND and IGNORE. Defaults to ERROR.
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
            raise ValueError(
                f'query_key: "{query_key}" is invalid. Valid options are "var" and "cov".'
            )

    # Drop base table
    dbconn.submit_query(f"DROP TABLE {three_part_name};")


def _stats_checks(
    dbconn: SQLConnection,
    data_model: DataModel,
    feature_list: List[str],
    granularity_levels: List[str],
    if_exists: enums.TableExistsAction = enums.TableExistsAction.ERROR,
):
    """Runs checks on parameters passed to the below functions.
    Args:
        dbconn (SQLConnection): The database connection to interact with.
        data_model (DataModel): The data model corresponding to the features provided.
        feature_list (List[str]): The feature(s) involved in the calculation.
        granularity_levels (List[str]): The categorical features corresponding to the level of
                                        granularity desired in the given feature.
        if_exists (enums.TableExistsAction): The default action that taken when creating
                                        a table with a preexisting name. Does not accept APPEND or IGNORE. Defaults to ERROR.
    """
    if not (isinstance(dbconn, snowflake.Snowflake) or isinstance(dbconn, databricks.Databricks)):
        raise atscale_errors.UnsupportedOperationException(
            f"This function is only supported for Snowflake and Databricks at this time."
        )

    if if_exists in [enums.TableExistsAction.APPEND, enums.TableExistsAction.IGNORE]:
        raise ValueError(
            f"The ActionType provided is not supported, only REPLACE AND FAIL are valid."
        )

    proj_dict = data_model.project._get_dict()
    all_features_info = data_model_helpers._get_draft_features(
        proj_dict, data_model_name=data_model.name
    )
    all_numeric_features = dictionary_parser.filter_dict(
        to_filter=all_features_info,
        val_filters=[lambda i: i["feature_type"] == enums.FeatureType.NUMERIC.name_val],
    )
    all_categorical_features = dictionary_parser.filter_dict(
        to_filter=all_features_info,
        val_filters=[lambda i: i["feature_type"] == enums.FeatureType.CATEGORICAL.name_val],
    )

    # Check that features exist in the given DataModel in the first place
    model_utils._check_features(
        features=feature_list + granularity_levels,
        check_list=all_features_info,
        errmsg=enums.CheckFeaturesErrMsg.ALL.get_errmsg(is_published=False),
    )

    # Check that numeric/categorical features are in correct categories
    model_utils._check_features(
        features=feature_list,
        check_list=all_numeric_features,
        errmsg=enums.CheckFeaturesErrMsg.NUMERIC.get_errmsg(is_published=False),
    )

    model_utils._check_features(
        features=granularity_levels,
        check_list=all_categorical_features,
        errmsg=enums.CheckFeaturesErrMsg.CATEGORICAL.get_errmsg(is_published=False),
    )
