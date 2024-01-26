from copy import deepcopy
import inspect
from typing import List, Dict, Callable
from atscale.connection.connection import _Connection

from atscale.errors import atscale_errors
from atscale.utils import model_utils, project_utils, validation_utils
from atscale.parsers import project_parser


def supported_bulk_operations(
    function_to_check: Callable,
) -> Callable:
    """Checks if a function has a bulk operator, if it does then we return the function.
    If not, return None.

    Args:
        function_to_check (Callable): The single operation function to bulk operate

    Returns:
        Callable: The bulk operation version of the passed function
    """
    from atscale.data_model import DataModel

    supported_dict = {
        DataModel.create_aggregate_feature: bulk_create_aggregate_feature,
        DataModel.create_calculated_column: bulk_create_calculated_column,
        DataModel.create_calculated_feature: bulk_create_calculated_feature,
    }
    return supported_dict.get(function_to_check, None)


def bulk_create_aggregate_feature(
    atconn: _Connection,
    project_dict: Dict,
    feature_dict: Dict,
    data_model_id: str,
    parameter_list: List[Dict],
    error_limit=5,
):
    """The bulk function caller for create_aggregate_feature

    Args:
        atconn (_Connection): an AtScale connection
        project_dict (Dict): The project_dict to mutate
        feature_dict (Dict): The dictionary of current features in the model
        data_model_id (str): The data_model_id to add to
        parameter_list (List[Dict]): The set of parameters to validate and run
        error_limit (int): The maximum number of similar errors to collect before abbreviating.
    """
    from atscale.data_model import DataModel
    from atscale.utils.feature_utils import _create_aggregate_feature

    inspection = inspect.getfullargspec(DataModel.create_aggregate_feature)
    # don't want to edit the dictionary they passed in
    working_parameter_list = deepcopy(parameter_list)
    # check our inputs are valid for the function we intend to call
    validation_utils.validate_all_expected_params_bulk(
        passed_vars=working_parameter_list, inspection=inspection
    )
    feature_name_column = "new_feature_name"
    # check that no duplicate names were passed in
    features_to_create = [x.get(feature_name_column) for x in working_parameter_list]
    dupes_found = validation_utils.validate_no_duplicates_in_list(features_to_create)
    if dupes_found:
        starting_err_msg = (
            f"The following duplicated {feature_name_column} parameters were passed. "
            f"This parameter must be unique."
        )
        counter = 0
        for dupe in dupes_found:
            if counter >= error_limit:
                counter += 1
                break
            counter += 1
            starting_err_msg += f"\n\t{feature_name_column} parameter {dupe} appeared at indices: {dupes_found[dupe]}"
        if counter >= error_limit:
            starting_err_msg += f"\n\t{len(dupes_found) - counter} more duplicates"
        raise atscale_errors.UserError(starting_err_msg)

    # check that there will not be name collisions with the created
    existing_query_names_index = [
        (index, value) for index, value in enumerate(features_to_create) if value in feature_dict
    ]
    if existing_query_names_index:
        starting_err_msg = (
            f"The following {feature_name_column} parameters were passed that collide with an "
            f"existing feature in the Data Model."
        )
        counter = 0
        for existing_value in existing_query_names_index:
            if counter >= error_limit:
                counter += 1
                break
            counter += 1
            starting_err_msg += f"\n\t{feature_name_column} parameter {existing_value[1]} appeared at index: {existing_value[0]}"
        if counter >= error_limit:
            starting_err_msg += f"And \n\t{len(existing_query_names_index) -counter} more collisions hidden after exceeding error_limit"
        raise atscale_errors.UserError(starting_err_msg)

    # cube_dict for dataset and column validation
    data_model_dict = project_parser.get_data_model(project_dict, data_model_id)
    invalid_datasets = {}
    invalid_columns = {}
    valid_datasets = {}
    for index, parameter_dict in enumerate(working_parameter_list):
        dataset_of_int = parameter_dict["fact_dataset_name"]
        column_of_int = parameter_dict["column_name"]

        if dataset_of_int in valid_datasets:
            if column_of_int not in valid_datasets[dataset_of_int]["cols"]:
                invalid_columns[index] = (column_of_int, dataset_of_int)
                continue
        elif dataset_of_int in invalid_datasets.values():
            invalid_datasets[index] = dataset_of_int
            continue
        else:
            dset = model_utils._get_fact_dataset(
                data_model_dict, project_dict, dataset_name=dataset_of_int
            )
            if not dset:
                invalid_datasets[index] = dataset_of_int
                continue
            else:
                dset_columns = list(
                    model_utils._get_columns(
                        project_dict=project_dict, dataset_name=dataset_of_int
                    ).keys()
                )
                if column_of_int not in dset_columns:
                    invalid_columns[index] = (column_of_int, dataset_of_int)
                    continue
                valid_datasets[dataset_of_int] = {
                    "id": dset["id"],
                    "cols": dset_columns,
                }

        parameter_dict["dataset_id"] = valid_datasets[dataset_of_int]["id"]

    # raise the appropriate errors
    if invalid_datasets:
        starting_err_msg = "The following fact_dataset_name parameters were passed that do not exist in the Data Model."
        counter = 0
        for index_val, dataset in invalid_datasets.items():
            if counter >= error_limit:
                counter += 1
                break
            counter += 1
            starting_err_msg += f"\n\tFact Dataset {dataset} appeared at index: {index_val}"
        if counter >= error_limit:
            starting_err_msg += f"\n\t{len(invalid_datasets.items()) - counter} more errors"
        raise atscale_errors.UserError(starting_err_msg)
    if invalid_columns:
        starting_err_msg = (
            "The following column_name parameters were passed do not exist in the given dataset."
        )
        counter = 0
        for index_val, values in invalid_columns.items():
            if counter >= error_limit:
                counter += 1
                break
            counter += 1
            starting_err_msg += (
                f"\n\tColumn {values[0]} in dataset {values[1]} appeared at index: {index_val}"
            )

        if counter >= error_limit:
            starting_err_msg += f"\n\t{len(invalid_columns.items()) - counter} more columns"
        raise atscale_errors.UserError(starting_err_msg)

    # call the underlying function
    for parameter_dict in working_parameter_list:
        parameter_dict["project_dict"] = project_dict
        parameter_dict["cube_id"] = data_model_id
        parameter_dict.pop("fact_dataset_name", "")
        parameter_dict.pop("publish", "")
        # left off here, need to test passing with ** and make sure it checks the key names as param names
        _create_aggregate_feature(**parameter_dict)


def bulk_create_calculated_column(
    atconn: _Connection,
    project_dict: Dict,
    feature_dict: Dict,
    data_model_id: str,
    parameter_list: List[Dict],
    error_limit=5,
):
    """The bulk function caller for create_calculated_column

    Args:
        atconn (_Connection): an AtScale connection
        project_dict (Dict): The project_dict to mutate
        feature_dict (Dict): The dictionary of current features in the model
        data_model_id (str): The data_model_id to add to
        parameter_list (List[Dict]): The set of parameters to validate and run
        error_limit (int): The maximum number of similar errors to collect before abbreviating.
    """
    from atscale.data_model import DataModel
    from atscale.utils.project_utils import add_calculated_column_to_project_dataset

    inspection = inspect.getfullargspec(DataModel.create_calculated_column)

    # don't want to edit the dictionary they passed in
    working_parameter_list = deepcopy(parameter_list)
    # check our inputs are valid for the function we intend to call
    validation_utils.validate_all_expected_params_bulk(
        passed_vars=working_parameter_list, inspection=inspection
    )

    feature_name_column = "column_name"
    # check that no duplicate names were passed in
    features_to_create = [x.get(feature_name_column) for x in working_parameter_list]
    dupes_found = validation_utils.validate_no_duplicates_in_list(features_to_create)

    if dupes_found:
        starting_err_msg = (
            f"The following duplicated {feature_name_column} parameters were passed. "
            f"This parameter must be unique."
        )
        counter = 0
        for dupe in dupes_found:
            if counter >= error_limit:
                counter += 1
                break
            counter += 1
            starting_err_msg += f"\n\t{feature_name_column} parameter {dupe} appeared at indices: {dupes_found[dupe]}"
        if counter >= error_limit:
            starting_err_msg += f"\n\t{len(dupes_found) - counter} more duplicates"
        raise atscale_errors.UserError(starting_err_msg)

    # check that there will not be name collisions with the created
    existing_query_names_index = [
        (index, value) for index, value in enumerate(features_to_create) if value in feature_dict
    ]
    if existing_query_names_index:
        starting_err_msg = (
            f"The following {feature_name_column} parameters were passed that collide with an "
            f"existing feature in the Data Model."
        )
        counter = 0
        for existing_value in existing_query_names_index:
            if counter >= error_limit:
                counter += 1
                continue
            counter += 1
            starting_err_msg += f"\n\t{feature_name_column} parameter {existing_value[1]} appeared at index: {existing_value[0]}"
        if counter >= error_limit:
            starting_err_msg += f"And \n\t{len(existing_query_names_index)-counter } more collisions hidden after exceeding error_limit"
        raise atscale_errors.UserError(starting_err_msg)

    # cube_dict for dataset and column validation
    invalid_datasets = {}
    invalid_qds_datasets = {}
    valid_datasets = {}
    for index, parameter_dict in enumerate(working_parameter_list):
        dataset_of_int = parameter_dict["dataset_name"]

        if dataset_of_int not in valid_datasets:
            if dataset_of_int in invalid_datasets.values():
                invalid_datasets[index] = dataset_of_int
            elif dataset_of_int in invalid_qds_datasets.values():
                invalid_qds_datasets[index] = dataset_of_int
            else:
                dset = project_parser.get_dataset(
                    project_dict=project_dict, dataset_name=dataset_of_int
                )
                if not dset:
                    invalid_datasets[index] = dataset_of_int
                    continue
                if project_utils._check_if_qds(dset):
                    invalid_qds_datasets[index] = dataset_of_int

    # raise the appropriate errors
    if invalid_datasets:
        starting_err_msg = (
            f"The following dataset_name parameters were passed do not exist in the Data Model."
        )
        counter = 0
        for index_val, dataset in invalid_datasets.items():
            if counter >= error_limit:
                counter += 1
                continue
            counter += 1
            starting_err_msg += f"\n\tDataset {dataset} appeared at index: {index_val}"
        if counter >= error_limit:
            starting_err_msg += f"\n\t{len(invalid_datasets.items()) - counter} more nonexistent dataset_name parameters."
        raise atscale_errors.UserError(starting_err_msg)
    if invalid_qds_datasets:
        starting_err_msg = (
            f"The following dataset_name parameters were passed that match to a qds,"
            f" this is not supported."
        )
        counter = 0
        for index_val, dataset in invalid_qds_datasets.items():
            if counter >= error_limit:
                counter += 1
                continue
            counter += 1
            starting_err_msg += f"\n\tInvalid dataset {dataset} appeared at index: {index_val}"
        if counter >= error_limit:
            starting_err_msg += f"\n\t{len(invalid_qds_datasets.items()) - counter} more invalid dataset_name parameters that match to a query dataset."
        raise atscale_errors.UserError(starting_err_msg)

    original_project_dict = deepcopy(project_dict)
    sql_compilation_errors = []
    # call the underlying function
    for index, parameter_dict in enumerate(working_parameter_list):
        dset = project_parser.get_dataset(project_dict=project_dict, dataset_name=dataset_of_int)
        parameter_dict["data_set"] = dset
        parameter_dict["atconn"] = atconn
        parameter_dict.pop("dataset_name", "")
        parameter_dict.pop("publish", "")
        # left off here, need to test passing with ** and make sure it checks the key names as param names
        try:
            add_calculated_column_to_project_dataset(**parameter_dict)
        except atscale_errors.AtScaleServerError as err:
            if "SQL compilation error" in str(err):
                sql_compilation_errors.append(
                    f"\n\tSQL Compilation Error " f"found at index {index}: {str(err)}"
                )
            else:
                raise err

    # raise error and revert dict if errors found
    if sql_compilation_errors:
        project_dict = original_project_dict
        starting_err_msg = f"Bulk operation canceled:"
        counter = 0
        for err_msg in sql_compilation_errors:
            if counter >= error_limit:
                counter += 1
                break
            counter += 1
            starting_err_msg += err_msg
        if counter >= error_limit:
            starting_err_msg += (
                f"\n\t{len(sql_compilation_errors) - counter} more SQL compilation errors"
            )
        raise atscale_errors.UserError(starting_err_msg)


def bulk_create_calculated_feature(
    atconn: _Connection,
    project_dict: Dict,
    feature_dict: Dict,
    data_model_id: str,
    parameter_list: List[Dict],
    error_limit=5,
):
    """The bulk function caller for create_calculated_feature

    Args:
        atconn (_Connection): an AtScale connection
        project_dict (Dict): The project_dict to mutate
        feature_dict (Dict): The dictionary of current features in the model
        data_model_id (str): The data_model_id to add to
        parameter_list (List[Dict]): The set of parameters to validate and run
        error_limit (int): The maximum number of similar errors to collect before abbreviating.
    """
    from atscale.data_model import DataModel
    from atscale.utils.feature_utils import _create_calculated_feature

    inspection = inspect.getfullargspec(DataModel.create_calculated_feature)

    # don't want to edit the dictionary they passed in
    working_parameter_list = deepcopy(parameter_list)
    # check our inputs are valid for the function we intend to call
    validation_utils.validate_all_expected_params_bulk(
        passed_vars=working_parameter_list, inspection=inspection
    )

    feature_name_column = "new_feature_name"
    # check that no duplicate names were passed in
    features_to_create = [x.get(feature_name_column) for x in working_parameter_list]
    dupes_found = validation_utils.validate_no_duplicates_in_list(features_to_create)
    if dupes_found:
        starting_err_msg = (
            f"The following duplicated {feature_name_column} parameters were passed. "
            f"This parameter must be unique."
        )
        counter = 0
        for dupe in dupes_found:
            if counter >= error_limit:
                counter += 1
                break
            counter += 1
            starting_err_msg += f"\n\t{feature_name_column} parameter {dupe} appeared at indices: {dupes_found[dupe]}"
        if counter >= error_limit:
            starting_err_msg += f"\n\t{len(dupes_found) - counter} more duplications."
        raise atscale_errors.UserError(starting_err_msg)

    # check that there will not be name collisions with the created
    existing_query_names_index = [
        (index, value) for index, value in enumerate(features_to_create) if value in feature_dict
    ]
    if existing_query_names_index:
        starting_err_msg = (
            f"The following {feature_name_column} parameters were passed that collide with an "
            f"existing feature in the Data Model."
        )
        counter = 0
        for existing_value in existing_query_names_index:
            if counter >= error_limit:
                counter += 1
                break
            counter += 1
            starting_err_msg += f"\n\t{feature_name_column} parameter {existing_value[1]} appeared at index: {existing_value[0]}"
        if counter >= error_limit:
            starting_err_msg += f"And \n\t{len(existing_query_names_index) - counter} more collisions hidden after exceeding error_limit"
        raise atscale_errors.UserError(starting_err_msg)

    # validate the mdx
    invalid_mdx = {}
    for index, parameter_dict in enumerate(working_parameter_list):
        mdx_invalid = model_utils._validate_mdx_syntax(
            atconn=atconn, expression=parameter_dict["expression"], raises=False
        )
        if mdx_invalid:
            invalid_mdx[index] = mdx_invalid

    # raise the appropriate errors
    if invalid_mdx:
        starting_err_msg = "The following mdx expressions were passed that are not valid."
        counter = 0
        for index_val, error_msg in invalid_mdx.items():
            if counter >= error_limit:
                counter += 1
                break
            counter += 1
            starting_err_msg += f"\n\tmdx error {error_msg} appeared at index: {index_val}"
        if counter >= error_limit:
            starting_err_msg += (
                f"\n\t{len(invalid_mdx.items()) - counter} more invalid mdx expressions."
            )
        raise atscale_errors.UserError(starting_err_msg)

    # call the underlying function
    for parameter_dict in working_parameter_list:
        parameter_dict["project_dict"] = project_dict
        parameter_dict["cube_id"] = data_model_id
        parameter_dict["name"] = parameter_dict["new_feature_name"]

        parameter_dict.pop("publish", "")
        parameter_dict.pop("new_feature_name", "")
        # left off here, need to test passing with ** and make sure it checks the key names as param names
        _create_calculated_feature(**parameter_dict)
