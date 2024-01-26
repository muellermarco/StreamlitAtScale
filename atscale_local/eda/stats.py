from atscale.db.sql_connection import SQLConnection
from atscale.data_model.data_model import DataModel
from atscale.utils.eda_utils import _stats_checks
from atscale.base.enums import PandasTableExistsActionType
from typing import List
import logging
from inspect import getfullargspec
from atscale.utils.validation_utils import validate_by_type_hints


logger = logging.getLogger(__name__)


def variance(
    dbconn: SQLConnection,
    data_model: DataModel,
    feature: str,
    granularity_levels: List[str],
    sample: bool = True,
    if_exists: PandasTableExistsActionType = PandasTableExistsActionType.FAIL,
    write_database: str = None,
    write_schema: str = None,
) -> float:
    """Returns the variance of a given feature.

    Args:
        dbconn (SQLConnection): The database connection to interact with.
        data_model (DataModel): The data model corresponding to the features provided.
        feature (str): The feature whose variance is calculated.
        granularity_levels (List[str]): The categorical features corresponding to the level of
                                        granularity desired in the given feature.
        sample (bool, optional): Whether to calculate the sample variance. Defaults to True; otherwise,
                                 calculates the population variance.
        if_exists (PandasTableExistsActionType, optional): The default action that taken when creating
                                                           a table with a preexisting name. Does not accept APPEND. Defaults to FAIL.
        write_database (str): The database that this functionality will write tables to. Defaults to the database associated with the
                              given dbconn.
        write_schema (str): The schema that this functionality will write tables to. Defaults to the database associated with the
                            given dbconn.

    Returns:
        float: The feature's variance.
    """
    inspection = getfullargspec(variance)
    validate_by_type_hints(inspection=inspection, func_params=locals())

    # Error checks
    _stats_checks(
        dbconn=dbconn,
        data_model=data_model,
        feature_list=[feature],
        granularity_levels=granularity_levels,
    )

    if not write_database:
        write_database = dbconn._database

    if not write_schema:
        write_schema = dbconn._schema

    return dbconn._warehouse_variance(
        data_model=data_model,
        write_database=write_database,
        write_schema=write_schema,
        feature=feature,
        granularity_levels=granularity_levels,
        if_exists=if_exists,
        samp=sample,
    )


def covariance(
    dbconn: SQLConnection,
    data_model: DataModel,
    feature1: str,
    feature2: str,
    granularity_levels: List[str],
    sample: bool = True,
    if_exists: PandasTableExistsActionType = PandasTableExistsActionType.FAIL,
    write_database: str = None,
    write_schema: str = None,
) -> float:
    """Returns the covariance of two given features.

    Args:
        dbconn (SQLConnection): The database connection to interact with.
        data_model (DataModel): The data model corresponding to the features provided.
        feature1 (str): The first feature.
        fearure2 (str): The second feature.
        granularity_levels (List[str]): The categorical features corresponding to the level of
                                  granularity desired in the given features.
        sample (bool, optional): Whether to calculate the sample covariance. Defaults to True; otherwise,
                                 calculates the population covariance.
        if_exists (PandasTableExistsActionType, optional): The default action that taken when creating
                                                           a table with a preexisting name. Does not accept APPEND. Defaults to FAIL.
        write_database (str): The database that this functionality will write tables to. Defaults to the database associated with the
                              given dbconn.
        write_schema (str): The schema that this functionality will write tables to. Defaults to the database associated with the
                            given dbconn.

    Returns:
        float: The features' covariance.
    """
    inspection = getfullargspec(covariance)
    validate_by_type_hints(inspection=inspection, func_params=locals())

    # Error checks
    _stats_checks(
        dbconn=dbconn,
        data_model=data_model,
        feature_list=[feature1, feature2],
        granularity_levels=granularity_levels,
    )

    if not write_database:
        write_database = dbconn._database

    if not write_schema:
        write_schema = dbconn._schema

    return dbconn._warehouse_covariance(
        data_model=data_model,
        write_database=write_database,
        write_schema=write_schema,
        feature_1=feature1,
        feature_2=feature2,
        granularity_levels=granularity_levels,
        if_exists=if_exists,
        samp=sample,
    )


def std(
    dbconn: SQLConnection,
    data_model: DataModel,
    feature: str,
    granularity_levels: List[str],
    sample: bool = True,
    if_exists: PandasTableExistsActionType = PandasTableExistsActionType.FAIL,
    write_database: str = None,
    write_schema: str = None,
) -> float:
    """Returns the standard deviation of a given feature.

    Args:
        dbconn (SQLConnection): The database connection to interact with.
        data_model (DataModel): The data model corresponding to the features provided.
        feature (str): The feature whose standard deviation is calculated.
        granularity_levels (List[str]): The categorical features corresponding to the level of
                                  granularity desired in the given feature.
        sample (bool, optional): Whether to calculate the sample standard deviation. Defaults to True;
                                 otherwise, calculates the population standard deviation.
        if_exists (PandasTableExistsActionType, optional): The default action that taken when creating
                                                           a table with a preexisting name. Does not accept APPEND. Defaults to FAIL.
        write_database (str): The database that this functionality will write tables to. Defaults to the database associated with the
                              given dbconn.
        write_schema (str): The schema that this functionality will write tables to. Defaults to the database associated with the
                            given dbconn.

    Returns:
        float: The feature's standard deviation.
    """
    inspection = getfullargspec(std)
    validate_by_type_hints(inspection=inspection, func_params=locals())

    # Error checks
    _stats_checks(
        dbconn=dbconn,
        data_model=data_model,
        feature_list=[feature],
        granularity_levels=granularity_levels,
    )

    if not write_database:
        write_database = dbconn._database

    if not write_schema:
        write_schema = dbconn._schema

    return dbconn._warehouse_std(
        data_model=data_model,
        write_database=write_database,
        write_schema=write_schema,
        feature=feature,
        granularity_levels=granularity_levels,
        if_exists=if_exists,
        samp=sample,
    )


def corrcoef(
    dbconn: SQLConnection,
    data_model: DataModel,
    feature1: str,
    feature2: str,
    granularity_levels: List[str],
    if_exists: PandasTableExistsActionType = PandasTableExistsActionType.FAIL,
    write_database: str = None,
    write_schema: str = None,
) -> float:
    """Returns the correlation of two given features.

    Args:
        dbconn (SQLConnection): The database connection to interact with.
        data_model (DataModel): The data model corresponding to the features provided.
        feature1 (str): The first feature.
        fearure2 (str): The second feature.
        granularity_levels (List[str]): The categorical features corresponding to the level of
                                        granularity desired in the given features.
        if_exists (PandasTableExistsActionType, optional): The default action that taken when creating
                                                           a table with a preexisting name. Does not accept APPEND. Defaults to FAIL.
        write_database (str): The database that this functionality will write tables to. Defaults to the database associated with the
                              given dbconn.
        write_schema (str): The schema that this functionality will write tables to. Defaults to the database associated with the
                            given dbconn.

    Returns:
        float: The features' correlation.
    """
    inspection = getfullargspec(corrcoef)
    validate_by_type_hints(inspection=inspection, func_params=locals())

    # Error checks
    _stats_checks(
        dbconn=dbconn,
        data_model=data_model,
        feature_list=[feature1, feature2],
        granularity_levels=granularity_levels,
    )

    if not write_database:
        write_database = dbconn._database

    if not write_schema:
        write_schema = dbconn._schema

    return dbconn._warehouse_corrcoef(
        data_model=data_model,
        write_database=write_database,
        write_schema=write_schema,
        feature_1=feature1,
        feature_2=feature2,
        granularity_levels=granularity_levels,
        if_exists=if_exists,
    )
