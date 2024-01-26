from typing import Dict, List, Union, Tuple, get_origin

from atscale.errors import atscale_errors
from atscale.parsers import project_parser
from pandas import DataFrame

import logging

logger = logging.getLogger(__name__)


def validate_by_type_hints(
    inspection,
    func_params,
    accept_partial=False,
    raise_err=True,
):
    """Takes an inspection of a function (inspect.getfullargspec(<function without parenthesis>)) and the locals() dict
    and raises an error if any parameters as defined in the func_params dict don't match the type hint for the parameter
    with exception to the parameters default value."""
    text_rep = {
        Dict[str, str]: "Dict[str, str]",
        Dict[str, List[str]]: "Dict[str:List[str]]",
        Dict[str, Tuple[str, str]]: "Dict[str,Tuple[str, str]]",
        List[str]: "List[str]",
        List[Union[str, Tuple[str, str]]]: "List[Union[str, tuple]]",
    }
    if inspection.defaults is not None:
        defaults = {
            p: val
            for p, val in zip(inspection.args[-len(inspection.defaults) :], inspection.defaults)
        }
    else:
        defaults = {}

    bad_params = []
    missing_params = []

    for param in inspection.args:  # all but data_model
        if param not in inspection.annotations:
            continue

        if param in func_params:
            type_hint = inspection.annotations[
                param
            ]  # typing object like Dict[...] or an actual type like int
            if type(type_hint) != str:  # I.e., to avoid cases where the type hint is in string form
                origin = get_origin(type_hint)  # Dict[...] -> dict, int -> None
                if origin is None:  # builtin class like int
                    origin = type_hint  # <class: 'int'>, the actual type
                    type_hint = origin.__name__  # 'int', the name of the type
                elif hasattr(
                    origin, "_name"
                ):  # typing.get_origin(Union[...]) -> Union... union has _name
                    if param in defaults and func_params[param] == defaults[param]:
                        continue
                    elif type(func_params[param]) not in type_hint.__args__:
                        bad_params.append(
                            (param, text_rep.get(type_hint, str(type_hint).replace("typing.", "")))
                        )
                    continue

                    # continue  # ignore special form, for example Union

                if (
                    type(func_params[param]) == DataFrame
                ):  # Handling issue with truth values of DataFrames
                    if param in defaults and func_params[param].equals(defaults[param]):
                        continue  # always accept default value... None is used as a default for mutable types like {} or []
                elif param in defaults and func_params[param] == defaults[param]:
                    continue  # always accept default value... None is used as a default for mutable types like {} or []

                if type(func_params[param]) != origin and not isinstance(
                    func_params[param], origin
                ):
                    # If the parameter's type is not at least a subclass of the corresponding type hint (e.g., we don't
                    # want to error out if we pass a Snowflake connection to a parameter technically typed SQLConnection)
                    if origin == float and (
                        "int" in str(type(func_params[param])).lower()
                        or "float" in str(type(func_params[param])).lower()
                    ):  # Not taking issue with a user passing an int where the code expects a float
                        pass
                    elif origin == int and "int" in str(type(func_params[param])).lower():
                        # Not taking issue with a user passing an int where the code expects a float
                        pass
                    else:
                        bad_params.append(
                            (param, text_rep.get(type_hint, str(type_hint).replace("typing.", "")))
                        )
            else:
                if (
                    type(func_params[param]).__name__ != type_hint
                    and str(type(func_params[param])).split("'")[1] != type_hint
                ):
                    bad_params.append(
                        (param, text_rep.get(type_hint, str(type_hint).replace("typing.", "")))
                    )
        else:
            if not accept_partial:
                missing_params.append(param)

    if missing_params and raise_err:
        raise atscale_errors.UserError(f"Missing expected parameters {missing_params}")

    if bad_params and raise_err:
        bad_param_str = "Incorrect parameter types passed: "
        for param in bad_params:
            bad_param_str += f"the {param[0]} parameter must be of type {param[1]}\n\t"
        raise atscale_errors.UserError(bad_param_str)

    return (missing_params, bad_params)


def _validate_warehouse_id_parameter(
    atconn: "_Connection",
    project_dict: dict = None,
    warehouse_id: str = None,
    dbconn_warehouse_id: str = None,
) -> str:
    parsed_id = project_parser.get_project_warehouse(project_dict=project_dict)
    if parsed_id is not None:
        # if user passed a warehouse different from project
        if warehouse_id is not None and warehouse_id != parsed_id:
            raise atscale_errors.UserError(
                f"The passed warehouse_id parameter: '{warehouse_id}' does not match the warehouse set up with "
                f"the project: '{parsed_id}'"
            )
        # if user passed a database connection with a warehouse different from project
        if dbconn_warehouse_id is not None and dbconn_warehouse_id != parsed_id:
            raise atscale_errors.UserError(
                f"The warehouse_id parameter in the passed database connection: '{dbconn_warehouse_id}' does not match the warehouse set up with "
                f"the project: '{parsed_id}'"
            )
    if warehouse_id is None:
        if parsed_id is not None:
            warehouse_id = parsed_id
        elif dbconn_warehouse_id is not None:
            warehouse_id = dbconn_warehouse_id
        else:  # no passed warehouse and no datasets in the model
            raise atscale_errors.UserError(
                "No warehouse is used in the project yet, warehouse_id can not be "
                "inferred. Please pass a value for the warehouse_id parameter."
            )
    if warehouse_id not in [w["warehouse_id"] for w in atconn._get_connected_warehouses()]:
        raise atscale_errors.UserError(f"Nonexistent warehouse_id: '{warehouse_id}'")
    return warehouse_id


def _validate_warehouse_connection(
    atconn: "_Connection",
    project_dict: dict,
    dbconn: "SQLConnection",
) -> bool:
    project_datasets = project_parser.get_datasets(project_dict)
    connections = atconn._get_connection_groups()
    project_connections = project_parser.get_connection_list_for_project_datasets(
        project_datasets, connections
    )
    for project_connection in project_connections:
        if dbconn._verify(project_connection):
            return True
    msg = "The SQLConnection connects to a database that is not referenced by the given data_model."
    raise atscale_errors.UserError(msg)


def validate_required_params_not_none(
    local_vars: dict,
    inspection,
):
    """Errors if any parameters that are required according to the given inspection are None or not defined in the
    local_vars dict"""
    # list of all parameters names in order (optionals must come after required)
    all_params = inspection[0]
    # assume all required at first
    param_name_list = all_params

    # tuple of default values (for every optional parameter)
    defaults = inspection[3]
    # parameter has default if and only if its optional
    if defaults:
        param_name_list = all_params[: -len(defaults)]

    param_names_none = [x for x in param_name_list if local_vars[x] is None]

    if param_names_none:
        raise ValueError(
            f'The following required parameters are None: {", ".join(param_names_none)}'
        )


def validate_all_expected_params_bulk(
    passed_vars: List[Dict],
    inspection,
    raise_err: bool = True,
) -> List:
    """Custom mix of validations of parameters for bulk operations. Separate function created to reduce loops

    Args:
        passed_vars (List(Dict)): the list of dictionaries of passed parameter name:value pairs
        inspection: The inspection of the function of interest
        err_msg (str, optional): Custom error message to raise. Defaults to None to use default message.
        raise_err (bool, optional): If the function should raise the error message or return it. Defaults to True.

    Returns:
        List: a list of dictionaries that describe the issues found
    """
    # list of all parameters names in order (optionals must come after required)
    all_params = inspection[0]
    # assume all required at first
    param_name_required = all_params

    # tuple of default values (for every optional parameter)
    defaults = inspection[3]
    # parameter has default if and only if its optional
    if defaults:
        param_name_required = all_params[: -len(defaults)]

    # remove self from the list to validate
    all_params = [x for x in all_params if x != "self"]
    param_name_required = [x for x in param_name_required if x != "self"]

    errors_found = []
    for index, var_dict in enumerate(passed_vars):
        error_dict = {}
        var_dict_keys = list(var_dict.keys())

        # flag extra parameters
        extra_params = [x for x in var_dict_keys if x not in all_params]
        if extra_params:
            error_dict["index"] = index
            error_dict["extra_params"] = extra_params

        # flag missing parameters
        missing_params = [x for x in param_name_required if x not in var_dict_keys]
        if missing_params:
            error_dict["index"] = index
            error_dict["missing_params"] = missing_params

        # check_types
        invalid_types = validate_by_type_hints(
            inspection=inspection, func_params=var_dict, raise_err=False
        )[1]
        if invalid_types:
            error_dict["index"] = index
            error_dict["invalid_types"] = invalid_types

        if error_dict:
            errors_found.append(error_dict)

    if raise_err:
        if errors_found:
            base_err_msg = "Issues found with parameters at the following indices."
            for error_dict in errors_found:
                base_err_msg += f'\n\tAt index {error_dict["index"]}:'
                if error_dict.get("extra_params", []):
                    base_err_msg += f'\n\t\tThe following invalid parameters were passed {error_dict.get("extra_params")}'
                if error_dict.get("missing_params", []):
                    base_err_msg += f'\n\t\tThe following required parameters were missing {error_dict.get("missing_params")}'
                if error_dict.get("invalid_types", []):
                    invalid_type_dict = error_dict.get("invalid_types")
                    invalid_type_strings = [
                        f"{param[0]} must be of type {param[1]}" for param in invalid_type_dict
                    ]
                    base_err_msg += (
                        f"\n\t\tThe following parameters had incorrect types {invalid_type_strings}"
                    )

            raise atscale_errors.UserError(base_err_msg)

    return errors_found


def validate_no_duplicates_in_list(
    input_list: List[str],
) -> Dict[str, List]:
    """checks if there are duplicates in a list and returns a list of found duplicates.
    Note that this is only meant for strings or numerics.

    Args:
        input_list (List[str]): the list of strings to identify dupes in

    Returns:
        Dict[str,List]: the duplicates found and the list of indexes they appeared at
    """
    dupe_check = {}
    dupes_found = []
    for index, provided_name in enumerate(input_list):
        if provided_name in dupe_check:
            dupes_found.append(provided_name)
            dupe_check[provided_name].append(index)
        else:
            dupe_check[provided_name] = [index]
    ret_dict = {x: dupe_check.get(x) for x in dupes_found}
    return ret_dict
