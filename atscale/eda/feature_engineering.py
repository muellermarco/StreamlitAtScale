import copy
import logging
from typing import List, Union, Dict
from inspect import getfullargspec
from pandas import DataFrame

from atscale.data_model.data_model import DataModel
from atscale.base import enums
from atscale.db.sql_connection import SQLConnection
from atscale.errors import atscale_errors
from atscale.utils import query_utils, validation_utils, model_utils
from atscale.utils import prediction_utils, feature_utils, project_utils
from atscale.utils import dmv_utils, metadata_utils
from atscale.project import project_helpers
from atscale.parsers import dictionary_parser, project_parser
from atscale.data_model import data_model_helpers

logger = logging.getLogger(__name__)


def create_one_hot_encoded_features(
    data_model: DataModel,
    categorical_feature: str,
    hierarchy_name: str = None,
    description: str = None,
    folder: str = None,
    format_string: Union[enums.FeatureFormattingType, str] = None,
    publish: bool = True,
) -> List[str]:
    """Creates a one hot encoded feature for each value in the given categorical feature. Works off of the published project.

    Args:
        data_model (DataModel): The data model to add the features to.
        categorical_feature (str): The query name of the categorical feature to pull the values from.
        hierarchy_name (str, optional): The query name of the hierarchy to use for the feature. Only necessary if the feature is duplicated in multiple hierarchies.
        description (str, optional): A description to add to the new features. Defaults to None.
        folder (str, optional): The folder to put the new features in. Defaults to None.
        format_string (Union[enums.FeatureFormattingType, str], optional): A format sting for the new features. Defaults to None.
        publish (bool, optional): Whether to publish the project after creating the features. Defaults to True.

    Returns:
        List[str]: The query names of the newly created features
    """
    # check if the provided data_model is a perspective
    model_utils._perspective_check(data_model)

    inspection = getfullargspec(create_one_hot_encoded_features)
    validation_utils.validate_by_type_hints(inspection=inspection, func_params=locals())

    # check that we are using a published project
    project_helpers._check_published(data_model.project)

    project_dict = data_model.project._get_dict()
    draft_features = data_model_helpers._get_draft_features(
        project_dict=project_dict,
        data_model_name=data_model.name,
        feature_type=enums.FeatureType.ALL,
    )

    # Check to see that features passed exist in first place
    model_utils._check_features(
        features=[categorical_feature],
        check_list=draft_features,
        errmsg=enums.CheckFeaturesErrMsg.ALL.get_errmsg(is_published=True),
    )

    # Check to see that features passed are categorical
    draft_measures = dictionary_parser.filter_dict(
        to_filter=draft_features,
        val_filters=[lambda i: i["feature_type"] == enums.FeatureType.CATEGORICAL.name_val],
    )

    model_utils._check_features(
        features=[categorical_feature],
        check_list=draft_measures,
        errmsg=enums.CheckFeaturesErrMsg.CATEGORICAL.get_errmsg(is_published=True),
    )

    filter_by = {enums.Level.name: [categorical_feature]}
    if hierarchy_name:
        # check hierarchy if applicable
        hier_dict, _ = feature_utils._check_hierarchy(
            data_model=data_model, hierarchy_name=hierarchy_name, level_name=categorical_feature
        )
        filter_by[enums.Level.hierarchy] = [hierarchy_name]
    level_heritage = dmv_utils.get_dmv_data(
        model=data_model, fields=[enums.Level.dimension, enums.Level.hierarchy], filter_by=filter_by
    )

    if len(level_heritage) == 0:
        raise atscale_errors.ObjectNotFoundError(
            f"Unable to determine dimension and hierarchy for level: {categorical_feature}"
        )
    dimension = level_heritage[categorical_feature][enums.Level.dimension.name]
    hierarchy = level_heritage[categorical_feature][enums.Level.hierarchy.name]
    df_values = data_model.get_data([categorical_feature], gen_aggs=False)
    project_dict = data_model.project._get_dict()
    original_proj_dict = copy.deepcopy(
        project_dict
    )  # need to check that the new names were free BEFORE adding them
    created_names = []
    for value in df_values[categorical_feature].values:
        expression = f'IIF(ANCESTOR([{dimension}].[{hierarchy}].CurrentMember, [{dimension}].[{hierarchy}].[{categorical_feature}]).MEMBER_NAME="{value}",1,0)'
        name = f"{categorical_feature}_{value}"
        created_names.append(name)
        feature_utils._create_calculated_feature(
            project_dict,
            data_model.cube_id,
            name,
            expression,
            description=description,
            caption=None,
            folder=folder,
            format_string=format_string,
        )

    model_utils._check_conflicts(
        to_add=created_names, data_model=data_model, project_dict=original_proj_dict
    )
    data_model.project._update_project(project_dict=project_dict, publish=publish)
    return created_names


def create_percent_change(
    data_model: DataModel,
    new_feature_name: str,
    numeric_feature_name: str,
    hierarchy_name: str,
    level_name: str,
    time_length: int,
    description: str = None,
    caption: str = None,
    folder: str = None,
    format_string: Union[enums.FeatureFormattingType, str] = None,
    visible: bool = True,
    publish: bool = True,
):
    """Creates a time over time calculation

    Args:
        data_model (DataModel): The DataModel that the feature will be written into
        new_feature_name (str): The query name of the new feature
        numeric_feature_name (str): The query name of the numeric feature to use for the calculation
        hierarchy_name (str): The query name of the time hierarchy used in the calculation
        level_name (str): The query name of the level within the time hierarchy
        time_length (int): The length of the lag
        description (str, optional): The description for the feature. Defaults to None.
        caption (str, optional): The caption for the feature. Defaults to None.
        folder (str, optional): The folder to put the feature in. Defaults to None.
        format_string (Union[enums.FeatureFormattingType, str], optional): The format string for the feature. Defaults to None.
        visible (bool, optional): Whether the feature will be visible to BI tools. Defaults to True.
        publish (bool, optional): Whether or not the updated project should be published. Defaults to True.
    """
    # check if the provided data_model is a perspective
    model_utils._perspective_check(data_model)

    inspection = getfullargspec(create_percent_change)
    validation_utils.validate_by_type_hints(inspection=inspection, func_params=locals())

    proj_dict = data_model.project._get_dict()

    all_features_info = data_model_helpers._get_draft_features(
        proj_dict, data_model_name=data_model.name
    )
    numeric_features_info = dictionary_parser.filter_dict(
        to_filter=all_features_info,
        val_filters=[lambda i: i["feature_type"] == enums.FeatureType.NUMERIC.name_val],
    )

    # Check to see that features passed exist in first place
    model_utils._check_features(
        features=[numeric_feature_name],
        check_list=all_features_info,
        errmsg=enums.CheckFeaturesErrMsg.ALL.get_errmsg(is_published=False),
    )

    # Check to see that features passed are numeric
    model_utils._check_features(
        features=[numeric_feature_name],
        check_list=numeric_features_info,
        errmsg=enums.CheckFeaturesErrMsg.NUMERIC.get_errmsg(is_published=False),
    )

    if not (type(time_length) == int) or time_length <= 0:
        raise ValueError(
            f"Invalid parameter value '{time_length}', Length must be an integer greater than zero"
        )

    hier_dict, _ = feature_utils._check_time_hierarchy(
        data_model=data_model, hierarchy_name=hierarchy_name, level_name=level_name
    )

    time_dimension = hier_dict["dimension"]

    expression = (
        f"CASE WHEN IsEmpty((ParallelPeriod([{time_dimension}].[{hierarchy_name}].[{level_name}], {time_length}"
        f", [{time_dimension}].[{hierarchy_name}].CurrentMember), [Measures].[{numeric_feature_name}])) "
        f"THEN 0 ELSE ([Measures].[{numeric_feature_name}]"
        f"/(ParallelPeriod([{time_dimension}].[{hierarchy_name}].[{level_name}], {time_length}"
        f", [{time_dimension}].[{hierarchy_name}].CurrentMember), [Measures].[{numeric_feature_name}]) - 1) END"
    )
    data_model.create_calculated_feature(
        new_feature_name,
        expression,
        description=description,
        caption=caption,
        folder=folder,
        format_string=format_string,
        visible=visible,
        publish=publish,
    )


def create_period_to_date(
    data_model: DataModel,
    new_feature_name: str,
    numeric_feature_name: str,
    hierarchy_name: str,
    level_name: str,
    description: str = None,
    caption: str = None,
    folder: str = None,
    format_string: Union[enums.FeatureFormattingType, str] = None,
    visible: bool = True,
    publish: bool = True,
):
    """Creates a period-to-date calculation

    Args:
        data_model (DataModel): The DataModel that the feature will be written into
        new_feature_name (str): The query name of the new feature
        numeric_feature_name (str): The query name of the numeric feature to use for the calculation
        hierarchy_name (str): The query name of the time hierarchy used in the calculation
        level_name (str): The query name of the level within the time hierarchy
        description (str, optional): The description for the feature. Defaults to None.
        caption (str, optional): The caption for the feature. Defaults to None.
        folder (str, optional): The folder to put the feature in. Defaults to None.
        format_string (Union[enums.FeatureFormattingType, str], optional): The format string for the feature. Defaults to None.
        visible (bool, optional): Whether the feature will be visible to BI tools. Defaults to True.
        publish (bool, optional): Whether or not the updated project should be published. Defaults to True.
    """
    # check if the provided data_model is a perspective
    model_utils._perspective_check(data_model)

    inspection = getfullargspec(create_period_to_date)
    validation_utils.validate_by_type_hints(inspection=inspection, func_params=locals())

    project_dict = data_model.project._get_dict()
    existing_features = data_model_helpers._get_draft_features(
        project_dict=project_dict, data_model_name=data_model.name
    )
    existing_measures = dictionary_parser.filter_dict(
        to_filter=existing_features,
        val_filters=[lambda i: i["feature_type"] == enums.FeatureType.NUMERIC.name_val],
    )

    # Check to see that features passed exist in first place
    model_utils._check_features(
        features=[numeric_feature_name],
        check_list=existing_features,
        errmsg=enums.CheckFeaturesErrMsg.ALL.get_errmsg(is_published=False),
    )

    # Check to see that features passed are numeric
    model_utils._check_features(
        features=[numeric_feature_name],
        check_list=existing_measures,
        errmsg=enums.CheckFeaturesErrMsg.NUMERIC.get_errmsg(is_published=False),
    )

    model_utils._check_conflicts(to_add=new_feature_name, preexisting=existing_features)

    hier_dict, level_dict = feature_utils._check_time_hierarchy(
        data_model=data_model, hierarchy_name=hierarchy_name, level_name=level_name
    )

    time_dimension = hier_dict["dimension"]

    expression = (
        f"CASE WHEN IsEmpty([Measures].[{numeric_feature_name}]) THEN NULL ELSE "
        f"Sum(PeriodsToDate([{time_dimension}].[{hierarchy_name}].[{level_name}], "
        f"[{time_dimension}].[{hierarchy_name}].CurrentMember), [Measures].[{numeric_feature_name}]) END"
    )

    cube_id = data_model.cube_id
    feature_utils._create_calculated_feature(
        project_dict,
        cube_id,
        new_feature_name,
        expression,
        description=description,
        caption=caption,
        folder=folder,
        format_string=format_string,
        visible=visible,
    )
    data_model.project._update_project(project_dict=project_dict, publish=publish)


def create_pct_error_calculation(
    data_model: DataModel,
    new_feature_name: str,
    predicted_feature_name: str,
    actual_feature_name: str,
    description: str = None,
    caption: str = None,
    folder: str = None,
    format_string: Union[enums.FeatureFormattingType, str] = None,
    visible: bool = True,
    publish: bool = True,
):
    """Creates a calculation for the percent error of a predictive feature compared to the actual feature

    Args:
        data_model (DataModel): The DataModel that the feature will be written into
        new_feature_name (str): The query name of the new feature
        predicted_feature_name (str): The query name of the feature containing predictions
        actual_feature_name (str): The query name of the feature to compare the predictions to
        description (str, optional): The description for the feature. Defaults to None.
        caption (str, optional): The caption for the feature. Defaults to None.
        folder (str, optional): The folder to put the feature in. Defaults to None.
        format_string (Union[enums.FeatureFormattingType, str], optional): The format string for the feature. Defaults to None.
        visible (bool, optional): Whether the feature will be visible to BI tools. Defaults to True.
        publish (bool, optional): Whether or not the updated project should be published. Defaults to True.
    """
    # check if the provided data_model is a perspective
    model_utils._perspective_check(data_model)

    inspection = getfullargspec(create_pct_error_calculation)
    validation_utils.validate_by_type_hints(inspection=inspection, func_params=locals())

    proj_dict = data_model.project._get_dict()

    all_features_info = data_model_helpers._get_draft_features(
        proj_dict, data_model_name=data_model.name
    )
    numeric_features_info = dictionary_parser.filter_dict(
        to_filter=all_features_info,
        val_filters=[lambda i: i["feature_type"] == enums.FeatureType.NUMERIC.name_val],
    )

    # Check to see that features passed exist in first place
    model_utils._check_features(
        features=[predicted_feature_name, actual_feature_name],
        check_list=all_features_info,
        errmsg=enums.CheckFeaturesErrMsg.ALL.get_errmsg(is_published=False),
    )

    # Check to see that features passed are numeric
    model_utils._check_features(
        features=[predicted_feature_name, actual_feature_name],
        check_list=numeric_features_info,
        errmsg=enums.CheckFeaturesErrMsg.NUMERIC.get_errmsg(is_published=False),
    )

    expression = (
        f"100*([Measures].[{predicted_feature_name}] - [Measures].[{actual_feature_name}]) / "
        f"[Measures].[{actual_feature_name}]"
    )
    data_model.create_calculated_feature(
        new_feature_name,
        expression,
        description=description,
        caption=caption,
        folder=folder,
        format_string=format_string,
        visible=visible,
        publish=publish,
    )


def create_scaled_feature_minmax(
    data_model: DataModel,
    new_feature_name: str,
    numeric_feature_name: str,
    min: float,
    max: float,
    feature_min: float = 0,
    feature_max: float = 1,
    description: str = None,
    caption: str = None,
    folder: str = None,
    format_string: Union[enums.FeatureFormattingType, str] = None,
    visible: bool = True,
    publish: bool = True,
):
    """Creates a new feature that is minmax scaled

    Args:
        data_model (DataModel): The DataModel that the feature will be written into
        new_feature_name (str): The query name of the new feature
        numeric_feature_name (str): The query name of the feature to scale
        min (float): The min from the base feature
        max (float): The max from the base feature
        feature_min (float, optional): The min for the scaled feature. Defaults to 0.
        feature_max (float, optional): The max for the scaled feature. Defaults to 1.
        description (str, optional): The description for the feature. Defaults to None.
        caption (str, optional): The caption for the feature. Defaults to None.
        folder (str, optional): The folder to put the feature in. Defaults to None.
        format_string (Union[enums.FeatureFormattingType, str], optional): The format string for the feature. Defaults to None.
        visible (bool, optional): Whether the feature will be visible to BI tools. Defaults to True.
        publish (bool, optional): Whether or not the updated project should be published. Defaults to True.
    """
    # check if the provided data_model is a perspective
    model_utils._perspective_check(data_model)

    inspection = getfullargspec(create_scaled_feature_minmax)
    validation_utils.validate_by_type_hints(inspection=inspection, func_params=locals())

    project_dict = data_model.project._get_dict()
    draft_features = data_model_helpers._get_draft_features(
        project_dict=project_dict,
        data_model_name=data_model.name,
        feature_type=enums.FeatureType.ALL,
    )

    # Check to see that features passed exist in first place
    model_utils._check_features(
        features=[numeric_feature_name],
        check_list=draft_features,
        errmsg=enums.CheckFeaturesErrMsg.ALL.get_errmsg(is_published=False),
    )

    # Check to see that features passed are numeric
    draft_measures = dictionary_parser.filter_dict(
        to_filter=draft_features,
        val_filters=[lambda i: i["feature_type"] == enums.FeatureType.NUMERIC.name_val],
    )

    model_utils._check_features(
        features=[numeric_feature_name],
        check_list=draft_measures,
        errmsg=enums.CheckFeaturesErrMsg.NUMERIC.get_errmsg(is_published=False),
    )

    expression = (
        f"(([Measures].[{numeric_feature_name}] - {min})/({max}-{min}))"
        f"*({feature_max}-{feature_min})+{feature_min}"
    )

    data_model.create_calculated_feature(
        new_feature_name,
        expression,
        description=description,
        caption=caption,
        folder=folder,
        format_string=format_string,
        visible=visible,
        publish=publish,
    )


def create_scaled_feature_z_score(
    data_model: DataModel,
    new_feature_name: str,
    numeric_feature_name: str,
    mean: float = 0,
    standard_deviation: float = 1,
    description: str = None,
    caption: str = None,
    folder: str = None,
    format_string: Union[enums.FeatureFormattingType, str] = None,
    visible: bool = True,
    publish: bool = True,
):
    """Creates a new feature that is standard scaled

    Args:
        data_model (DataModel): The DataModel that the feature will be written into
        new_feature_name (str): The query name of the new feature
        numeric_feature_name (str): The query name of the feature to scale
        mean (float, optional): The mean from the base feature. Defaults to 0.
        standard_deviation (float, optional): The standard deviation from the base feature. Defaults to 1.
        description (str, optional): The description for the feature. Defaults to None.
        caption (str, optional): The caption for the feature. Defaults to None.
        folder (str, optional): The folder to put the feature in. Defaults to None.
        format_string (Union[enums.FeatureFormattingType, str], optional): The format string for the feature. Defaults to None.
        visible (bool, optional): Whether the feature will be visible to BI tools. Defaults to True.
        publish (bool, optional): Whether or not the updated project should be published. Defaults to True.
    """
    # check if the provided data_model is a perspective
    model_utils._perspective_check(data_model)

    inspection = getfullargspec(create_scaled_feature_z_score)
    validation_utils.validate_by_type_hints(inspection=inspection, func_params=locals())

    project_dict = data_model.project._get_dict()
    draft_features = data_model_helpers._get_draft_features(
        project_dict=project_dict,
        data_model_name=data_model.name,
        feature_type=enums.FeatureType.ALL,
    )

    # Check to see that features passed exist in first place
    model_utils._check_features(
        features=[numeric_feature_name],
        check_list=draft_features,
        errmsg=enums.CheckFeaturesErrMsg.ALL.get_errmsg(is_published=False),
    )

    # Check to see that features passed are numeric
    draft_measures = dictionary_parser.filter_dict(
        to_filter=draft_features,
        val_filters=[lambda i: i["feature_type"] == enums.FeatureType.NUMERIC.name_val],
    )

    model_utils._check_features(
        features=[numeric_feature_name],
        check_list=draft_measures,
        errmsg=enums.CheckFeaturesErrMsg.NUMERIC.get_errmsg(is_published=False),
    )

    expression = f"([Measures].[{numeric_feature_name}] - {mean}) / {standard_deviation}"

    data_model.create_calculated_feature(
        new_feature_name,
        expression,
        description=description,
        caption=caption,
        folder=folder,
        format_string=format_string,
        visible=visible,
        publish=publish,
    )


def create_scaled_feature_maxabs(
    data_model: DataModel,
    new_feature_name: str,
    numeric_feature_name: str,
    maxabs: float,
    description: str = None,
    caption: str = None,
    folder: str = None,
    format_string: Union[enums.FeatureFormattingType, str] = None,
    visible: bool = True,
    publish: bool = True,
):
    """Creates a new feature that is maxabs scaled

    Args:
        data_model (DataModel): The DataModel that the feature will be written into
        new_feature_name (str): The query name of the new feature
        numeric_feature_name (str): The query name of the feature to scale
        maxabs (float): The max absolute value of any data point from the base feature
        description (str, optional): The description for the feature. Defaults to None.
        caption (str, optional): The caption for the feature. Defaults to None.
        folder (str, optional): The folder to put the feature in. Defaults to None.
        format_string (Union[enums.FeatureFormattingType, str], optional): The format string for the feature. Defaults to None.
        visible (bool, optional): Whether the feature will be visible to BI tools. Defaults to True.
        publish (bool, optional): Whether or not the updated project should be published. Defaults to True.
    """
    # check if the provided data_model is a perspective
    model_utils._perspective_check(data_model)

    inspection = getfullargspec(create_scaled_feature_maxabs)
    validation_utils.validate_by_type_hints(inspection=inspection, func_params=locals())

    project_dict = data_model.project._get_dict()
    draft_features = data_model_helpers._get_draft_features(
        project_dict=project_dict,
        data_model_name=data_model.name,
        feature_type=enums.FeatureType.ALL,
    )

    # Check to see that features passed exist in first place
    model_utils._check_features(
        features=[numeric_feature_name],
        check_list=draft_features,
        errmsg=enums.CheckFeaturesErrMsg.ALL.get_errmsg(is_published=False),
    )

    # Check to see that features passed are numeric
    draft_measures = dictionary_parser.filter_dict(
        to_filter=draft_features,
        val_filters=[lambda i: i["feature_type"] == enums.FeatureType.NUMERIC.name_val],
    )

    model_utils._check_features(
        features=[numeric_feature_name],
        check_list=draft_measures,
        errmsg=enums.CheckFeaturesErrMsg.NUMERIC.get_errmsg(is_published=False),
    )

    maxabs = abs(maxabs)
    expression = f"[Measures].[{numeric_feature_name}] / {maxabs}"

    data_model.create_calculated_feature(
        new_feature_name,
        expression,
        description=description,
        caption=caption,
        folder=folder,
        format_string=format_string,
        visible=visible,
        publish=publish,
    )


def create_scaled_feature_robust(
    data_model: DataModel,
    new_feature_name: str,
    numeric_feature_name: str,
    median: float = 0,
    interquartile_range: float = 1,
    description: str = None,
    caption: str = None,
    folder: str = None,
    format_string: Union[enums.FeatureFormattingType, str] = None,
    visible: bool = True,
    publish: bool = True,
):
    """Creates a new feature that is robust scaled; mirrors default behavior of scikit-learn.preprocessing.RobustScaler

    Args:
        data_model (DataModel): The DataModel that the feature will be written into
        new_feature_name (str): The query name of the new feature
        numeric_feature_name (str): The query name of the feature to scale
        median (float, optional): _description_. Defaults to 0.
        interquartile_range (float, optional): _description_. Defaults to 1.
        description (str, optional): The description for the feature. Defaults to None.
        caption (str, optional): The caption for the feature. Defaults to None.
        folder (str, optional): The folder to put the feature in. Defaults to None.
        format_string (Union[enums.FeatureFormattingType, str], optional): The format string for the feature. Defaults to None.
        visible (bool, optional): Whether the feature will be visible to BI tools. Defaults to True.
        publish (bool, optional): Whether or not the updated project should be published. Defaults to True.
    """
    # check if the provided data_model is a perspective
    model_utils._perspective_check(data_model)

    inspection = getfullargspec(create_scaled_feature_robust)
    validation_utils.validate_by_type_hints(inspection=inspection, func_params=locals())

    project_dict = data_model.project._get_dict()
    draft_features = data_model_helpers._get_draft_features(
        project_dict=project_dict,
        data_model_name=data_model.name,
        feature_type=enums.FeatureType.ALL,
    )

    # Check to see that features passed exist in first place
    model_utils._check_features(
        features=[numeric_feature_name],
        check_list=draft_features,
        errmsg=enums.CheckFeaturesErrMsg.ALL.get_errmsg(is_published=False),
    )

    # Check to see that features passed are numeric
    draft_measures = dictionary_parser.filter_dict(
        to_filter=draft_features,
        val_filters=[lambda i: i["feature_type"] == enums.FeatureType.NUMERIC.name_val],
    )

    model_utils._check_features(
        features=[numeric_feature_name],
        check_list=draft_measures,
        errmsg=enums.CheckFeaturesErrMsg.NUMERIC.get_errmsg(is_published=False),
    )

    expression = f"([Measures].[{numeric_feature_name}] - {median}) / {interquartile_range}"

    data_model.create_calculated_feature(
        new_feature_name,
        expression,
        description=description,
        caption=caption,
        folder=folder,
        format_string=format_string,
        visible=visible,
        publish=publish,
    )


def create_scaled_feature_log_transformed(
    data_model: DataModel,
    new_feature_name: str,
    numeric_feature_name: str,
    description: str = None,
    caption: str = None,
    folder: str = None,
    format_string: Union[enums.FeatureFormattingType, str] = None,
    visible: bool = True,
    publish: bool = True,
):
    """Creates a new feature that is log transformed

    Args:
        data_model (DataModel): The DataModel that the feature will be written into
        new_feature_name (str): The query name of the new feature
        numeric_feature_name (str): The query name of the feature to scale
        description (str, optional): The description for the feature. Defaults to None.
        caption (str, optional): The caption for the feature. Defaults to None.
        folder (str, optional): The folder to put the feature in. Defaults to None.
        format_string (Union[enums.FeatureFormattingType, str], optional): The format string for the feature. Defaults to None.
        visible (bool, optional): Whether the feature will be visible to BI tools. Defaults to True.
        publish (bool, optional): Whether or not the updated project should be published. Defaults to True.
    """
    # check if the provided data_model is a perspective
    model_utils._perspective_check(data_model)

    inspection = getfullargspec(create_scaled_feature_log_transformed)
    validation_utils.validate_by_type_hints(inspection=inspection, func_params=locals())

    project_dict = data_model.project._get_dict()
    draft_features = data_model_helpers._get_draft_features(
        project_dict=project_dict,
        data_model_name=data_model.name,
        feature_type=enums.FeatureType.ALL,
    )

    # Check to see that features passed exist in first place
    model_utils._check_features(
        features=[numeric_feature_name],
        check_list=draft_features,
        errmsg=enums.CheckFeaturesErrMsg.ALL.get_errmsg(is_published=False),
    )

    # Check to see that features passed are numeric
    draft_measures = dictionary_parser.filter_dict(
        to_filter=draft_features,
        val_filters=[lambda i: i["feature_type"] == enums.FeatureType.NUMERIC.name_val],
    )

    model_utils._check_features(
        features=[numeric_feature_name],
        check_list=draft_measures,
        errmsg=enums.CheckFeaturesErrMsg.NUMERIC.get_errmsg(is_published=False),
    )

    expression = f"log([Measures].[{numeric_feature_name}])"

    data_model.create_calculated_feature(
        new_feature_name,
        expression,
        description=description,
        caption=caption,
        folder=folder,
        format_string=format_string,
        visible=visible,
        publish=publish,
    )


def create_scaled_feature_unit_vector_norm(
    data_model: DataModel,
    new_feature_name: str,
    numeric_feature_name: str,
    magnitude: float,
    description: str = None,
    caption: str = None,
    folder: str = None,
    format_string: Union[enums.FeatureFormattingType, str] = None,
    visible: bool = True,
    publish: bool = True,
):
    """Creates a new feature that is unit vector normalized

    Args:
        data_model (DataModel): The DataModel that the feature will be written into
        new_feature_name (str): The query name of the new feature
        numeric_feature_name (str): The query name of the feature to scale
        magnitude (float): The magnitude of the base feature, i.e. the square root of the sum of the squares of numeric_feature's data points
        description (str, optional): The description for the feature. Defaults to None.
        caption (str, optional): The caption for the feature. Defaults to None.
        folder (str, optional): The folder to put the feature in. Defaults to None.
        format_string (Union[enums.FeatureFormattingType, str], optional): The format string for the feature. Defaults to None.
        visible (bool, optional): Whether the feature will be visible to BI tools. Defaults to True.
        publish (bool, optional): Whether or not the updated project should be published. Defaults to True.
    """
    # check if the provided data_model is a perspective
    model_utils._perspective_check(data_model)

    inspection = getfullargspec(create_scaled_feature_unit_vector_norm)
    validation_utils.validate_by_type_hints(inspection=inspection, func_params=locals())

    project_dict = data_model.project._get_dict()
    draft_features = data_model_helpers._get_draft_features(
        project_dict=project_dict,
        data_model_name=data_model.name,
        feature_type=enums.FeatureType.ALL,
    )

    # Check to see that features passed exist in first place
    model_utils._check_features(
        features=[numeric_feature_name],
        check_list=draft_features,
        errmsg=enums.CheckFeaturesErrMsg.ALL.get_errmsg(is_published=False),
    )

    # Check to see that features passed are numeric
    draft_measures = dictionary_parser.filter_dict(
        to_filter=draft_features,
        val_filters=[lambda i: i["feature_type"] == enums.FeatureType.NUMERIC.name_val],
    )

    model_utils._check_features(
        features=[numeric_feature_name],
        check_list=draft_measures,
        errmsg=enums.CheckFeaturesErrMsg.NUMERIC.get_errmsg(is_published=False),
    )

    expression = f"[Measures].[{numeric_feature_name}]/{magnitude}"

    data_model.create_calculated_feature(
        new_feature_name,
        expression,
        description=description,
        caption=caption,
        folder=folder,
        format_string=format_string,
        visible=visible,
        publish=publish,
    )


def create_scaled_feature_power_transformed(
    data_model: DataModel,
    new_feature_name: str,
    numeric_feature_name: str,
    power: float,
    method: str = "yeo-johnson",
    description: str = None,
    caption: str = None,
    folder: str = None,
    format_string: Union[enums.FeatureFormattingType, str] = None,
    visible: bool = True,
    publish: bool = True,
):
    """Creates a new feature that is power transformed. Parameter 'method' must be either 'box-cox' or 'yeo-johnson'

    Args:
        data_model (DataModel): The DataModel that the feature will be written into
        new_feature_name (str): The query name of the new feature
        numeric_feature_name (str): The query name of the feature to scale
        power (float): The exponent used in the scaling
        method (str, optional): Which power transformation method to use. Defaults to 'yeo-johnson'.
        description (str, optional): The description for the feature. Defaults to None.
        caption (str, optional): The caption for the feature. Defaults to None.
        folder (str, optional): The folder to put the feature in. Defaults to None.
        format_string (Union[enums.FeatureFormattingType, str], optional): The format string for the feature. Defaults to None.
        visible (bool, optional): Whether the feature will be visible to BI tools. Defaults to True.
        publish (bool, optional): Whether or not the updated project should be published. Defaults to True.
    """
    # check if the provided data_model is a perspective
    model_utils._perspective_check(data_model)

    inspection = getfullargspec(create_scaled_feature_power_transformed)
    validation_utils.validate_by_type_hints(inspection=inspection, func_params=locals())

    project_dict = data_model.project._get_dict()
    draft_features = data_model_helpers._get_draft_features(
        project_dict=project_dict,
        data_model_name=data_model.name,
        feature_type=enums.FeatureType.ALL,
    )

    # Check to see that features passed exist in first place
    model_utils._check_features(
        features=[numeric_feature_name],
        check_list=draft_features,
        errmsg=enums.CheckFeaturesErrMsg.ALL.get_errmsg(is_published=False),
    )

    # Check to see that features passed are numeric
    draft_measures = dictionary_parser.filter_dict(
        to_filter=draft_features,
        val_filters=[lambda i: i["feature_type"] == enums.FeatureType.NUMERIC.name_val],
    )

    model_utils._check_features(
        features=[numeric_feature_name],
        check_list=draft_measures,
        errmsg=enums.CheckFeaturesErrMsg.NUMERIC.get_errmsg(is_published=False),
    )

    if method.lower() == "yeo-johnson":
        if power == 0:
            expression = (
                f"IIF([Measures].[{numeric_feature_name}]<0,"
                f"(-1*((((-1*[Measures].[{numeric_feature_name}])+1)^(2-{power}))-1))"
                f"/(2-{power}),log([Measures].[{numeric_feature_name}]+1))"
            )
        elif power == 2:
            expression = (
                f"IIF([Measures].[{numeric_feature_name}]<0,"
                f"(-1*log((-1*[Measures].[{numeric_feature_name}])+1)),"
                f"((([Measures].[{numeric_feature_name}]+1)^{power})-1)/{power})"
            )
        else:
            expression = (
                f"IIF([Measures].[{numeric_feature_name}]<0,"
                f"(-1*((((-1*[Measures].[{numeric_feature_name}])+1)^(2-{power}))-1))/(2-{power}),"
                f"((([Measures].[{numeric_feature_name}]+1)^{power})-1)/{power})"
            )
    elif method.lower() == "box-cox":
        if power == 0:
            expression = f"log([Measures].[{numeric_feature_name}])"
        else:
            expression = f"(([Measures].[{numeric_feature_name}]^{power})-1)/{power}"
    else:
        raise ValueError("Invalid type: Valid values are yeo-johnson and box-cox")

    data_model.create_calculated_feature(
        new_feature_name,
        expression,
        description=description,
        caption=caption,
        folder=folder,
        format_string=format_string,
        visible=visible,
        publish=publish,
    )


def create_net_error_calculation(
    data_model: DataModel,
    new_feature_name: str,
    predicted_feature_name: str,
    actual_feature_name: str,
    description: str = None,
    caption: str = None,
    folder: str = None,
    format_string: Union[enums.FeatureFormattingType, str] = None,
    visible: bool = True,
    publish: bool = True,
):
    """Creates a calculation for the net error of a predictive feature compared to the actual feature

    Args:
        data_model (DataModel): The Data Model that the feature will be created in
        new_feature_name (str): The query name of the new feature
        predicted_feature_name (str): The query name of the feature containing predictions
        actual_feature_name (str): The query name of the feature to compare the predictions to
        description (str, optional): The description for the feature. Defaults to None.
        caption (str, optional): The caption for the feature. Defaults to None.
        folder (str, optional): The folder to put the feature in. Defaults to None.
        format_string (Union[enums.FeatureFormattingType, str], optional): The format string for the feature. Defaults to None.
        visible (bool, optional): Whether the created feature will be visible to BI tools. Defaults to True.
        publish (bool, optional): Whether or not the updated project should be published. Defaults to True.
    """
    # check if the provided data_model is a perspective
    model_utils._perspective_check(data_model)

    inspection = getfullargspec(create_net_error_calculation)
    validation_utils.validate_by_type_hints(inspection=inspection, func_params=locals())

    project_dict = data_model.project._get_dict()

    all_features_info = data_model_helpers._get_draft_features(
        project_dict, data_model_name=data_model.name
    )
    measure_list = dictionary_parser.filter_dict(
        to_filter=all_features_info,
        val_filters=[lambda i: i["feature_type"] == enums.FeatureType.NUMERIC.name_val],
    )

    # Check to see that features passed exist in first place
    model_utils._check_features(
        features=[predicted_feature_name, actual_feature_name],
        check_list=all_features_info,
        errmsg=enums.CheckFeaturesErrMsg.ALL.get_errmsg(is_published=False),
    )

    # Check to see that features passed are numeric
    model_utils._check_features(
        features=[predicted_feature_name, actual_feature_name],
        check_list=measure_list,
        errmsg=enums.CheckFeaturesErrMsg.NUMERIC.get_errmsg(is_published=False),
    )

    model_utils._check_conflicts(to_add=new_feature_name, preexisting=all_features_info)

    expression = f"[Measures].[{predicted_feature_name}] - [Measures].[{actual_feature_name}]"
    feature_utils._create_calculated_feature(
        project_dict=project_dict,
        cube_id=data_model.cube_id,
        name=new_feature_name,
        expression=expression,
        description=description,
        caption=caption,
        folder=folder,
        format_string=format_string,
        visible=visible,
    )
    data_model.project._update_project(project_dict=project_dict, publish=publish)


def create_binned_feature(
    data_model: DataModel,
    new_feature_name: str,
    numeric_feature_name: str,
    bin_edges: List[float],
    description: str = None,
    caption: str = None,
    folder: str = None,
    format_string: Union[enums.FeatureFormattingType, str] = None,
    visible: bool = True,
    publish: bool = True,
):
    """Creates a new feature that is a binned version of an existing numeric feature.

    Args:
        data_model (DataModel): The DataModel that the feature will be written into
        new_feature_name (str): The query name of the new feature
        numeric_feature_name (str): The query name of the feature to bin
        bin_edges (List[float]): The edges to use to compute the bins, left inclusive. Contents of bin_edges are interpreted
                                 in ascending order
        description (str, optional): The description for the feature. Defaults to None.
        caption (str, optional): The caption for the feature. Defaults to None.
        folder (str, optional): The folder to put the feature in. Defaults to None.
        format_string (Union[enums.FeatureFormattingType, str], optional): The format string for the feature. Defaults to None.
        visible (bool, optional): Whether the created feature will be visible to BI tools. Defaults to True.
        publish (bool, optional): Whether or not the updated project should be published. Defaults to True.
    """
    # check if the provided data_model is a perspective
    model_utils._perspective_check(data_model)

    inspection = getfullargspec(create_binned_feature)
    validation_utils.validate_by_type_hints(inspection=inspection, func_params=locals())

    project_dict = data_model.project._get_dict()
    draft_features = data_model_helpers._get_draft_features(
        project_dict=project_dict,
        data_model_name=data_model.name,
        feature_type=enums.FeatureType.ALL,
    )

    # Check to see that features passed exist in first place
    model_utils._check_features(
        features=[numeric_feature_name],
        check_list=draft_features,
        errmsg=enums.CheckFeaturesErrMsg.ALL.get_errmsg(is_published=False),
    )

    # Check to see that features passed are numeric
    draft_measures = dictionary_parser.filter_dict(
        to_filter=draft_features,
        val_filters=[lambda i: i["feature_type"] == enums.FeatureType.NUMERIC.name_val],
    )

    model_utils._check_features(
        features=[numeric_feature_name],
        check_list=draft_measures,
        errmsg=enums.CheckFeaturesErrMsg.NUMERIC.get_errmsg(is_published=False),
    )

    bin_edges = sorted(bin_edges)
    expression = f"CASE [Measures].[{numeric_feature_name}]"
    bin = 0
    for edge in bin_edges:
        expression += f" WHEN [Measures].[{numeric_feature_name}] < {edge} THEN {bin}"
        bin += 1
    expression += f" ELSE {bin} END"

    data_model.create_calculated_feature(
        new_feature_name,
        expression,
        description=description,
        caption=caption,
        folder=folder,
        format_string=format_string,
        visible=visible,
        publish=publish,
    )


def create_covariance_feature(
    data_model: DataModel,
    new_feature_name: str,
    hierarchy_name: str,
    numeric_feature_1_name: str,
    numeric_feature_2_name: str,
    use_sample: bool = True,
    description: str = None,
    caption: str = None,
    folder: str = None,
    format_string: str = None,
    visible: bool = True,
    publish: bool = True,
):
    """Creates a new feature off of the published project showing the covariance of two features.

    Args:
        data_model (DataModel): The DataModel that the feature will be written into
        new_feature_name (str): The query name of the new feature
        hierarchy_name (str): The query name of the hierarchy used in the calculation
        numeric_feature_1_name (str): The query name of the first feature in the covariance calculation
        numeric_feature_2_name (str): The query name of the second feature in the covariance calculation
        use_sample (bool, optional): Whether the covariance being calculated is the sample covariance. Defaults
                                     to True.
        description (str, optional): The description for the feature. Defaults to None.
        caption (str, optional): The caption for the feature. Defaults to None.
        folder (str, optional): The folder to put the feature in. Defaults to None.
        format_string (str, optional): The format string for the feature. Defaults to None.
        visible (bool, optional): Whether the created feature will be visible to BI tools. Defaults to True.
        publish (bool, optional): Whether or not the updated project should be published. Defaults to True.
    """
    model_utils._perspective_check(data_model)

    inspection = getfullargspec(create_covariance_feature)
    validation_utils.validate_by_type_hints(inspection=inspection, func_params=locals())

    # check that we are using a published project
    project_helpers._check_published(data_model.project)

    all_published_features = data_model_helpers._get_published_features(data_model=data_model)

    # Check to see that features passed are numeric
    all_numeric_features = dictionary_parser.filter_dict(
        to_filter=all_published_features,
        val_filters=[lambda i: i["feature_type"] == enums.FeatureType.NUMERIC.name_val],
    )

    # Check that features exist in the first place
    model_utils._check_features(
        features=[numeric_feature_1_name, numeric_feature_2_name],
        check_list=all_published_features,
        errmsg=enums.CheckFeaturesErrMsg.ALL.get_errmsg(is_published=True),
    )

    # Check that numeric features are indeed numeric
    model_utils._check_features(
        features=[numeric_feature_1_name, numeric_feature_2_name],
        check_list=all_numeric_features,
        errmsg=enums.CheckFeaturesErrMsg.NUMERIC.get_errmsg(is_published=True),
    )

    feature_utils._check_hierarchy(
        data_model=data_model,
        hierarchy_name=hierarchy_name,
        level_name=None,
    )

    dimension, leaf = metadata_utils._get_dimension_and_lowest_hierarchy_level(
        data_model=data_model,
        hierarchy_name=hierarchy_name,
    )

    expr = feature_utils._get_cov_str(
        dimension=dimension,
        hierarchy_name=hierarchy_name,
        numeric_feature_1_name=numeric_feature_1_name,
        numeric_feature_2_name=numeric_feature_2_name,
        leaf_level=leaf,
        use_sample=use_sample,
    )

    data_model.create_calculated_feature(
        new_feature_name=new_feature_name,
        expression=expr,
        description=description,
        caption=caption,
        folder=folder,
        format_string=format_string,
        visible=visible,
        publish=publish,
    )


def create_correlation_feature(
    data_model: DataModel,
    new_feature_name: str,
    hierarchy_name: str,
    numeric_feature_1_name: str,
    numeric_feature_2_name: str,
    description: str = None,
    caption: str = None,
    folder: str = None,
    format_string: str = None,
    visible: bool = True,
    publish: bool = True,
):
    """Creates a new feature off of the published project showing the correlation of two features.

    Args:
        data_model (DataModel): The DataModel that the feature will be written into
        new_feature_name (str): The query name of the new feature
        hierarchy_name (str): The query name of the hierarchy used in the calculation
        numeric_feature_1_name (str): The query name of the first feature in the correlation calculation
        numeric_feature_2_name (str): The query name of the second feature in the correlation calculation
        description (str, optional): The description for the feature. Defaults to None.
        caption (str, optional): The caption for the feature. Defaults to None.
        folder (str, optional): The folder to put the feature in. Defaults to None.
        format_string (str, optional): The format string for the feature. Defaults to None.
        visible (bool, optional): Whether the created feature will be visible to BI tools. Defaults to True.
        publish (bool, optional): Whether or not the updated project should be published. Defaults to True.
    """
    model_utils._perspective_check(data_model)

    inspection = getfullargspec(create_correlation_feature)
    validation_utils.validate_by_type_hints(inspection=inspection, func_params=locals())

    # check that we are using a published project
    project_helpers._check_published(data_model.project)

    all_published_features = data_model_helpers._get_published_features(data_model=data_model)

    # Check to see that features passed are numeric
    all_numeric_features = dictionary_parser.filter_dict(
        to_filter=all_published_features,
        val_filters=[lambda i: i["feature_type"] == enums.FeatureType.NUMERIC.name_val],
    )

    # Check that features exist in the first place
    model_utils._check_features(
        features=[numeric_feature_1_name, numeric_feature_2_name],
        check_list=all_published_features,
        errmsg=enums.CheckFeaturesErrMsg.ALL.get_errmsg(is_published=True),
    )

    # Check that numeric features are indeed numeric
    model_utils._check_features(
        features=[numeric_feature_1_name, numeric_feature_2_name],
        check_list=all_numeric_features,
        errmsg=enums.CheckFeaturesErrMsg.NUMERIC.get_errmsg(is_published=True),
    )

    feature_utils._check_hierarchy(
        data_model=data_model,
        hierarchy_name=hierarchy_name,
        level_name=None,
    )

    dimension, leaf = metadata_utils._get_dimension_and_lowest_hierarchy_level(
        data_model=data_model,
        hierarchy_name=hierarchy_name,
    )

    expr = feature_utils._get_corr_str(
        dimension=dimension,
        hierarchy_name=hierarchy_name,
        numeric_feature_1_name=numeric_feature_1_name,
        numeric_feature_2_name=numeric_feature_2_name,
        leaf_level=leaf,
    )

    data_model.create_calculated_feature(
        new_feature_name=new_feature_name,
        expression=expr,
        description=description,
        caption=caption,
        folder=folder,
        format_string=format_string,
        visible=visible,
        publish=publish,
    )


def generate_time_series_features(
    data_model: DataModel,
    dataframe: DataFrame,
    numeric_features: List[str],
    time_hierarchy: str,
    level: str,
    group_features: List[str] = None,
    intervals: List[int] = None,
    shift_amount: int = 0,
) -> DataFrame:
    """Generates time series features off of the published project, like rolling statistics and period to date for the given numeric features
     using the time hierarchy from the given data model. The core of the function is built around the groupby function, like so:
        dataframe[groupby(group_features + hierarchy_levels)][shift(shift_amount)][rolling(interval)][{aggregate function}]

    Args:
        data_model (DataModel): The data model to use.
        dataframe (pandas.DataFrame): the pandas dataframe with the features.
        numeric_features (List[str]): The list of numeric feature query names to build time series features of.
        time_hierarchy (str): The query names of the time hierarchy to use to derive features.
        level (str): The query name of the level within the time hierarchy to derive the features at.
        group_features (List[str], optional): The list of features to group by. Note that this acts as a logical grouping as opposed to a
            dimensionality reduction when paired with shifts or intervals. Defaults to None.
        intervals (List[int], optional): The intervals to create the features over.
            Will use default values based on the time step of the given level if None. Defaults to None.
        shift_amount (int, optional): The amount of rows to shift the new features. Defaults to 0.

    Returns:
        DataFrame: A DataFrame containing the original columns and the newly generated ones
    """
    inspection = getfullargspec(generate_time_series_features)
    validation_utils.validate_by_type_hints(inspection=inspection, func_params=locals())

    # check that we are using a published project
    project_helpers._check_published(data_model.project)

    feature_utils._check_time_hierarchy(
        data_model=data_model, hierarchy_name=time_hierarchy, level_name=level
    )

    all_published_features = data_model_helpers._get_published_features(data_model=data_model)

    # Check to see that features passed are numeric
    measure_list = list(
        dictionary_parser.filter_dict(
            to_filter=all_published_features,
            val_filters=[lambda i: i["feature_type"] == enums.FeatureType.NUMERIC.name_val],
        ).keys()
    )

    categorical_list = list(
        dictionary_parser.filter_dict(
            to_filter=all_published_features,
            val_filters=[lambda i: i["feature_type"] == enums.FeatureType.CATEGORICAL.name_val],
        ).keys()
    )

    if group_features:
        # Check to see that features passed exist in first place
        model_utils._check_features(
            features=group_features,
            check_list=all_published_features,
            errmsg=enums.CheckFeaturesErrMsg.ALL.get_errmsg(is_published=True),
        )

        # Check to see that features passed are categorical
        model_utils._check_features(
            features=group_features,
            check_list=categorical_list,
            errmsg=enums.CheckFeaturesErrMsg.CATEGORICAL.get_errmsg(is_published=True),
        )

    # Check to see that features passed exist in first place
    model_utils._check_features(
        features=numeric_features,
        check_list=all_published_features,
        errmsg=enums.CheckFeaturesErrMsg.ALL.get_errmsg(is_published=True),
    )

    # Check to see that features passed are numeric
    model_utils._check_features(
        features=numeric_features,
        check_list=measure_list,
        errmsg=enums.CheckFeaturesErrMsg.NUMERIC.get_errmsg(is_published=True),
    )

    level_dict = all_published_features[level]
    time_numeric = level_dict["atscale_type"]
    # takes out the Time and 's' at the end and in lowercase
    time_name = str(time_numeric)[4:-1].lower()

    if intervals:
        if type(intervals) != list:
            intervals = [intervals]
    else:
        intervals = enums.TimeSteps[time_numeric].get_steps()

    shift_name = f"_shift_{shift_amount}" if shift_amount != 0 else ""

    levels = [x for x in metadata_utils._get_hierarchy_levels(data_model, time_hierarchy) if x in dataframe.columns]

    if group_features:
        dataframe = dataframe.sort_values(by=group_features + levels).reset_index(drop=True)
    else:
        dataframe = dataframe.sort_values(by=levels).reset_index(drop=True)

    for feature in numeric_features:
        if group_features:

            def grouper(x):
                return x.groupby(group_features)

        else:

            def grouper(x):
                return x

            # set this to an empty list so we can add it to hier_level later no matter what
            group_features = []

        # a helper function for the agg chaining
        def groupby_chain(dataframe_n, feature_n, group_func, shift_amt, roll_interval, agg_func):
            if shift_amount != 0:
                func_to_exec = getattr(
                    group_func(dataframe_n)[feature_n].shift(shift_amt).rolling(roll_interval),
                    agg_func,
                )
                return func_to_exec().reset_index(drop=True)
            else:
                func_to_exec = getattr(
                    group_func(dataframe_n)[feature_n].rolling(roll_interval), agg_func
                )
                return func_to_exec().reset_index(drop=True)

        for interval in intervals:
            interval = int(interval)
            name = feature + f"_{interval}_{time_name}_"

            if interval > 1:
                dataframe[f"{name}sum{shift_name}"] = groupby_chain(
                    dataframe, feature, grouper, shift_amount, interval, "sum"
                )

                dataframe[f"{name}avg{shift_name}"] = groupby_chain(
                    dataframe, feature, grouper, shift_amount, interval, "mean"
                )

                dataframe[f"{name}stddev{shift_name}"] = groupby_chain(
                    dataframe, feature, grouper, shift_amount, interval, "std"
                )

                dataframe[f"{name}min{shift_name}"] = groupby_chain(
                    dataframe, feature, grouper, shift_amount, interval, "min"
                )

                dataframe[f"{name}max{shift_name}"] = groupby_chain(
                    dataframe, feature, grouper, shift_amount, interval, "max"
                )

            dataframe[f"{name}lag{shift_name}"] = (
                grouper(dataframe)[feature].shift(shift_amount + interval).reset_index(drop=True)
            )

        found = False
        for heir_level in reversed(levels):
            if found and heir_level in dataframe.columns:
                name = f"{feature}_{heir_level}_to_date"
                if shift_amount != 0:
                    dataframe[name] = (
                        dataframe.groupby(group_features + [heir_level])[feature]
                        .shift(shift_amount)
                        .cumsum()
                        .reset_index(drop=True)
                    )
                else:
                    dataframe[name] = (
                        dataframe.groupby(group_features + [heir_level])[feature]
                        .cumsum()
                        .reset_index(drop=True)
                    )
            if heir_level == level:
                found = True

    return dataframe


def write_snowpark_udf_to_qds(
    data_model: DataModel,
    udf_name: str,
    new_feature_name: str,
    feature_inputs: List[str],
    publish: bool = True,
):
    """Writes a single column output of a udf into the given data_model as a feature. For example, if a
     udf created in snowpark 'udf' outputs predictions based on a given set of features '[f]', then calling
     write_udf_as_qds(data_model=atmodel, udf_name=udf, new_feature_name='predictions' feature_inputs=f)
     will create a new feature called 'predictions' which can be included in any query that excludes categorical features
     that are not accounted for in '[f]' (no feature not in same dimension at same level or lower in [f]). Currently only
     supports snowflake udfs.

    Args:
        data_model (DataModel): The AtScale data model to create the new feature in
        udf_name (str): The name of an existing udf which outputs a single column for every row of input.
            The full name space should be passed (ex. '"DB"."SCHEMA".udf_name').
        new_feature_name (str): The query name of the newly created feature from the output of the udf.
        feature_inputs (List[str]): The query names of features in data_model that are the inputs for the udf, in the order
            they are passed to the udf.
        publish (bool, optional): Whether to publish the project after updating, defaults to true.
    """
    model_utils._perspective_check(data_model)
    project_helpers._check_published(data_model.project)

    inspection = getfullargspec(write_snowpark_udf_to_qds)
    validation_utils.validate_by_type_hints(inspection=inspection, func_params=locals())

    # Check to see that features passed exist in first place
    project_dict = data_model.project._get_dict()

    existing_features = data_model_helpers._get_draft_features(
        project_dict=project_dict, data_model_name=data_model.name
    )

    model_utils._check_features(
        features=feature_inputs,
        check_list=existing_features,
        errmsg=enums.CheckFeaturesErrMsg.ALL.get_errmsg(is_published=False),
    )

    model_utils._check_conflicts(to_add=new_feature_name, preexisting=existing_features)
    atscale_query: str = query_utils._generate_atscale_query(
        data_model=data_model, feature_list=feature_inputs
    )
    feature_query: str = query_utils._generate_db_query(
        data_model=data_model, atscale_query=atscale_query, use_aggs=False
    )

    categorical_inputs = []
    join_columns = []
    join_features = []
    roleplay_expressions = []
    for feat in feature_inputs:
        if existing_features[feat]["feature_type"] == "Categorical":
            categorical_inputs.append(feat)
            if existing_features[feat]["secondary_attribute"] == False:
                join_columns.append(feat)
                join_features.append(existing_features[feat].get("base_name", feat))
                roleplay_expressions.append(
                    existing_features[feat].get("roleplay_expression", "{0}")
                )

    categorical_string: str = ", ".join(f'"{cat}"' for cat in categorical_inputs)
    qds_query: str = (
        f"SELECT {prediction_utils._snowpark_udf_call(udf_name=udf_name, feature_inputs=feature_inputs)} "
        f'as "{new_feature_name}", {categorical_string} FROM ({feature_query})'
    )
    qds_name = f"{new_feature_name}_QDS"
    data_model.create_dataset(
        dataset_name=qds_name,
        query=qds_query,
        publish=False,
    )
    data_model.create_dataset_relationship(
        dataset_name=qds_name,
        join_features=join_features,
        join_columns=join_columns,
        roleplay_features=roleplay_expressions,
        publish=False,
    )
    data_model.create_aggregate_feature(
        column_name=new_feature_name,
        fact_dataset_name=qds_name,
        new_feature_name=new_feature_name,
        aggregation_type=enums.Aggs.SUM,  # could parameterize
        publish=publish,
    )


def join_udf(
    data_model: DataModel,
    target_columns: List[str],
    udf_call: str,
    join_columns: List[Union[str, List[str]]] = None,
    join_features: List[str] = None,
    roleplay_features: List[str] = None,
    folder: str = None,
    qds_name: str = None,
    warehouse_id: str = None,
    allow_aggregates: bool = True,
    create_hinted_aggregate: bool = False,
    publish: bool = True,
):
    """Creates measures for each column in target_columns using the name that they are presented. For example,
    target_columns=['\"predicted_sales\" as \"sales_prediction\"', '\"confidence\"'] would make two measures named
    'sales_prediction' and 'confidence' respectively. The join_columns will be joined to join_features so that the
    target columns can be queried in tandem with the join_features and aggregate properly. If the join_columns already
    match the names of the categorical features in the data model, join_features can be omitted to use the names of the
    join_columns. The measures will be created from a QDS (Query Dataset) which uses the following query:
    'SELECT <target_column1, target_column2, ... target_columnN, join_column1, join_column2, ...> FROM <udf_call>'
    Each target column will have a sum aggregate feature created with "_SUM" appended to the column name.

    Args:
        data_model (DataModel): The AtScale data model to create the new features in
        target_columns (List[str]): A list of target columns which will be made into features, proper quoting for the
            data warehouse used is required. Feature names will be based on the name of the column as queried. These
            strings represent raw SQL and thus a target column can be a calculated column or udf call as long as it is
            proper SQL syntax.
        udf_call (str): A valid SQL statement that will be placed directly after a FROM clause and a space with no
        parenthesis.
        join_features (list, optional): a list of feature query names in the data model to use for joining. If None it will not
            join the qds to anything. Defaults to None for no joins.
        join_columns (list, optional): The columns in the from statement to join to the join_features. List must be
            either None or the same length and order as join_features. Defaults to None to use identical names to the
            join_features. If multiple columns are needed for a single join they should be in a nested list.
            Data warehouse specific quoting is not required, join_columns should be passed as strings and if quotes are
            required for the data model's data warehouse, they will be inserted automatically.
        roleplay_features (list, optional): The roleplays to use on the relationships. List must be either
                None or the same length and order as join_features. Use '' to not roleplay that relationship. Defaults to None.
        folder (str): Optionally specifies a folder to put the created features in. If the folder does not exist it will
            be created.
        qds_name (str): Optionally specifies the name of Query Dataset that is created. Defaults to None to be named
            AI_LINK_UDF_QDS_<N> where <N> is 1 or the minimum number that doesn't conflict with existing dataset names.
        warehouse_id (str, optional): Defaults to None. The id of the warehouse that datasets in the data model query from.
            This parameter is only required if no dataset has been created in the data model yet.
        allow_aggregates(bool, optional): Whether to allow aggregates to be built off of the QDS. Defaults to True.
        create_hinted_aggregate(bool, optional): Whether to generate an aggregate table for all measures and keys in this QDS to improve join performance. Defaults to False.
        publish (bool): Defaults to True. Whether the updated project should be published or only the draft should be
            updated.
    """
    model_utils._perspective_check(data_model)

    inspection = getfullargspec(join_udf)
    validation_utils.validate_by_type_hints(inspection=inspection, func_params=locals())

    project_dict = data_model.project._get_dict()

    if qds_name:
        # check if there is an existing dataset with the given name
        existing_dset = project_parser.get_dataset(project_dict=project_dict, dataset_name=qds_name)
        if existing_dset:
            raise atscale_errors.CollisionError(
                f"A dataset already exists with the name {qds_name}"
            )

    if join_features is None:
        join_features = []

    if join_columns is None:
        join_columns = join_features.copy()

    warehouse_id = validation_utils._validate_warehouse_id_parameter(
        atconn=data_model.project._atconn,
        project_dict=project_dict,
        warehouse_id=warehouse_id,
    )

    db_platform: enums.PlatformType = data_model.project._atconn._get_warehouse_platform(
        warehouse_id=warehouse_id
    )
    db_conn: SQLConnection = db_platform.dbconn
    q: str = db_conn._column_quote()  # ex. Snowflake.column_quote(), its a static method

    join_column_strings = [f"{q}{j}{q}" for j in join_columns]
    qds_query = f'SELECT {", ".join(target_columns + join_column_strings)} FROM {udf_call}'

    # we need a set of columns to check the joins
    columns = data_model.project._atconn._get_query_columns(
        warehouse_id=warehouse_id, query=qds_query
    )
    column_names = {col[0] for col in columns}

    join_features, join_columns, roleplay_features, _ = data_model_helpers._check_joins(
        project_dict=project_dict,
        cube_id=data_model.cube_id,
        join_features=join_features,
        join_columns=join_columns,
        roleplay_features=roleplay_features,
        column_set=column_names,
    )

    key_dict = project_parser._get_feature_keys(project_dict, data_model.cube_id, join_features)
    for join_feature, join_column in zip(join_features, join_columns):
        key_col = key_dict[join_feature]["key_cols"][0]
        value_col = key_dict[join_feature]["value_col"]
        if type(join_column) is list and len(join_column) == 1:
            join_column = join_column[0]
        if type(join_column) is not list and key_col != value_col and key_col != join_column:
            logger.warning(
                f"Feature: '{join_feature}' has different key and value columns. "
                f"If join_column: '{join_column}' does not contain the same values as the key column: "
                f"'{key_col}' this could impact the join and produce unexpected results from queries"
            )

    # check that the created agg will not have a conflict
    feat_dict: Dict = data_model_helpers._get_draft_features(
        project_dict=project_dict, data_model_name=data_model.name
    )
    columns_to_checks = [x[0] + "_SUM" for x in columns[: len(target_columns)]]
    model_utils._check_conflicts(to_add=columns_to_checks, preexisting=feat_dict)

    if qds_name is None:
        prefix = "AI_LINK_UDF_QDS_"
        all_dsets = project_parser.get_datasets(project_dict=project_dict)
        count = 1
        number_taken = {}
        for dset in all_dsets:
            if dset["name"][: len(prefix)] == prefix:
                try:
                    number_taken[int(dset["name"][len(prefix) :])] = True
                except:
                    pass
        while count in number_taken:
            count += 1
        qds_name = f"{prefix}{count}"

    project_dict = data_model.project._get_dict()

    project_dataset, dataset_id = project_utils._create_query_dataset(
        project_dict=project_dict,
        name=qds_name,
        query=qds_query,
        columns=columns,
        warehouse_id=warehouse_id,
        allow_aggregates=True,
    )
    model_dict = model_utils._get_model_dict(data_model, project_dict)[0]
    model_utils._add_data_set_ref(
        model_dict,
        dataset_id,
        allow_aggregates=allow_aggregates,
        create_hinted_aggregate=create_hinted_aggregate,
    )

    model_utils._create_dataset_relationship_from_dataset(
        project_dict=project_dict,
        cube_id=data_model.cube_id,
        dataset_name=qds_name,
        join_features=join_features,
        join_columns=join_columns,
        roleplay_features=roleplay_features,
    )

    for i in range(len(target_columns)):
        column_name = columns[i][0]
        feature_name = f"{column_name}_SUM"
        feature_utils._create_aggregate_feature(
            project_dict=project_dict,
            cube_id=data_model.cube_id,
            dataset_id=dataset_id,
            column_name=column_name,
            new_feature_name=feature_name,
            aggregation_type=enums.Aggs.SUM,
            caption=feature_name,
            folder=folder,
        )
    data_model.project._update_project(project_dict=project_dict, publish=publish)


def write_linear_regression_model(
    data_model: DataModel,
    regression_model,
    new_feature_name: str,
    granularity_levels: List[str] = None,
    feature_inputs: List[str] = None,
):
    """Writes a scikit-learn LinearRegression model, which takes AtScale features exclusively as input, to the given
    Published DataModel as a sum aggregated feature with the given name. The feature will return the output of the coefficients
    and intercept in the model applied to feature_inputs as defined in AtScale. Omitting feature_inputs will use the
    names of the columns passed at training time and error if any names are not in the data model.

    Args:
        data_model (DataModel): The AtScale DataModel to add the regression into.
        regression_model (LinearRegression): The scikit-learn LinearRegression model to build into a feature.
        new_feature_name (str): The query name of the created feature.
        granularity_levels (List[str], optional): List of the query names for the lowest categorical levels that predictions with this
            model can be run on. Defaults to False to use the lowest level from each hierarchy.
        feature_inputs (List[str], optional): List of query names of inputs features in the input order.
            Defaults to None to use the column names used when training the model.
    """
    model_utils._perspective_check(data_model)
    project_helpers._check_published(data_model.project)

    inspection = getfullargspec(write_linear_regression_model)
    validation_utils.validate_by_type_hints(inspection=inspection, func_params=locals())

    prediction_utils._write_regression_model(
        enums.ScikitLearnModelType.LINEARREGRESSION,
        data_model,
        regression_model,
        new_feature_name,
        feature_inputs,
        granularity_levels,
    )


def write_logistic_regression_model(
    data_model: DataModel,
    regression_model,
    new_feature_name: str,
    granularity_levels: List[str] = None,
    feature_inputs: List[str] = None,
):
    """Writes a scikit-learn binary LogisticRegression model, which takes AtScale features exclusively as input, to the given
    Published DataModel as a sum aggregated feature with the given name. The feature will return the output of the coefficients
    and intercept in the model applied to feature_inputs as defined in AtScale. Omitting feature_inputs will use the
    names of the columns passed at training time and error if any names are not in the data model.

    Args:
        data_model (DataModel): The AtScale DataModel to add the regression into.
        regression_model (LogisticRegression): The scikit-learn LogisticRegression model to build into a feature.
        new_feature_name (str): The query name of the created feature.
        granularity_levels (List[str], optional): List of the query names for the lowest categorical levels that predictions with this
            model can be run on. Defaults to False to use the lowest level from each hierarchy.
        feature_inputs (List[str], optional): List of query names of inputs features in the input order.
            Defaults to None to use the column names used when training the model.
    """
    model_utils._perspective_check(data_model)
    project_helpers._check_published(data_model.project)

    inspection = getfullargspec(write_logistic_regression_model)
    validation_utils.validate_by_type_hints(inspection=inspection, func_params=locals())

    # NOTE: Function only supports binary classification; AI-Link has not implemented multiclass support yet. We only support
    # binary classification until customer feedback indicates multiclass would be of use, as it is non-trivial to expand the logic.
    if len(regression_model.classes_) > 2:
        raise ValueError(
            f"write_logistic_regression_model only supports binary classification; model: "
            f"{regression_model} has more than two classes"
        )

    prediction_utils._write_regression_model(
        enums.ScikitLearnModelType.LOGISTICREGRESSION,
        data_model,
        regression_model,
        new_feature_name,
        feature_inputs,
        granularity_levels,
    )
