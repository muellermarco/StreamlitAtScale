import logging
from math import e
from typing import List

from atscale.errors import atscale_errors
from atscale.base import enums
from atscale.data_model.data_model import DataModel, data_model_helpers
from atscale.utils import feature_utils, project_utils, query_utils
from atscale.utils import dmv_utils, model_utils, validation_utils
from atscale.parsers import dataset_parser

logger = logging.getLogger(__name__)


def _write_regression_model_checks(
    model_type: enums.ScikitLearnModelType,
    data_model: DataModel,
    regression_model,
    new_feature_name: str,
    granularity_levels: List[str],
    feature_inputs: List[str],
):
    """A helper function for writing regression models to AtScale.

    Args:
        model_type (enums.enums.ScikitLearnModelType): the type of scikit-learn model being written to AtScale.
        data_model (DataModel): The AtScale DataModel to add the regression into.
        regression_model (LinearRegression): The scikit-learn LinearRegression model to build into a feature.
        new_feature_name (str): The name of the created feature.
    """
    model_failure = False
    # TODO at some point we may want to generalize this and remove the enum so we can take any model object and just check it is a type we support.
    # if not isinstance(regression_model, sklearn.linear_model.LinearRegression) and not isinstance(regression_model, sklearn.linear_model.LogisticRegression):
    # raise atscale_errors.WorkFlowError(
    #        f"The model object of type: {type(regression_model)} is not compatible with this method "
    #        f"which takes an object of type sklearn.linear_model.LinearRegression or sklearn.linear_model.LogisticRegression"
    #    )
    #

    if model_type == enums.ScikitLearnModelType.LINEARREGRESSION:
        if type(regression_model).__name__ not in ["LinearRegression"]:
            model_failure = True
    elif model_type == enums.ScikitLearnModelType.LOGISTICREGRESSION:
        if type(regression_model).__name__ not in ["LogisticRegression"]:
            model_failure = True

    if model_failure:
        raise atscale_errors.WorkFlowError(
            f"The model object of type: {type(regression_model)} is not compatible with this method "
            f"which takes an object of type sklearn.linear_model.{model_type.value}"
        )

    try:
        import sklearn
    except ImportError:
        raise ImportError(
            "scikit-learn needs to be installed to use this functionality, the function takes an "
            f"sklearn.linear_model.{model_type.value} object. Try running pip install scikit-learn"
        )

    model_failure = False

    if model_type == enums.ScikitLearnModelType.LINEARREGRESSION:
        if not isinstance(regression_model, sklearn.linear_model.LinearRegression):
            model_failure = True
    elif model_type == enums.ScikitLearnModelType.LOGISTICREGRESSION:
        if not isinstance(regression_model, sklearn.linear_model.LogisticRegression):
            model_failure = True

    if model_failure:
        raise atscale_errors.WorkFlowError(
            f"The model object of type: {type(regression_model)} is not compatible with this method "
            f"which takes an object of type sklearn.linear_model.{model_type.value}"
        )

    feature_list = []
    if feature_inputs:
        feature_list = feature_inputs
    else:
        feature_inputs = list(regression_model.feature_names_in_)
    if granularity_levels:
        feature_list = feature_list + granularity_levels
    if feature_list:
        model_utils._check_features(
            features=feature_list,
            check_list=list(data_model.get_features(use_published=True).keys()),
            errmsg=enums.CheckFeaturesErrMsg.ALL.get_errmsg(is_published=True),
        )

    model_utils._check_conflicts(to_add=new_feature_name, data_model=data_model)


def _write_regression_model(
    model_type: enums.ScikitLearnModelType,
    data_model: DataModel,
    regression_model,
    new_feature_name: str,
    feature_inputs: List[str],
    granularity_levels: List[str],
):
    """A helper function for writing regression models to AtScale.

    Args:
        model_type (enums.enums.ScikitLearnModelType): the type of scikit-learn model being written to AtScale.
        data_model (DataModel): The AtScale DataModel to add the regression into.
        regression_model (sklearn.linear_model): The scikit-learn linear model to build into a feature.
        new_feature_name (str): The name of the created feature.
        feature_inputs (List[str], optional): List of names of inputs features in the input order.
            Defaults to None to use the column names used when training the model.
        granularity_levels (List[str], optional): List of lowest categorical levels that predictions with this
            model can be run on. Defaults to False to use the lowest level from each hierarchy.
    """
    _write_regression_model_checks(
        model_type,
        data_model,
        regression_model,
        new_feature_name,
        feature_inputs,
        granularity_levels,
    )

    if granularity_levels is None or granularity_levels == []:
        feature_dict = data_model.get_features(feature_type=enums.FeatureType.CATEGORICAL)
        leaf_levels = []
        hierarchy_to_levels = dmv_utils.get_dmv_data(
            model=data_model,
            id_field=enums.Level.hierarchy,
            fields=[enums.Level.name, enums.Level.level_number],
        )
        for levels in hierarchy_to_levels.values():
            if type(levels["name"]) == list:
                leaf_levels.append(levels["name"][-1])
            elif not feature_dict[levels["name"]]["secondary_attribute"]:
                leaf_levels.append(levels["name"])
        granularity_levels = leaf_levels

    if feature_inputs is None:
        feature_inputs = list(regression_model.feature_names_in_)

    atscale_query: str = query_utils._generate_atscale_query(
        data_model=data_model, feature_list=feature_inputs + granularity_levels
    )
    feature_query: str = query_utils._generate_db_query(
        data_model=data_model, atscale_query=atscale_query, use_aggs=False
    )

    categorical_string: str = ", ".join(f'"{cat}"' for cat in granularity_levels)
    numeric = " + ".join(
        [
            f'{theta1}*"{x}"'
            for theta1, x in zip(regression_model.coef_[0], regression_model.feature_names_in_)
        ]
    )
    numeric += f" + {regression_model.intercept_[0]}"
    if model_type == enums.ScikitLearnModelType.LINEARREGRESSION:
        qds_query: str = f'SELECT ({numeric}) as "{new_feature_name}"{", " if categorical_string else ""}{categorical_string} FROM ({feature_query})'
    elif model_type == enums.ScikitLearnModelType.LOGISTICREGRESSION:
        qds_query: str = f'SELECT ROUND(1 - 1 / (1 + POWER({e}, {numeric})), 0) as "{new_feature_name}" , {categorical_string} FROM ({feature_query})'

    dataset_name = f"{new_feature_name}_QDS"

    project_dict = data_model.project._get_dict()
    warehouse_id = validation_utils._validate_warehouse_id_parameter(
        atconn=data_model.project._atconn, project_dict=project_dict
    )
    columns = data_model.project._atconn._get_query_columns(
        warehouse_id=warehouse_id, query=qds_query
    )
    project_dataset, dataset_id = project_utils._create_query_dataset(
        project_dict=project_dict,
        name=dataset_name,
        query=qds_query,
        columns=columns,
        warehouse_id=warehouse_id,
        allow_aggregates=True,
    )

    roleplay_features = ["" for x in granularity_levels]
    dataset_columns: List[dataset_parser.Column] = dataset_parser.Dataset(project_dataset).columns
    column_set = {c.name for c in dataset_columns}
    join_columns: List[List[str]] = data_model_helpers._prep_join_columns_for_join(
        join_columns=granularity_levels, atscale_columns=column_set
    )

    model_utils._create_dataset_relationship_from_dataset(
        project_dict=project_dict,
        cube_id=data_model.cube_id,
        dataset_name=dataset_name,
        join_features=granularity_levels,
        join_columns=join_columns,
        roleplay_features=roleplay_features,
    )

    feature_utils._create_aggregate_feature(
        project_dict=project_dict,
        cube_id=data_model.cube_id,
        dataset_id=dataset_id,
        column_name=new_feature_name,
        new_feature_name=new_feature_name,
        aggregation_type=enums.Aggs.SUM,
    )
    data_model.project._update_project(project_dict=project_dict, publish=True)


def _snowpark_udf_call(
    udf_name: str,
    feature_inputs: List[str],
):
    inputs = ", ".join(f'"{f}"' for f in feature_inputs)
    return f"{udf_name}(array_construct({inputs}))"
