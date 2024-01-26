import copy
import inspect
from typing import List, Union
from atscale.data_model.data_model import DataModel
from atscale.base.enums import (
    Hierarchy,
    Level,
    TimeSteps,
    FeatureType,
    CheckFeaturesErrMsg,
    FeatureFormattingType,
)
from atscale.errors import atscale_errors
from atscale.utils import validation_utils
from atscale.utils.dmv_utils import get_dmv_data
from atscale.parsers import dictionary_parser as dparse
from atscale.data_model import data_model_helpers as dmh
from atscale.utils.feature_utils import (
    _check_time_hierarchy,
    _create_calculated_feature,
    _get_cov_str,
    _get_corr_str,
    _check_hierarchy,
)
from atscale.utils.model_utils import (
    _check_features,
    _check_conflicts,
    _perspective_check,
)
from inspect import getfullargspec
from atscale.utils.validation_utils import validate_by_type_hints
from pandas import DataFrame
from atscale.utils.metadata_utils import _get_dimension_and_lowest_hierarchy_level


def create_one_hot_encoded_features(
    data_model: DataModel,
    categorical_feature: str,
    hierarchy_name: str = None,
    description: str = None,
    folder: str = None,
    format_string: Union[FeatureFormattingType, str] = None,
    publish: bool = True,
) -> List[str]:
    """Creates a one hot encoded feature for each value in the given categorical feature

    Args:
        data_model (DataModel): The data model to add the features to.
        categorical_feature (str): The query name of the categorical feature to pull the values from.
        hierarchy_name (str, optional): The query name of the hierarchy to use for the feature. Only necessary if the feature is duplicated in multiple hierarchies.
        description (str, optional): A description to add to the new features. Defaults to None.
        folder (str, optional): The folder to put the new features in. Defaults to None.
        format_string (Union[FeatureFormattingType, str], optional): A format sting for the new features. Defaults to None.
        publish (bool, optional): Whether to publish the project after creating the features. Defaults to True.

    Returns:
        List[str]: The query names of the newly created features
    """
    # check if the provided data_model is a perspective
    _perspective_check(data_model)

    inspection = getfullargspec(create_one_hot_encoded_features)
    validate_by_type_hints(inspection=inspection, func_params=locals())

    project_dict = data_model.project._get_dict()
    draft_features = dmh._get_draft_features(
        project_dict=project_dict,
        data_model_name=data_model.name,
        feature_type=FeatureType.ALL,
    )

    # TO DO: Add in hierarchy checking here

    # Check to see that features passed exist in first place
    _check_features(
        features=[categorical_feature],
        check_list=draft_features,
        errmsg=CheckFeaturesErrMsg.ALL.get_errmsg(is_published=False),
    )

    # Check to see that features passed are categorical
    draft_measures = dparse.filter_dict(
        to_filter=draft_features,
        val_filters=[lambda i: i["feature_type"] == FeatureType.CATEGORICAL.name_val],
    )

    _check_features(
        features=[categorical_feature],
        check_list=draft_measures,
        errmsg=CheckFeaturesErrMsg.CATEGORICAL.get_errmsg(is_published=False),
    )

    filter_by = {Level.name: [categorical_feature]}
    if hierarchy_name:
        filter_by[Level.hierarchy] = [hierarchy_name]
    level_heritage = get_dmv_data(
        model=data_model, fields=[Level.dimension, Level.hierarchy], filter_by=filter_by
    )

    if len(level_heritage) == 0:
        raise atscale_errors.UserError(f"Level: {categorical_feature} does not exist in the model")
    dimension = level_heritage[categorical_feature][Level.dimension.name]
    hierarchy = level_heritage[categorical_feature][Level.hierarchy.name]
    df_values = data_model.get_data([categorical_feature], gen_aggs=False)
    project_json = data_model.project._get_dict()
    original_proj_dict = copy.deepcopy(
        project_json
    )  # need to check that the new names were free BEFORE adding them
    created_names = []
    for value in df_values[categorical_feature].values:
        expression = f'IIF(ANCESTOR([{dimension}].[{hierarchy}].CurrentMember, [{dimension}].[{hierarchy}].[{categorical_feature}]).MEMBER_NAME="{value}",1,0)'
        name = f"{categorical_feature}_{value}"
        created_names.append(name)
        _create_calculated_feature(
            project_json,
            data_model.cube_id,
            name,
            expression,
            description=description,
            caption=None,
            folder=folder,
            format_string=format_string,
        )

    _check_conflicts(to_add=created_names, data_model=data_model, project_dict=original_proj_dict)
    data_model.project._update_project(project_json=project_json, publish=publish)
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
    format_string: Union[FeatureFormattingType, str] = None,
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
        format_string (Union[FeatureFormattingType, str], optional): The format string for the feature. Defaults to None.
        visible (bool, optional): Whether the feature will be visible to BI tools. Defaults to True.
        publish (bool, optional): Whether or not the updated project should be published. Defaults to True.
    """
    # check if the provided data_model is a perspective
    _perspective_check(data_model)

    inspection = getfullargspec(create_percent_change)
    validate_by_type_hints(inspection=inspection, func_params=locals())

    proj_dict = data_model.project._get_dict()

    # Check to see that features passed exist in first place
    _check_features(
        features=[numeric_feature_name],
        check_list=dmh._get_draft_features(
            project_dict=proj_dict,
            data_model_name=data_model.name,
            feature_type=FeatureType.ALL,
        ),
        errmsg=CheckFeaturesErrMsg.ALL.get_errmsg(is_published=False),
    )

    # Check to see that features passed are numeric
    _check_features(
        features=[numeric_feature_name],
        check_list=dmh._get_draft_features(
            project_dict=proj_dict,
            data_model_name=data_model.name,
            feature_type=FeatureType.NUMERIC,
        ),
        errmsg=CheckFeaturesErrMsg.NUMERIC.get_errmsg(is_published=False),
    )

    if not (type(time_length) == int) or time_length <= 0:
        raise ValueError(
            f"Invalid parameter value '{time_length}', Length must be an integer greater than zero"
        )

    hier_dict, _ = _check_time_hierarchy(
        data_model=data_model, hierarchy_name=hierarchy_name, level_name=level_name
    )

    time_dimension = hier_dict[hierarchy_name][Hierarchy.dimension.name]

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
    format_string: Union[FeatureFormattingType, str] = None,
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
        format_string (Union[FeatureFormattingType, str], optional): The format string for the feature. Defaults to None.
        visible (bool, optional): Whether the feature will be visible to BI tools. Defaults to True.
        publish (bool, optional): Whether or not the updated project should be published. Defaults to True.
    """
    # check if the provided data_model is a perspective
    _perspective_check(data_model)

    inspection = getfullargspec(create_period_to_date)
    validate_by_type_hints(inspection=inspection, func_params=locals())

    project_json = data_model.project._get_dict()
    existing_features = dmh._get_draft_features(
        project_dict=project_json, data_model_name=data_model.name
    )
    existing_measures = dparse.filter_dict(
        to_filter=existing_features,
        val_filters=[lambda i: i["feature_type"] == FeatureType.NUMERIC.name_val],
    )

    # Check to see that features passed exist in first place
    _check_features(
        features=[numeric_feature_name],
        check_list=existing_features,
        errmsg=CheckFeaturesErrMsg.ALL.get_errmsg(is_published=False),
    )

    # Check to see that features passed are numeric
    _check_features(
        features=[numeric_feature_name],
        check_list=existing_measures,
        errmsg=CheckFeaturesErrMsg.NUMERIC.get_errmsg(is_published=False),
    )

    _check_conflicts(to_add=new_feature_name, preexisting=existing_features)

    hier_dict, level_dict = _check_time_hierarchy(
        data_model=data_model, hierarchy_name=hierarchy_name, level_name=level_name
    )

    time_dimension = hier_dict[hierarchy_name][Hierarchy.dimension.name]

    expression = (
        f"CASE WHEN IsEmpty([Measures].[{numeric_feature_name}]) THEN NULL ELSE "
        f"Sum(PeriodsToDate([{time_dimension}].[{hierarchy_name}].[{level_name}], "
        f"[{time_dimension}].[{hierarchy_name}].CurrentMember), [Measures].[{numeric_feature_name}]) END"
    )

    cube_id = data_model.cube_id
    _create_calculated_feature(
        project_json,
        cube_id,
        new_feature_name,
        expression,
        description=description,
        caption=caption,
        folder=folder,
        format_string=format_string,
        visible=visible,
    )
    data_model.project._update_project(project_json=project_json, publish=publish)


def create_pct_error_calculation(
    data_model: DataModel,
    new_feature_name: str,
    predicted_feature_name: str,
    actual_feature_name: str,
    description: str = None,
    caption: str = None,
    folder: str = None,
    format_string: Union[FeatureFormattingType, str] = None,
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
        format_string (Union[FeatureFormattingType, str], optional): The format string for the feature. Defaults to None.
        visible (bool, optional): Whether the feature will be visible to BI tools. Defaults to True.
        publish (bool, optional): Whether or not the updated project should be published. Defaults to True.
    """
    # check if the provided data_model is a perspective
    _perspective_check(data_model)

    inspection = getfullargspec(create_pct_error_calculation)
    validate_by_type_hints(inspection=inspection, func_params=locals())

    proj_dict = data_model.project._get_dict()

    numerics = dmh._get_draft_features(
        project_dict=proj_dict,
        data_model_name=data_model.name,
        feature_type=FeatureType.NUMERIC,
    ).keys()

    # Check to see that features passed exist in first place
    _check_features(
        features=[predicted_feature_name, actual_feature_name],
        check_list=dmh._get_draft_features(
            project_dict=proj_dict,
            data_model_name=data_model.name,
            feature_type=FeatureType.ALL,
        ),
        errmsg=CheckFeaturesErrMsg.ALL.get_errmsg(is_published=False),
    )

    # Check to see that features passed are numeric
    _check_features(
        features=[predicted_feature_name, actual_feature_name],
        check_list=numerics,
        errmsg=CheckFeaturesErrMsg.NUMERIC.get_errmsg(is_published=False),
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
    format_string: Union[FeatureFormattingType, str] = None,
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
        format_string (Union[FeatureFormattingType, str], optional): The format string for the feature. Defaults to None.
        visible (bool, optional): Whether the feature will be visible to BI tools. Defaults to True.
        publish (bool, optional): Whether or not the updated project should be published. Defaults to True.
    """
    # check if the provided data_model is a perspective
    _perspective_check(data_model)

    inspection = getfullargspec(create_scaled_feature_minmax)
    validate_by_type_hints(inspection=inspection, func_params=locals())

    project_dict = data_model.project._get_dict()
    draft_features = dmh._get_draft_features(
        project_dict=project_dict,
        data_model_name=data_model.name,
        feature_type=FeatureType.ALL,
    )

    # Check to see that features passed exist in first place
    _check_features(
        features=[numeric_feature_name],
        check_list=draft_features,
        errmsg=CheckFeaturesErrMsg.ALL.get_errmsg(is_published=False),
    )

    # Check to see that features passed are numeric
    draft_measures = dparse.filter_dict(
        to_filter=draft_features,
        val_filters=[lambda i: i["feature_type"] == FeatureType.NUMERIC.name_val],
    )

    _check_features(
        features=[numeric_feature_name],
        check_list=draft_measures,
        errmsg=CheckFeaturesErrMsg.NUMERIC.get_errmsg(is_published=False),
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
    format_string: Union[FeatureFormattingType, str] = None,
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
        format_string (Union[FeatureFormattingType, str], optional): The format string for the feature. Defaults to None.
        visible (bool, optional): Whether the feature will be visible to BI tools. Defaults to True.
        publish (bool, optional): Whether or not the updated project should be published. Defaults to True.
    """
    # check if the provided data_model is a perspective
    _perspective_check(data_model)

    inspection = getfullargspec(create_scaled_feature_z_score)
    validate_by_type_hints(inspection=inspection, func_params=locals())

    project_dict = data_model.project._get_dict()
    draft_features = dmh._get_draft_features(
        project_dict=project_dict,
        data_model_name=data_model.name,
        feature_type=FeatureType.ALL,
    )

    # Check to see that features passed exist in first place
    _check_features(
        features=[numeric_feature_name],
        check_list=draft_features,
        errmsg=CheckFeaturesErrMsg.ALL.get_errmsg(is_published=False),
    )

    # Check to see that features passed are numeric
    draft_measures = dparse.filter_dict(
        to_filter=draft_features,
        val_filters=[lambda i: i["feature_type"] == FeatureType.NUMERIC.name_val],
    )

    _check_features(
        features=[numeric_feature_name],
        check_list=draft_measures,
        errmsg=CheckFeaturesErrMsg.NUMERIC.get_errmsg(is_published=False),
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
    format_string: Union[FeatureFormattingType, str] = None,
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
        format_string (Union[FeatureFormattingType, str], optional): The format string for the feature. Defaults to None.
        visible (bool, optional): Whether the feature will be visible to BI tools. Defaults to True.
        publish (bool, optional): Whether or not the updated project should be published. Defaults to True.
    """
    # check if the provided data_model is a perspective
    _perspective_check(data_model)

    inspection = getfullargspec(create_scaled_feature_maxabs)
    validate_by_type_hints(inspection=inspection, func_params=locals())

    project_dict = data_model.project._get_dict()
    draft_features = dmh._get_draft_features(
        project_dict=project_dict,
        data_model_name=data_model.name,
        feature_type=FeatureType.ALL,
    )

    # Check to see that features passed exist in first place
    _check_features(
        features=[numeric_feature_name],
        check_list=draft_features,
        errmsg=CheckFeaturesErrMsg.ALL.get_errmsg(is_published=False),
    )

    # Check to see that features passed are numeric
    draft_measures = dparse.filter_dict(
        to_filter=draft_features,
        val_filters=[lambda i: i["feature_type"] == FeatureType.NUMERIC.name_val],
    )

    _check_features(
        features=[numeric_feature_name],
        check_list=draft_measures,
        errmsg=CheckFeaturesErrMsg.NUMERIC.get_errmsg(is_published=False),
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
    format_string: Union[FeatureFormattingType, str] = None,
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
        format_string (Union[FeatureFormattingType, str], optional): The format string for the feature. Defaults to None.
        visible (bool, optional): Whether the feature will be visible to BI tools. Defaults to True.
        publish (bool, optional): Whether or not the updated project should be published. Defaults to True.
    """
    # check if the provided data_model is a perspective
    _perspective_check(data_model)

    inspection = getfullargspec(create_scaled_feature_robust)
    validate_by_type_hints(inspection=inspection, func_params=locals())

    project_dict = data_model.project._get_dict()
    draft_features = dmh._get_draft_features(
        project_dict=project_dict,
        data_model_name=data_model.name,
        feature_type=FeatureType.ALL,
    )

    # Check to see that features passed exist in first place
    _check_features(
        features=[numeric_feature_name],
        check_list=draft_features,
        errmsg=CheckFeaturesErrMsg.ALL.get_errmsg(is_published=False),
    )

    # Check to see that features passed are numeric
    draft_measures = dparse.filter_dict(
        to_filter=draft_features,
        val_filters=[lambda i: i["feature_type"] == FeatureType.NUMERIC.name_val],
    )

    _check_features(
        features=[numeric_feature_name],
        check_list=draft_measures,
        errmsg=CheckFeaturesErrMsg.NUMERIC.get_errmsg(is_published=False),
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
    format_string: Union[FeatureFormattingType, str] = None,
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
        format_string (Union[FeatureFormattingType, str], optional): The format string for the feature. Defaults to None.
        visible (bool, optional): Whether the feature will be visible to BI tools. Defaults to True.
        publish (bool, optional): Whether or not the updated project should be published. Defaults to True.
    """
    # check if the provided data_model is a perspective
    _perspective_check(data_model)

    inspection = getfullargspec(create_scaled_feature_log_transformed)
    validate_by_type_hints(inspection=inspection, func_params=locals())

    project_dict = data_model.project._get_dict()
    draft_features = dmh._get_draft_features(
        project_dict=project_dict,
        data_model_name=data_model.name,
        feature_type=FeatureType.ALL,
    )

    # Check to see that features passed exist in first place
    _check_features(
        features=[numeric_feature_name],
        check_list=draft_features,
        errmsg=CheckFeaturesErrMsg.ALL.get_errmsg(is_published=False),
    )

    # Check to see that features passed are numeric
    draft_measures = dparse.filter_dict(
        to_filter=draft_features,
        val_filters=[lambda i: i["feature_type"] == FeatureType.NUMERIC.name_val],
    )

    _check_features(
        features=[numeric_feature_name],
        check_list=draft_measures,
        errmsg=CheckFeaturesErrMsg.NUMERIC.get_errmsg(is_published=False),
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
    format_string: Union[FeatureFormattingType, str] = None,
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
        format_string (Union[FeatureFormattingType, str], optional): The format string for the feature. Defaults to None.
        visible (bool, optional): Whether the feature will be visible to BI tools. Defaults to True.
        publish (bool, optional): Whether or not the updated project should be published. Defaults to True.
    """
    # check if the provided data_model is a perspective
    _perspective_check(data_model)

    inspection = getfullargspec(create_scaled_feature_unit_vector_norm)
    validate_by_type_hints(inspection=inspection, func_params=locals())

    project_dict = data_model.project._get_dict()
    draft_features = dmh._get_draft_features(
        project_dict=project_dict,
        data_model_name=data_model.name,
        feature_type=FeatureType.ALL,
    )

    # Check to see that features passed exist in first place
    _check_features(
        features=[numeric_feature_name],
        check_list=draft_features,
        errmsg=CheckFeaturesErrMsg.ALL.get_errmsg(is_published=False),
    )

    # Check to see that features passed are numeric
    draft_measures = dparse.filter_dict(
        to_filter=draft_features,
        val_filters=[lambda i: i["feature_type"] == FeatureType.NUMERIC.name_val],
    )

    _check_features(
        features=[numeric_feature_name],
        check_list=draft_measures,
        errmsg=CheckFeaturesErrMsg.NUMERIC.get_errmsg(is_published=False),
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
    format_string: Union[FeatureFormattingType, str] = None,
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
        format_string (Union[FeatureFormattingType, str], optional): The format string for the feature. Defaults to None.
        visible (bool, optional): Whether the feature will be visible to BI tools. Defaults to True.
        publish (bool, optional): Whether or not the updated project should be published. Defaults to True.

    Raises:
        atscale_errors.UserError: User must pass either of two valid power transformation methods
    """
    # check if the provided data_model is a perspective
    _perspective_check(data_model)

    inspection = getfullargspec(create_scaled_feature_power_transformed)
    validate_by_type_hints(inspection=inspection, func_params=locals())

    project_dict = data_model.project._get_dict()
    draft_features = dmh._get_draft_features(
        project_dict=project_dict,
        data_model_name=data_model.name,
        feature_type=FeatureType.ALL,
    )

    # Check to see that features passed exist in first place
    _check_features(
        features=[numeric_feature_name],
        check_list=draft_features,
        errmsg=CheckFeaturesErrMsg.ALL.get_errmsg(is_published=False),
    )

    # Check to see that features passed are numeric
    draft_measures = dparse.filter_dict(
        to_filter=draft_features,
        val_filters=[lambda i: i["feature_type"] == FeatureType.NUMERIC.name_val],
    )

    _check_features(
        features=[numeric_feature_name],
        check_list=draft_measures,
        errmsg=CheckFeaturesErrMsg.NUMERIC.get_errmsg(is_published=False),
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
    format_string: Union[FeatureFormattingType, str] = None,
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
        format_string (Union[FeatureFormattingType, str], optional): The format string for the feature. Defaults to None.
        visible (bool, optional): Whether the created feature will be visible to BI tools. Defaults to True.
        publish (bool, optional): Whether or not the updated project should be published. Defaults to True.
    """
    # check if the provided data_model is a perspective
    _perspective_check(data_model)

    inspection = getfullargspec(create_net_error_calculation)
    validate_by_type_hints(inspection=inspection, func_params=locals())

    project_dict = data_model.project._get_dict()
    measure_list = dmh._get_draft_features(
        project_dict=project_dict,
        data_model_name=data_model.name,
        feature_type=FeatureType.NUMERIC,
    )

    # Check to see that features passed exist in first place
    _check_features(
        features=[predicted_feature_name, actual_feature_name],
        check_list=dmh._get_draft_features(
            project_dict=project_dict,
            data_model_name=data_model.name,
            feature_type=FeatureType.ALL,
        ),
        errmsg=CheckFeaturesErrMsg.ALL.get_errmsg(is_published=False),
    )

    # Check to see that features passed are numeric
    _check_features(
        features=[predicted_feature_name, actual_feature_name],
        check_list=measure_list,
        errmsg=CheckFeaturesErrMsg.NUMERIC.get_errmsg(is_published=False),
    )

    level_list = dmh._get_draft_features(
        project_dict=project_dict,
        data_model_name=data_model.name,
        feature_type=FeatureType.CATEGORICAL,
    )
    preexisting = measure_list
    preexisting.update(level_list)
    _check_conflicts(to_add=new_feature_name, preexisting=preexisting)

    expression = f"[Measures].[{predicted_feature_name}] - [Measures].[{actual_feature_name}]"
    _create_calculated_feature(
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
    data_model.project._update_project(project_json=project_dict, publish=publish)


def create_binned_feature(
    data_model: DataModel,
    new_feature_name: str,
    numeric_feature_name: str,
    bin_edges: List[float],
    description: str = None,
    caption: str = None,
    folder: str = None,
    format_string: Union[FeatureFormattingType, str] = None,
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
        format_string (Union[FeatureFormattingType, str], optional): The format string for the feature. Defaults to None.
        visible (bool, optional): Whether the created feature will be visible to BI tools. Defaults to True.
        publish (bool, optional): Whether or not the updated project should be published. Defaults to True.
    """
    # check if the provided data_model is a perspective
    _perspective_check(data_model)

    inspection = getfullargspec(create_binned_feature)
    validate_by_type_hints(inspection=inspection, func_params=locals())

    project_dict = data_model.project._get_dict()
    draft_features = dmh._get_draft_features(
        project_dict=project_dict,
        data_model_name=data_model.name,
        feature_type=FeatureType.ALL,
    )

    # Check to see that features passed exist in first place
    _check_features(
        features=[numeric_feature_name],
        check_list=draft_features,
        errmsg=CheckFeaturesErrMsg.ALL.get_errmsg(is_published=False),
    )

    # Check to see that features passed are numeric
    draft_measures = dparse.filter_dict(
        to_filter=draft_features,
        val_filters=[lambda i: i["feature_type"] == FeatureType.NUMERIC.name_val],
    )

    _check_features(
        features=[numeric_feature_name],
        check_list=draft_measures,
        errmsg=CheckFeaturesErrMsg.NUMERIC.get_errmsg(is_published=False),
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
    _perspective_check(data_model)

    inspection = getfullargspec(create_covariance_feature)
    validate_by_type_hints(inspection=inspection, func_params=locals())

    all_published_features = dmh._get_published_features(data_model=data_model)

    # Check to see that features passed are numeric
    all_numeric_features = dparse.filter_dict(
        to_filter=all_published_features,
        val_filters=[lambda i: i["feature_type"] == FeatureType.NUMERIC.name_val],
    )

    # Check that features exist in the first place
    _check_features(
        features=[numeric_feature_1_name, numeric_feature_2_name],
        check_list=all_published_features,
        errmsg=CheckFeaturesErrMsg.ALL.get_errmsg(is_published=True),
    )

    # Check that numeric features are indeed numeric
    _check_features(
        features=[numeric_feature_1_name, numeric_feature_2_name],
        check_list=all_numeric_features,
        errmsg=CheckFeaturesErrMsg.NUMERIC.get_errmsg(is_published=True),
    )

    _check_hierarchy(
        data_model=data_model,
        hierarchy_name=hierarchy_name,
        level_name=None,
    )

    dimension, leaf = _get_dimension_and_lowest_hierarchy_level(
        data_model=data_model,
        hierarchy_name=hierarchy_name,
    )

    expr = _get_cov_str(
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
    _perspective_check(data_model)

    inspection = getfullargspec(create_correlation_feature)
    validate_by_type_hints(inspection=inspection, func_params=locals())

    all_published_features = dmh._get_published_features(data_model=data_model)

    # Check to see that features passed are numeric
    all_numeric_features = dparse.filter_dict(
        to_filter=all_published_features,
        val_filters=[lambda i: i["feature_type"] == FeatureType.NUMERIC.name_val],
    )

    # Check that features exist in the first place
    _check_features(
        features=[numeric_feature_1_name, numeric_feature_2_name],
        check_list=all_published_features,
        errmsg=CheckFeaturesErrMsg.ALL.get_errmsg(is_published=True),
    )

    # Check that numeric features are indeed numeric
    _check_features(
        features=[numeric_feature_1_name, numeric_feature_2_name],
        check_list=all_numeric_features,
        errmsg=CheckFeaturesErrMsg.NUMERIC.get_errmsg(is_published=True),
    )

    _check_hierarchy(
        data_model=data_model,
        hierarchy_name=hierarchy_name,
        level_name=None,
    )

    dimension, leaf = _get_dimension_and_lowest_hierarchy_level(
        data_model=data_model,
        hierarchy_name=hierarchy_name,
    )

    expr = _get_corr_str(
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
):
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
    validate_by_type_hints(inspection=inspection, func_params=locals())

    # validate the non-null inputs
    validation_utils.validate_required_params_not_none(
        local_vars=locals(),
        inspection=inspect.getfullargspec(generate_time_series_features),
    )

    _, level_dict = _check_time_hierarchy(
        data_model=data_model, hierarchy_name=time_hierarchy, level_name=level
    )

    all_published_features = dmh._get_published_features(data_model=data_model)

    # Check to see that features passed are numeric
    measure_list = list(
        dparse.filter_dict(
            to_filter=all_published_features,
            val_filters=[lambda i: i["feature_type"] == FeatureType.NUMERIC.name_val],
        ).keys()
    )

    categorical_list = list(
        dparse.filter_dict(
            to_filter=all_published_features,
            val_filters=[lambda i: i["feature_type"] == FeatureType.CATEGORICAL.name_val],
        ).keys()
    )

    level_list = level_dict
    if group_features:
        # Check to see that features passed exist in first place
        _check_features(
            features=group_features,
            check_list=all_published_features,
            errmsg=CheckFeaturesErrMsg.ALL.get_errmsg(is_published=True),
        )

        # Check to see that features passed are categorical
        _check_features(
            features=group_features,
            check_list=categorical_list,
            errmsg=CheckFeaturesErrMsg.CATEGORICAL.get_errmsg(is_published=True),
        )

    # Check to see that features passed exist in first place
    _check_features(
        features=numeric_features,
        check_list=all_published_features,
        errmsg=CheckFeaturesErrMsg.ALL.get_errmsg(is_published=True),
    )

    # Check to see that features passed are numeric
    _check_features(
        features=numeric_features,
        check_list=measure_list,
        errmsg=CheckFeaturesErrMsg.NUMERIC.get_errmsg(is_published=True),
    )

    time_numeric = level_dict[level][Level.type.name]
    # takes out the Time and 's' at the end and in lowercase
    time_name = str(time_numeric)[4:-1].lower()

    if intervals:
        if type(intervals) != list:
            intervals = [intervals]
    else:
        intervals = TimeSteps[time_numeric].get_steps()

    shift_name = f"_shift_{shift_amount}" if shift_amount != 0 else ""

    levels = [x for x in level_list if x in dataframe.columns]

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

        #a helper function for the agg chaining
        def groupby_chain(dataframe_n, feature_n, group_func, shift_amt, roll_interval, agg_func):
            if shift_amount != 0:
                func_to_exec = getattr(group_func(dataframe_n)[feature_n].shift(shift_amt).rolling(roll_interval), agg_func)
                return func_to_exec().reset_index(drop = True)
            else:
                func_to_exec = getattr(group_func(dataframe_n)[feature_n].rolling(roll_interval), agg_func)
                return func_to_exec().reset_index(drop = True)
    
        for interval in intervals:
            interval = int(interval)
            name = feature + f"_{interval}_{time_name}_"

            if interval > 1:
                dataframe[f"{name}sum{shift_name}"] = groupby_chain(dataframe, 
                                                                    feature, 
                                                                    grouper, 
                                                                    shift_amount, 
                                                                    interval, 
                                                                    'sum')


                dataframe[f"{name}avg{shift_name}"] = groupby_chain(dataframe, 
                                                                    feature, 
                                                                    grouper, 
                                                                    shift_amount, 
                                                                    interval, 
                                                                    'mean')

                dataframe[f"{name}stddev{shift_name}"] = groupby_chain(dataframe, 
                                                                    feature, 
                                                                    grouper, 
                                                                    shift_amount, 
                                                                    interval, 
                                                                    'std')

                dataframe[f"{name}min{shift_name}"] = groupby_chain(dataframe, 
                                                                    feature, 
                                                                    grouper, 
                                                                    shift_amount, 
                                                                    interval, 
                                                                    'min')

                dataframe[f"{name}max{shift_name}"] = groupby_chain(dataframe, 
                                                                    feature, 
                                                                    grouper, 
                                                                    shift_amount, 
                                                                    interval, 
                                                                    'max')

            dataframe[f"{name}lag{shift_name}"] = (
                grouper(dataframe)[feature]
                .shift(shift_amount + interval)
                .reset_index(drop=True)
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
