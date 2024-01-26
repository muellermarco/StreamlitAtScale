import copy
import logging
import uuid
import pandas as pd
from typing import List, Set, Union, Tuple, Dict, Any
from atscale.base.enums import (
    Aggs,
    Measure,
    Level,
    Hierarchy,
    FeatureType,
)
from atscale.connection.connection import _Connection
from atscale.db.sql_connection import SQLConnection
from atscale.utils.dmv_utils import get_dmv_data
from atscale.utils import db_utils, model_utils, input_utils
from atscale.errors import atscale_errors
from atscale.parsers import project_parser
from atscale.base.enums import CheckFeaturesErrMsg

logger = logging.getLogger(__name__)


def _get_draft_features(
    project_dict,
    data_model_name,
    feature_list: List[str] = None,
    folder_list: List[str] = None,
    feature_type: FeatureType = FeatureType.ALL,
) -> dict:
    """Gets the feature names and metadata for each feature in the published DataModel.

    Args:
        project_dict (dict): the metadata of the project to extract
        data_model_name (str): the name of the data_model of interest
        feature_list (List[str], optional): A list of features to return. Defaults to None to return all.
        folder_list (List[str], optional): A list of folders to filter by. Defaults to None to ignore folder.
        feature_type (FeatureType, optional): The type of features to filter by. Options
            include FeatureType.ALL, FeatureType.CATEGORICAL, or FeatureType.NUMERIC. Defaults to ALL.

    Returns:
        dict: A dictionary of dictionaries where the feature names are the keys in the outer dictionary
              while the inner keys break down metadata of the features.
    """
    start_dict = {}
    # metrical attributes and levels
    start_dict.update(_parse_categorical_features(data_model_name, project_dict))
    start_dict.update(_parse_denormalized_categorical_features(data_model_name, project_dict))
    if feature_type in [FeatureType.NUMERIC, FeatureType.ALL]:
        start_dict.update(_parse_aggregate_features(data_model_name, project_dict))
        start_dict.update(_parse_calculated_features(data_model_name, project_dict))

    feature_list = [feature_list] if isinstance(feature_list, str) else feature_list
    folder_list = [folder_list] if isinstance(folder_list, str) else folder_list

    ret_dict = copy.deepcopy(start_dict)
    for i in start_dict:
        if feature_list is not None:
            if i not in feature_list:
                del ret_dict[i]
                continue
        if folder_list is not None:
            if all(folder_val not in folder_list for folder_val in ret_dict[i]["folder"]):
                del ret_dict[i]
                continue
        if feature_type != FeatureType.ALL:
            if ret_dict[i]["feature_type"] != feature_type.name_val:
                del ret_dict[i]
    return ret_dict


def _check_joins(
    project_dict: dict,
    cube_id: str,
    join_features: List[str],
    join_columns: List[Union[str, List[str]]],
    column_set: set,
    roleplay_features: List[str] = None,
    dbconn: SQLConnection = None,
    df: pd.DataFrame = None,
    key_dict=None,
    feature_dict=None,
    spark_input: bool = False,
    use_spark: bool = False,
):
    """Checks that the join features and columns are valid and either errors or returns join_features, join_columns, and df.
    Args:
        project_dict (dict): the metadata of the project to validate against
        cube_id (str): the id of the cube to validate against
        join_features (List[str]): the list of features to join on
        join_columns (List[str]): the list of columns to join on
        column_set (set): the set of columns in the table or dataframe
        roleplay_features (List[str], optional): the list of roleplay features to join on.
            Defaults to None to be set as a list of '' for each join features.
        dbconn (SQLConnection, optional): the connection to the database, used for querying columns as defined in atscale
        in case df is passsed and needs value columns to be mapped to query columns. Defaults to None.
        df (pd.DataFrame, optional): the dataframe to validated before writing to db and model. Defaults to None.
        key_dict (dict, optional): The key dict returned by calling _get_feature_keys for the join_features.
            Defaults to None to retrieve it.
        feature_dict (dict, optional): The feature dict returned by calling _get_draft_features for the join_features.
            Defaults to None to call the method and retrieve it.
        spark_input (bool, optional): if the input df is spark or pandas, defaults to False.
        use_spark (bool, optional): Whether to use spark to query for key columns, defaults to False.
    """
    column_set: Set[str] = set(column_set)
    if join_features is None:
        join_features = []
    if join_columns is None:
        join_columns = join_features
    elif len(join_features) != len(join_columns):
        raise atscale_errors.UserError(
            f"join_features and join_columns must be equal lengths. join_features is"
            f" length {len(join_features)} while join_columns is length {len(join_columns)}"
        )
    # copy so if we make a feature a list, or change its name, it doesn't change the original
    join_columns = join_columns.copy()
    if roleplay_features is None:
        roleplay_features = ["" for feature in join_features]
    elif len(join_features) != len(roleplay_features):
        raise atscale_errors.UserError(
            f"join_features and roleplay_features lengths must match. "
            f"join_features is length {len(join_features)} "
            f"while roleplay_features is length {len(roleplay_features)}"
        )

    if feature_dict is None:
        model_name = project_parser.get_cube(project_dict=project_dict, id=cube_id)["name"]
        feature_dict = _get_draft_features(data_model_name=model_name, project_dict=project_dict)
    # need to get a set of features that includes base names of roleplayed features
    levels = {}
    # also need the set of only base names of levels (not secondary attributes either)
    base_names = {}
    for feat, info in feature_dict.items():
        if info["feature_type"] == FeatureType.CATEGORICAL.name_val:
            if feat != info.get("base_name", feat):  # roleplayed
                base_names[info["base_name"]] = info
            if not info.get("secondary_attribute", False):
                levels[info.get("base_name", feat)] = info
            # if there are more than one roleplay on the level, it will hold the info of just one
    feature_dict.update(base_names)

    features_not_in_model = []
    non_level_features = []
    for f in join_features:
        if f not in feature_dict:
            features_not_in_model.append(f)
        elif f not in levels:
            non_level_features.append(f)
    err_msg = ""
    if features_not_in_model:
        err_msg += f"The following features in join_features do not exist in the data model: {features_not_in_model}\n"
    if non_level_features:
        err_msg += (
            f"Joins must be made exclusively to hierarchy levels, the following items in "
            f"join_features are not levels of a hierarchy: {non_level_features}."
        )
    if err_msg:
        raise atscale_errors.UserError(err_msg)

    # Verify the join_columns (which may be join_features now) are in the dataframe columns.
    key_dict = (
        project_parser._get_feature_keys(project_dict, cube_id, join_features)
        if key_dict is None
        else key_dict
    )
    missing_join_columns = []

    for i, column in enumerate(join_columns):
        if type(column) is not list:
            column = [column]
            join_columns[i] = column
        for col in column:
            if col not in column_set:
                missing_join_columns.append(col)
    if missing_join_columns:
        raise atscale_errors.UserError(
            f"The given join_columns {missing_join_columns} do not exist in the column set {list(column_set)}."
        )

    # users are going to know the feature names associated with values, but the feature names don't always map to
    # the feature keys. So if they pass column name that is victim to this, try and adjust it to match the key.
    for i, (join_feature, join_column) in enumerate(zip(join_features, join_columns)):
        key_cols: List[str] = key_dict[join_feature]["key_cols"]
        value_col: str = key_dict[join_feature]["value_col"]
        # alert the user to a missed multi-key
        if len(join_column) != len(key_cols):
            raise atscale_errors.UserError(
                f'Relationship for feature: "{join_feature}" '
                f'requires {len(key_cols)} key{"s" if len(key_cols) > 1 else ""}: {key_cols} '
                f"but received {len(join_column)}: {join_column}"
            )
        if dbconn is not None and df is not None:
            # if the column is from an atscale query and the value returned is not the join key
            # then we assume that the join_column is an alias for the value column when it should be the key column
            if len(key_cols) == 1 and key_cols[0] != value_col and join_column[0] != key_cols[0]:
                if join_column[0] != value_col and join_column[0] != join_feature:
                    value = input_utils.prompt_yes_no(
                        question=f"Provided join_column: {join_column[0]} cannot be automatically mapped "
                        f"to the field name for the key({key_cols[0]}) or value({value_col}) of {join_feature}. "
                        f"If this join_column maps to the value, input 'y', else 'n'. Note: "
                        f"If this column is the result of a get_data call, it is a value and 'y' should be input."
                    )
                    if not value:
                        continue
                if use_spark:
                    df_key = db_utils._get_key_cols(
                        key_dict[join_feature], spark_session=df.sparkSession
                    )
                else:
                    df_key: pd.DataFrame = db_utils._get_key_cols(
                        key_dict[join_feature], dbconn=dbconn
                    )
                if df_key is not None:
                    if join_column[0] != value_col:
                        if use_spark:
                            df_key = df_key.withColumnRenamed(value_col, join_column[0])
                        else:
                            df_key.rename(
                                columns={value_col: join_column[0]}, inplace=True
                            )  # rename df_key value column to given join_column
                    if spark_input:
                        if not use_spark:
                            spark_session = df.sparkSession
                            df_key = spark_session.createDataFrame(df_key)
                        df = df.join(df_key, how="left", on=join_column[0])
                    else:
                        df = pd.merge(df, df_key, how="left", on=join_column[0])
                    # merge on given join_column name

                    join_columns[i] = [key_cols[0]]
        else:
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

    return join_features, join_columns, roleplay_features, df


def _get_atscale_names(
    atconn: _Connection,
    warehouse_id: str,
    table_name: str,
    dbconn: SQLConnection = None,
    database: str = None,
    schema: str = None,
    expected_columns: List[str] = None,
    include_dtype: bool = False,
) -> Tuple[Union[Set[str], List[str]], str, str, str]:
    """Will error if database and schema are not connected to warehouse_id. Will error if table_name is not viewable
    from the atconn in the given db and schema, if table_name doesn't exist but an alias does (upper or lower), this
    method assumes it is an alias and returns that name. ignores expected_columns that are not in
    atscale columns but will warn if one is not present but appears fully uppercase or lowercase.
    Args:
        atconn:
        warehouse_id:
        table_name:
        dbconn:
        database: Need to pass if dbconn is not passed
        schema: Need to pass if dbconn is not passed
        expected_columns: If true, warns if atscale columns are of a different casing
        include_dtype: If true, first returned item will be a list of tuples with name and dtype,
        otherwise a set of names
    """
    if schema is None and database is not None:
        raise atscale_errors.UserError("Must pass schema if database passed")
    if dbconn is None and database is None and schema is None:
        raise atscale_errors.UserError(
            "Must pass dbconn or both database and schema, none were passed"
        )
    if dbconn is not None and database is None and schema is None:
        database, schema = db_utils.get_database_and_schema(dbconn=dbconn)
    db_aliases = atconn._get_connected_databases(
        warehouse_id=warehouse_id
    )  # don't convert to aliases
    if database not in db_aliases:
        raise atscale_errors.UserError(
            f"The database '{database}' does not exist in the list of databases "
            f"connected to warehouse id '{warehouse_id}': {db_aliases}"
        )

    schema_aliases = atconn._get_connected_schemas(warehouse_id=warehouse_id, database=database)
    if schema not in schema_aliases:
        raise atscale_errors.UserError(
            f"The schema '{schema}' does not exist in the list of schemas"
            f"connected to warehouse_id '{warehouse_id} in database {database}': {schema_aliases}"
        )
    atscale_table_name = db_utils.get_atscale_tablename(
        atconn=atconn,
        warehouse_id=warehouse_id,
        database=database,
        schema=schema,
        table_name=table_name,
    )
    atscale_columns = atconn._get_table_columns(
        warehouse_id=warehouse_id,
        table_name=atscale_table_name,
        database=database,
        schema=schema,
        expected_columns=expected_columns,
    )
    if not include_dtype:
        atscale_columns = {c[0] for c in atscale_columns}
    return atscale_columns, atscale_table_name, schema, database


def _prep_join_columns_for_join(
    join_columns: List[List[str]],
    atscale_columns: List[str],
) -> List[List[str]]:
    """Prepares the join columns for the join by replacing any column names that are aliases with the actual column name and making each item a list.

    Args:
        join_columns: The columns to join on.
        atscale_columns: The columns as they appear in the atscale dataset.

    Returns:
        The join columns with any aliases replaced with the actual column names.
    """
    if join_columns is None:
        return join_columns
    else:
        join_columns = (
            join_columns.copy()
        )  # always copy before mutating, the user could've used the param twice
    atscale_columns = set(atscale_columns)
    for i, joins in enumerate(join_columns):
        if type(joins) is not list:
            join_columns[i] = [joins]
            joins = [joins]
        for j, col in enumerate(joins):
            fixed_names, missing_names = db_utils._convert_names_to_atscale_names(
                names=[col], aliases=atscale_columns
            )
            join_columns[i][j] = fixed_names[0]
    return join_columns


def _get_agg_type(attribute: dict):
    if "count-nonnull" in attribute.get("properties", {}).get("type", {}):
        agg_type = "NDC"
    elif "count-distinct" in attribute.get("properties", {}).get("type", {}):
        if (
            attribute.get("properties", {})
            .get("type", {})
            .get("count-distinct", {})
            .get("approximate", False)
        ):
            agg_type = "DCE"
        else:
            agg_type = "DC"
    else:
        agg_type = (
            attribute.get("properties", {})
            .get("type", {})
            .get("measure", {})
            .get("default-aggregation", "Aggregate")
        )
    return Aggs(agg_type).visual_rep


def _parse_categorical_features(
    data_model_name,
    project_dict,
):
    """Pulls metadata on roleplayed features

    Args:
        data_model_name (str): the name of the data_model of interest
        project_dict (dict): the metadata of the project to extract

    Returns:
        Dict[Dict]: a dict of dicts of the form 'query_name':{metadata}
    """
    info_dict = {}

    if "attributes" not in project_dict or "keyed-attribute" not in project_dict["attributes"]:
        return {}

    for i in project_dict["attributes"]["keyed-attribute"]:
        info_dict[i["id"]] = i

    # deal with metrical secondary attributes
    if "attribute" in project_dict["attributes"]:
        for i in project_dict["attributes"]["attribute"]:
            info_dict[i["id"]] = i

    roleplay_refs = {}
    cube = [x for x in project_dict["cubes"]["cube"] if x["name"] == data_model_name][0]

    for dataset in cube["data-sets"]["data-set-ref"]:
        if "key-ref" in dataset["logical"]:
            for key in dataset["logical"]["key-ref"]:
                if key["complete"] == "false":
                    if "ref-path" in key:
                        val = (
                            key["ref-path"]["new-ref"]["ref-naming"],
                            key["ref-path"]["new-ref"]["ref-id"],
                        )
                    else:
                        val = ("{0}", "")
                    roleplay_refs.setdefault(key["id"], [])
                    roleplay_refs[key["id"]].append(val)
    roleplay_ids = {}
    ref_ids = {}
    for key_ref in project_dict["attributes"]["keyed-attribute"]:
        if key_ref.get("key-ref", None) and key_ref["key-ref"] in roleplay_refs:
            roleplay_ids[key_ref["id"]] = roleplay_refs[key_ref["key-ref"]]

    # need this to handle snowflake dimensions
    done = False
    last_run = False
    while not done:
        starting_roleplays = len(roleplay_ids)
        for dimension in project_dict["dimensions"]["dimension"]:
            for hierarchy in dimension["hierarchy"]:
                for level in hierarchy["level"]:
                    if level["primary-attribute"] in roleplay_ids or last_run:
                        base_roleplays = roleplay_ids.get(level["primary-attribute"], [("{0}", "")])
                        if "properties" in level and level["properties"].get("visible", True):
                            if "keyed-attribute-ref" in level:
                                for key in level["keyed-attribute-ref"]:
                                    for roleplay in base_roleplays:
                                        rp_string = roleplay[0]
                                        if "ref-path" in key["properties"]:
                                            val = (
                                                rp_string.replace(
                                                    "{0}",
                                                    key["properties"]["ref-path"]["new-ref"][
                                                        "ref-naming"
                                                    ],
                                                    1,
                                                ),
                                                key["properties"]["ref-path"]["new-ref"]["ref-id"],
                                            )
                                        else:
                                            val = (rp_string, "")
                                        roleplay_ids.setdefault(key["attribute-id"], [])
                                        roleplay_ids[key["attribute-id"]].append(val)
                            # added in 'attribute-ref to deal with metrical secondary attributes
                            if "attribute-ref" in level:
                                for key in level["attribute-ref"]:
                                    for roleplay in base_roleplays:
                                        rp_string = roleplay[0]
                                        roleplay_ids.setdefault(key["attribute-id"], [])
                                        roleplay_ids[key["attribute-id"]].append((rp_string, ""))
        if starting_roleplays == len(roleplay_ids):
            last_run = True
        if last_run:
            done = True

    for key_ref in project_dict["attributes"]["keyed-attribute"]:
        ref_ids[key_ref["id"]] = key_ref

    # for metrical attributes
    if "attribute" in project_dict["attributes"]:
        for key_ref in project_dict["attributes"]["attribute"]:
            if key_ref.get("key-ref", None) and key_ref["key-ref"] in roleplay_refs:
                roleplay_ids[key_ref["id"]] = roleplay_refs[key_ref["key-ref"]]
            # this seems necessary for snowflake dimensions
            elif key_ref.get("id", None) and key_ref["id"] in roleplay_refs:
                roleplay_ids[key_ref["id"]] = roleplay_refs[key_ref["id"]]
            ref = copy.deepcopy(key_ref)
            ref["level-type"] = _get_agg_type(key_ref)
            ref["feature-type"] = "Numeric"
            ref_ids[key_ref["id"]] = ref

    dim_to_id_dict = {}

    for dimension in project_dict["dimensions"]["dimension"]:
        for hierarchy in dimension["hierarchy"]:
            if "folder" in hierarchy["properties"]:
                this_folder = hierarchy["properties"]["folder"]
            else:
                this_folder = ""
            roleplays = set()
            # reversed so that we only apply role playing above the leaf
            for level in reversed(hierarchy["level"]):
                queryable_level = True
                if level["primary-attribute"] in roleplay_ids:
                    roleplays.add(level["primary-attribute"])
                if len(roleplays) == 0:
                    roleplays_to_apply = [level["primary-attribute"]]
                else:
                    roleplays_to_apply = roleplays
                for roleplay in roleplays_to_apply:
                    level_roleplays = roleplay_ids.get(roleplay, [])
                    if roleplay not in roleplay_ids:
                        level_roleplays.append(("{0}", ""))
                        queryable_level = False
                    for role, ref_id in level_roleplays:
                        roleplaying_dict = {}
                        if level.get("properties", {}).get("level-type", []):
                            roleplaying_dict["level_type"] = level["properties"]["level-type"]
                        else:
                            roleplaying_dict["level_type"] = "Regular"
                        roleplaying_dict["id"] = ref_ids[level["primary-attribute"]]["id"]
                        rp_name = role.replace("{0}", ref_ids[level["primary-attribute"]]["name"])
                        roleplaying_dict["roleplay_expression"] = role
                        roleplaying_dict["roleplay_ref_id"] = ref_id
                        roleplaying_dict["roleplayed_name"] = rp_name
                        roleplaying_dict["folder"] = [this_folder]
                        roleplaying_dict["queryable"] = queryable_level
                        roleplaying_dict["roleplayed_hierarchy"] = [
                            role.replace("{0}", hierarchy["name"])
                        ]
                        roleplaying_dict["roleplayed_dimension"] = role.replace(
                            "{0}", dimension["name"]
                        )
                        roleplaying_dict["roleplayed_caption"] = role.replace(
                            "{0}", info_dict[roleplaying_dict["id"]]["properties"]["caption"]
                        )
                        roleplaying_dict["base_name"] = ref_ids[level["primary-attribute"]]["name"]
                        roleplaying_dict["base_hierarchy"] = [hierarchy["name"]]
                        roleplaying_dict["base_dimension"] = dimension["name"]

                        # deal with multiple hierachies with same roleplay method
                        if rp_name in dim_to_id_dict:
                            if (
                                roleplaying_dict["roleplayed_hierarchy"][0]
                                not in dim_to_id_dict[rp_name]["roleplayed_hierarchy"]
                            ):
                                for found_key, found_value in roleplaying_dict.items():
                                    current_val = dim_to_id_dict[rp_name].get(found_key, [])
                                    if type(current_val) == list and len(current_val) > 0:
                                        dim_to_id_dict[rp_name][found_key].extend(found_value)
                                    else:
                                        dim_to_id_dict[rp_name][found_key] = found_value
                        else:
                            dim_to_id_dict[rp_name] = roleplaying_dict

                    # these are the secondary attributes
                    if (
                        "keyed-attribute-ref" in level
                    ):  # then find the base hierarchy (source for this rp'd one)
                        for attr in level["keyed-attribute-ref"]:
                            # if it has a reference ID then it should be handled elsewhere as this is a join
                            ref_id_check = attr.get("ref-id", False)
                            if not ref_id_check:
                                # for role, ref_id in roleplay_ids[roleplay]:
                                level_roleplays = roleplay_ids.get(roleplay, [])
                                if roleplay not in roleplay_ids:
                                    level_roleplays.append(("{0}", ""))
                                    queryable_level = False
                                for role, ref_id in level_roleplays:
                                    roleplaying_dict = {}
                                    roleplaying_dict["id"] = ref_ids[attr["attribute-id"]]["id"]
                                    roleplaying_dict["roleplayed_name"] = role.replace(
                                        "{0}", ref_ids[attr["attribute-id"]]["name"]
                                    )
                                    if "folder" in ref_ids[attr["attribute-id"]]["properties"]:
                                        roleplaying_dict["folder"] = [
                                            ref_ids[attr["attribute-id"]]["properties"]["folder"]
                                        ]
                                    else:
                                        roleplaying_dict["folder"] = [this_folder]
                                    roleplaying_dict["queryable"] = queryable_level
                                    roleplaying_dict["roleplay_expression"] = role
                                    roleplaying_dict["roleplay_ref_id"] = ref_id
                                    roleplaying_dict["roleplayed_hierarchy"] = [
                                        role.replace("{0}", ref_ids[attr["attribute-id"]]["name"])
                                    ]
                                    roleplaying_dict["roleplayed_dimension"] = role.replace(
                                        "{0}", dimension["name"]
                                    )
                                    roleplaying_dict["roleplayed_caption"] = role.replace(
                                        "{0}",
                                        info_dict[roleplaying_dict["id"]]["properties"]["caption"],
                                    )
                                    roleplaying_dict["base_name"] = ref_ids[attr["attribute-id"]][
                                        "name"
                                    ]
                                    roleplaying_dict["base_hierarchy"] = [hierarchy["name"]]
                                    roleplaying_dict["base_dimension"] = dimension["name"]
                                    roleplaying_dict["secondary_attribute"] = True

                                    dim_to_id_dict[
                                        roleplaying_dict["roleplayed_name"]
                                    ] = roleplaying_dict

                    # these are the metrical secondary attributes
                    if "attribute-ref" in level:
                        for attr in level["attribute-ref"]:
                            # if it has a reference ID then it should be handled elsewhere as this is a join
                            ref_id_check = attr.get("ref-id", False)
                            if not ref_id_check:
                                level_roleplays = roleplay_ids.get(roleplay, [])
                                if roleplay not in roleplay_ids:
                                    level_roleplays.append(("{0}", ""))
                                    queryable_level = False
                                for role, ref_id in level_roleplays:
                                    roleplaying_dict = {}
                                    roleplaying_dict["level_type"] = ref_ids[attr["attribute-id"]][
                                        "level-type"
                                    ]
                                    roleplaying_dict["feature_type"] = ref_ids[
                                        attr["attribute-id"]
                                    ]["feature-type"]
                                    roleplaying_dict["id"] = ref_ids[attr["attribute-id"]]["id"]
                                    roleplaying_dict["queryable"] = queryable_level
                                    roleplaying_dict["roleplay_expression"] = role
                                    roleplaying_dict["roleplay_ref_id"] = ref_id
                                    roleplaying_dict["roleplayed_name"] = role.replace(
                                        "{0}", ref_ids[attr["attribute-id"]]["name"]
                                    )
                                    roleplaying_dict["base_name"] = ref_ids[attr["attribute-id"]][
                                        "name"
                                    ]

                                    if "folder" in ref_ids[attr["attribute-id"]]["properties"]:
                                        roleplaying_dict["folder"] = [
                                            ref_ids[attr["attribute-id"]]["properties"]["folder"]
                                        ]
                                    else:
                                        roleplaying_dict["folder"] = [this_folder]
                                    roleplaying_dict["roleplayed_caption"] = role.replace(
                                        "{0}",
                                        info_dict[roleplaying_dict["id"]]["properties"]["caption"],
                                    )
                                    roleplaying_dict["secondary_attribute"] = True
                                    dim_to_id_dict[
                                        roleplaying_dict["roleplayed_name"]
                                    ] = roleplaying_dict

    return_dict = {}
    for i in dim_to_id_dict:
        return_dict[i] = {}

    for i in dim_to_id_dict:
        return_dict[i]["caption"] = dim_to_id_dict[i].get("roleplayed_caption", "")
        return_dict[i]["atscale_type"] = dim_to_id_dict[i].get("level_type", "Regular")
        try:
            return_dict[i]["description"] = info_dict[dim_to_id_dict[i]["id"]]["properties"][
                "description"
            ]
        except KeyError:
            return_dict[i]["description"] = ""
        return_dict[i]["hierarchy"] = dim_to_id_dict[i].get("roleplayed_hierarchy", [""])
        return_dict[i]["dimension"] = dim_to_id_dict[i].get("roleplayed_dimension", "")
        return_dict[i]["folder"] = dim_to_id_dict[i].get("folder", [""])
        return_dict[i]["queryable"] = dim_to_id_dict[i].get("queryable", True)
        return_dict[i]["feature_type"] = dim_to_id_dict[i].get("feature_type", "Categorical")
        return_dict[i]["roleplay_expression"] = dim_to_id_dict[i].get("roleplay_expression", "")
        if dim_to_id_dict[i].get("roleplay_ref_id", False):
            return_dict[i]["roleplay_ref_id"] = dim_to_id_dict[i]["roleplay_ref_id"]
        return_dict[i]["base_name"] = dim_to_id_dict[i].get("base_name", "")
        return_dict[i]["base_hierarchy"] = dim_to_id_dict[i].get("base_hierarchy", "")
        return_dict[i]["base_dimension"] = dim_to_id_dict[i].get("base_dimension", "")
        return_dict[i]["secondary_attribute"] = dim_to_id_dict[i].get("secondary_attribute", False)

        # deal with metricals
        if return_dict[i]["feature_type"] == "Numeric":
            return_dict[i]["expression"] = ""
            del return_dict[i]["hierarchy"]
            del return_dict[i]["secondary_attribute"]

    return return_dict


def _parse_aggregate_features(
    data_model_name,
    project_dict,
):
    """Loads _feature_dict with information regarding aggregate features.

    Args:
        data_model_name (str): the name of the data_model of interest
        project_dict (dict): the metadata of the project to extract

    Returns:
        Dict[Dict]: a dict of dicts of the form 'query_name':{metadata}
    """
    return_dict = {}

    cube = [x for x in project_dict["cubes"]["cube"] if x["name"] == data_model_name][0]
    if "attributes" not in cube or "attribute" not in cube["attributes"]:
        return {}  # Meaning no features have been added yet

    feature_info = [y for y in [x for x in cube["attributes"]["attribute"]]]

    for i in feature_info:
        return_dict[i["name"]] = {}

    for i in feature_info:
        return_dict[i["name"]]["caption"] = i.get("properties", {}).get("caption", "")
        return_dict[i["name"]]["atscale_type"] = _get_agg_type(i)
        # commented out until the dmv bug is fixed and we expose it in use_published
        # agg_type = Aggs.from_properties(i.get("properties", {})).visual_rep
        # return_dict[i["name"]]["aggregation_type"] = agg_type
        return_dict[i["name"]]["description"] = i.get("properties", {}).get("description", "")
        return_dict[i["name"]]["folder"] = [i.get("properties", {}).get("folder", "")]
        return_dict[i["name"]]["feature_type"] = "Numeric"
        return_dict[i["name"]]["expression"] = ""

    return return_dict


def _parse_calculated_features(
    data_model_name,
    project_dict,
):
    """Loads _feature_dict with information regarding calculated features.

    Args:
        data_model_name (str): the name of the data_model of interest
        project_dict (dict): the metadata of the project to extract

    Returns:
        Dict[Dict]: a dict of dicts of the form 'query_name':{metadata}
    """
    return_dict = {}
    cube = [
        x for x in project_dict.get("cubes", {}).get("cube", []) if x.get("name") == data_model_name
    ][0]
    refs = [x["id"] for x in cube.get("calculated-members", {}).get("calculated-member-ref", [])]
    for feature in project_dict.get("calculated-members", {}).get("calculated-member", []):
        if feature["id"] in refs:
            return_dict[feature["name"]] = {
                "caption": feature.get("properties", {}).get("caption", ""),
                "atscale_type": "Calculated",
                # "aggregation_type": "Calculated",
                "description": feature.get("properties", {}).get("description", ""),
                "folder": [feature.get("properties", {}).get("folder", "")],
                "feature_type": "Numeric",
                "expression": feature.get("expression", ""),
            }
    return return_dict


def _parse_denormalized_categorical_features(
    data_model_name,
    project_dict,
):
    """Loads _feature_dict with information regarding denormalized categorical features.

    Args:
        data_model_name (str): the name of the data_model of interest
        project_dict (dict): the metadata of the project to extract

    Returns:
        Dict[Dict]: a dict of dicts of the form 'query_name':{metadata}
    """
    return_dict = {}

    cube = [x for x in project_dict["cubes"]["cube"] if x["name"] == data_model_name][0]
    if "attributes" not in cube or "keyed-attribute" not in cube["attributes"]:
        return {}

    feature_info = [x for x in cube["attributes"]["keyed-attribute"]]
    project_attributes = [
        x
        for x in project_dict.get("attributes", {}).get("keyed-attribute", [])
        + project_dict.get("attributes", {}).get("attribute", [])
    ]

    folder_info = {}
    metrical_attributes = []
    for dimension in cube["dimensions"]["dimension"]:
        for hierarchy in dimension["hierarchy"]:
            hierarchy_name = hierarchy["name"]
            if "folder" in hierarchy["properties"]:
                this_folder = hierarchy["properties"]["folder"]
            else:
                this_folder = ""
            for level in hierarchy["level"]:
                level_attr_id = level["primary-attribute"]
                secondary_attributes = []
                if "keyed-attribute-ref" in level:  # degenerates can't rp so these are secondaries
                    for attr in level["keyed-attribute-ref"]:
                        secondary_attributes.append(attr["attribute-id"])
                if "attribute-ref" in level:  # these are metricals
                    for attr in level["attribute-ref"]:
                        metrical_attributes.append(attr["attribute-id"])
                        secondary_attributes.append(attr["attribute-id"])
                for attr_id in [level_attr_id] + secondary_attributes:
                    if attr_id in folder_info:
                        if hierarchy_name not in folder_info[attr_id]["hierarchy"]:
                            folder_info[attr_id]["folder"].append(this_folder)
                            folder_info[attr_id]["hierarchy"].append(hierarchy_name)
                    else:
                        secondary_attribute = attr_id != level_attr_id
                        folder_info[attr_id] = {
                            "folder": [this_folder],
                            "hierarchy": [hierarchy_name],
                            "dimension": dimension["name"],
                            "atscale_type": level.get("properties", {}).get(
                                "level-type",
                                "Regular",
                            ),
                            "secondary_attribute": secondary_attribute,
                        }
                        if attr_id in metrical_attributes:
                            folder_info[attr_id]["atscale_type"] = "Aggregate"
    for i in feature_info + project_attributes:
        if i["id"] in folder_info.keys():
            is_secondary = folder_info.get(i["id"], {}).get("secondary_attribute")
            properties = i.get("properties", {})
            feature = {
                "caption": properties.get("caption", ""),
                "atscale_type": folder_info.get(i["id"], {}).get("atscale_type", "Regular"),
                "description": properties.get("description", ""),
                "hierarchy": folder_info.get(i["id"], {}).get("hierarchy", ""),
                "dimension": folder_info.get(i["id"], {}).get("dimension", ""),
                "folder": folder_info.get(i["id"], {}).get("folder", ""),
                "feature_type": "Categorical",
                "secondary_attribute": is_secondary,
            }
            if is_secondary:
                secondary_folder = properties.get("folder")  # folder of secondary attribute
                if secondary_folder is not None:
                    feature["folder"] = [secondary_folder]
                feature["hierarchy"] = [i["name"]]
            if i["id"] in metrical_attributes:
                feature.pop("hierarchy")
                feature.pop("dimension")
                feature.pop("secondary_attribute")
                feature["atscale_type"] = _get_agg_type(i)
                feature["feature_type"] = "Numeric"
                feature["expression"] = ""
            return_dict[i["name"]] = feature
    return return_dict


def _get_published_features(
    data_model,
    feature_list: List[str] = None,
    folder_list: List[str] = None,
    feature_type: FeatureType = FeatureType.ALL,
) -> dict:
    """Gets the feature names and metadata for each feature in the published DataModel.

    Args:
        data_model (DataModel): The published atscale data model to get the features of via dmv
        feature_list (List[str], optional): A list of features to return. Defaults to None to return all.
        folder_list (List[str], optional): A list of folders to filter by. Defaults to None to ignore folder.
        feature_type (FeatureType, optional): The type of features to filter by. Options
            include FeatureType.ALL, FeatureType.CATEGORICAL, or FeatureType.NUMERIC. Defaults to ALL.

    Returns:
        dict: A dictionary of dictionaries where the feature names are the keys in the outer dictionary
                while the inner keys are the following:
                'atscale_type'(value is a level-type, 'Aggregate', or 'Calculated'),
                'description', 'expression', caption, 'folder', 'data_type', and 'feature_type'(value is Numeric or Categorical).
    """
    level_filter_by = {}
    measure_filter_by = {}
    hier_filter_by = {}
    if feature_list:
        feature_list = [feature_list] if isinstance(feature_list, str) else feature_list
        level_filter_by[Level.name] = feature_list
        measure_filter_by[Measure.name] = feature_list
    if folder_list:
        folder_list = [folder_list] if isinstance(folder_list, str) else folder_list
        hier_filter_by[Hierarchy.folder] = folder_list
        measure_filter_by[Measure.folder] = folder_list

    feature_dict = {}

    catalog_licensed = data_model.project._atconn._validate_license("data_catalog_api")

    if feature_type is FeatureType.ALL or feature_type is FeatureType.CATEGORICAL:
        hier_dict = get_dmv_data(
            model=data_model, fields=[Hierarchy.folder], filter_by=hier_filter_by
        )
        level_filter_by[Level.hierarchy] = list(hier_dict.keys())
        query_fields = [
            Level.type,
            Level.description,
            Level.hierarchy,
            Level.dimension,
            Level.caption,
            Level.data_type,
        ]
        if catalog_licensed:
            query_fields.append(Level.secondary_attribute)
        dimension_dict = get_dmv_data(
            model=data_model,
            fields=query_fields,
            filter_by=level_filter_by,
        )
        for name, info in dimension_dict.items():
            # if a level was duplicated we might have multiple hierarchies which could mean multiple folders
            folder = []
            if type(info[Level.hierarchy.name]) is list:
                for hierarchy_name in info[Level.hierarchy.name]:
                    if hier_dict.get(hierarchy_name):
                        folder.append(hier_dict[hierarchy_name][Hierarchy.folder.name])
            else:
                folder.append(hier_dict[info[Level.hierarchy.name]][Hierarchy.folder.name])
                info[Level.hierarchy.name] = [info[Level.hierarchy.name]]

            feature_dict[name] = {
                "caption": info[Level.caption.name],
                "atscale_type": info[Level.type.name],
                "data_type": info[Level.data_type.name],
                "description": info[Level.description.name],
                "hierarchy": info[Level.hierarchy.name],
                "dimension": info[Level.dimension.name],
                "folder": folder,
                "feature_type": "Categorical",
            }
            if catalog_licensed:
                feature_dict[name]["secondary_attribute"] = info[Level.secondary_attribute.name]
            else:
                feature_dict[name]["secondary_attribute"] = False
    if feature_type is FeatureType.ALL or feature_type is FeatureType.NUMERIC:
        query_fields = [
            Measure.type,
            Measure.description,
            Measure.folder,
            Measure.caption,
            Measure.data_type,
        ]
        if catalog_licensed:
            query_fields.append(Measure.expression)
        measure_dict = get_dmv_data(
            model=data_model, fields=query_fields, filter_by=measure_filter_by
        )
        for name, info in measure_dict.items():
            agg_type = info[Measure.type.name]
            feature_dict[name] = {
                "caption": info[Measure.caption.name],
                "atscale_type": agg_type if agg_type != "Calculated" else "Calculated",
                # "aggregation_type": agg_type,
                "data_type": info[Measure.data_type.name],
                "description": info[Measure.description.name],
                "folder": [info[Measure.folder.name]],
                "feature_type": "Numeric",
            }
            if catalog_licensed:
                feature_dict[name]["expression"] = info[Measure.expression.name]
            else:
                feature_dict[name]["expression"] = ""

    return feature_dict


def _create_perspective(
    data_model,
    name: str,
    dimensions: List[str] = None,
    hierarchies: List[str] = None,
    categorical_features: List[str] = None,
    numeric_features: List[str] = None,
    publish: bool = True,
    update: bool = False,
) -> str:
    """Creates a perspective that hides the inputs, using the current data model as a base.

    Args:
        data_model (DataModel): The data model to work off of
        name (str): Creates a new perspective based on the current data model. Objects passed in will be hidden by the perspective.
        dimensions (List[str], optional): Dimensions to hide. Defaults to None.
        hierarchies (List[str], optional): Hierarchies to hide. Defaults to None.
        categorical_features (List[str], optional): Categorical features to hide. Defaults to None.
        numeric_features (List[str], optional): Numeric features to hide. Defaults to None.
        publish (bool, optional): Whether to publish the updated project. Defaults to True.
        update (bool, optional): Whether to update an existing perpective. Defaults to False to create a new one.

    Returns:
        str: The id of the created perspective
    """
    project_dict = data_model.project._get_dict()
    project_dict.setdefault("perspectives", {})
    project_dict["perspectives"].setdefault("perspective", [])
    if update:
        perspective_ids = [
            x["id"] for x in project_dict["perspectives"]["perspective"] if x["name"] == name
        ]
        if len(perspective_ids) == 0:
            raise atscale_errors.UserError(f"No perspective named: '{name}' exists")
        perspective_id = perspective_ids[0]
    else:
        perspective_names = [x["name"] for x in project_dict["perspectives"]["perspective"]]
        if name in perspective_names:
            raise ValueError(f"A perspective named: '{name}' already exists")
        perspective_id = str(uuid.uuid4())

    numeric_features_info = _get_draft_features(
        project_dict, data_model_name=data_model.name, feature_type=FeatureType.NUMERIC
    )
    categorical_feature_info = _get_draft_features(
        project_dict, data_model_name=data_model.name, feature_type=FeatureType.CATEGORICAL
    )
    hierarchy_info = data_model.get_hierarchies(secondary_attribute=False)
    hierarchy_roleplays = {}
    dimension_roleplays = {}
    for info in categorical_feature_info.values():
        for hier, base_hier in zip(
            info.get("hierarchy"), info.get("base_hierarchy", info.get("hierarchy"))
        ):
            if hier not in hierarchy_roleplays:
                hierarchy_roleplays[hier] = {
                    "base_hierarchy": base_hier,
                    "ref_id": info.get("roleplay_ref_id", ""),
                }
        if info.get("dimension") not in dimension_roleplays:
            dimension_roleplays[info.get("dimension")] = {
                "base_dimension": info.get("base_dimension", info.get("dimension")),
                "ref_id": info.get("roleplay_ref_id", ""),
            }
    if numeric_features:
        model_utils._check_features(
            numeric_features,
            numeric_features_info,
            errmsg=CheckFeaturesErrMsg.NUMERIC.get_errmsg(is_published=False),
        )
    if categorical_features:
        model_utils._check_features(
            categorical_features,
            categorical_feature_info,
            errmsg=CheckFeaturesErrMsg.CATEGORICAL.get_errmsg(is_published=False),
        )
    if hierarchies:
        model_utils._check_features(
            features=hierarchies,
            check_list=hierarchy_info,
            errmsg=CheckFeaturesErrMsg.HIERARCHY.get_errmsg(is_published=False),
        )

    cube = project_parser.get_cube(project_dict=project_dict, id=data_model.cube_id)
    # create the base dict for the perspective that we will fill in
    perspective_dict = {
        "cube-ref": data_model.cube_id,
        "id": perspective_id,
        "name": name,
        "calculated-members": {},
        "flat-attributes": {},
        "flat-dimensions": {},
    }
    # numeric features can either be measures or calculated measures so we look up which each inout is and add it to the right section
    if numeric_features:
        measures_dict = {"flat-attribute-ref": []}
        calculated_measures_dict = {"calculated-member-ref": []}
        for feature in numeric_features:
            # need to handle possible roleplaying because of metrical attributes
            base_feature_name = numeric_features_info[feature].get("base_name", feature)
            if numeric_features_info[feature]["atscale_type"] != "Calculated":
                measure_id = [
                    x["id"]
                    for x in project_dict.get("attributes", {}).get("attribute", [])
                    + cube.get("attributes", {}).get("attribute", [])
                    if x["name"] == base_feature_name
                ][0]
                measure_dict = {
                    "id": measure_id,
                    "properties": {"visible": False},
                    "ref-path": {},
                }
                if base_feature_name != feature:
                    measure_dict["ref-path"] = {
                        "ref": [{"id": numeric_features_info[feature].get("roleplay_ref_id", "")}]
                    }
                measures_dict["flat-attribute-ref"].append(measure_dict)
            else:
                calculated_measure_id = [
                    x["id"]
                    for x in project_dict["calculated-members"]["calculated-member"]
                    if x["name"] == feature
                ][0]
                calculated_measure_dict = {
                    "id": calculated_measure_id,
                    "properties": {"visible": False},
                }
                calculated_measures_dict["calculated-member-ref"].append(calculated_measure_dict)
        perspective_dict["flat-attributes"] = measures_dict
        perspective_dict["calculated-members"] = calculated_measures_dict

    dimensions_dict = {"flat-dimension-ref": []}
    # we want to keep track of if a dimension or hierarchy is already hidden because their children will also be hidden automatically
    hidden_dimensions = []
    hidden_hierarchies = []
    # first we do dimensions because they are the highest level
    if dimensions:
        for dimension in dimensions:
            for dim in project_dict.get("dimensions", {}).get("dimension", []) + cube.get(
                "dimensions", {}
            ).get("dimension", []):
                if dim.get("name") == dimension_roleplays.get(dimension, {}).get("base_dimension"):
                    dimension_dict = {"id": dim.get("id"), "properties": {"visible": False}}
                    if dimension != dimension_roleplays[dimension]["base_dimension"]:
                        dimension_dict["ref-path"] = {
                            "ref": [{"id": dimension_roleplays[dimension]["ref_id"]}]
                        }
                    dimensions_dict["flat-dimension-ref"].append(dimension_dict)
                    hidden_dimensions.append(dimension)
                    break
            else:
                raise atscale_errors.UserError(f"No dimension named: '{dimension}' found")
    # second are hierarchies
    if hierarchies:
        for hierarchy in hierarchies:
            for dimension in project_dict.get("dimensions", {}).get("dimension", []) + cube.get(
                "dimensions", {}
            ).get("dimension", []):
                for hier in dimension.get("hierarchy", []):
                    if hier.get("name") == hierarchy_roleplays[hierarchy]["base_hierarchy"]:
                        # if the dimension is already hidden do nothing and move on
                        if dimension.get("name") not in hidden_dimensions:
                            hierarchy_dict = {
                                "id": hier.get("id"),
                                "properties": {"visible": False},
                            }
                            # check if the dimension already has an entry because of another object in it
                            match = False
                            for dim in dimensions_dict["flat-dimension-ref"]:
                                if dim.get("id") == dimension.get("id"):
                                    # if there is a ref path we check if it is for the same roleplay
                                    if dim.get("ref-path", {}).get("ref", []):
                                        if (
                                            dim.get("ref-path", {}).get("ref", [])[0].get("id", "")
                                            == hierarchy_roleplays[hierarchy]["ref_id"]
                                        ):
                                            match = True
                                    # if no ref path the dim already in the perspective isn't roleplayed so check if the same is true for the hierarchy
                                    else:
                                        if (
                                            hierarchy
                                            == hierarchy_roleplays[hierarchy]["base_hierarchy"]
                                        ):
                                            match = True
                                    if match:
                                        dim.setdefault("flat-hierarchy-ref", [])
                                        dim["flat-hierarchy-ref"].append(hierarchy_dict)
                                        break
                            else:
                                dimension_dict = {
                                    "id": dimension.get("id"),
                                    "flat-hierarchy-ref": [hierarchy_dict],
                                    "properties": {"visible": True},
                                }
                                if hierarchy != hierarchy_roleplays[hierarchy]["base_hierarchy"]:
                                    dimension_dict["ref-path"] = {
                                        "ref": [{"id": hierarchy_roleplays[hierarchy]["ref_id"]}]
                                    }
                                dimensions_dict["flat-dimension-ref"].append(dimension_dict)
                            hidden_hierarchies.append(hierarchy)
                            break
                else:
                    continue
                break
    # last we do the attributes
    if categorical_features:
        for categorical_feature in categorical_features:
            # we need the hierarchy info for the attribute as well as whether it is a secondary attribute
            # if the level is in multiple hierarchies it doesn't matter which we use so we can just grab the first one
            hierarchies = categorical_feature_info[categorical_feature]["hierarchy"]
            dim = categorical_feature_info[categorical_feature]["dimension"]
            secondary_attribute = hierarchy_info.get(hierarchies[0], {}).get(
                "secondary_attribute", True
            )
            # If the hierarchy is already hidden move on
            if (
                dim in hidden_dimensions
                or len([x for x in hierarchies if x not in hidden_hierarchies]) == 0
            ):
                continue
            for dimension in project_dict.get("dimensions", {}).get("dimension", []) + cube.get(
                "dimensions", {}
            ).get("dimension", []):
                for hier in dimension.get("hierarchy", []):
                    for hierarchy in hierarchies:
                        if secondary_attribute or (
                            hier.get("name") == hierarchy_roleplays[hierarchy]["base_hierarchy"]
                            and hierarchy not in hidden_hierarchies
                        ):
                            for attribute in project_dict.get("attributes", {}).get(
                                "keyed-attribute", []
                            ) + cube.get("attributes", {}).get("keyed-attribute", []):
                                if attribute.get("name") == categorical_feature_info[
                                    categorical_feature
                                ].get("base_name", categorical_feature):
                                    # if it is a secondary attribute it goes in the same section as the measures for some reason
                                    if secondary_attribute:
                                        attribute_dict = {
                                            "id": attribute.get("id"),
                                            "properties": {"visible": False},
                                            "ref-path": {},
                                        }
                                        if categorical_feature != categorical_feature_info[
                                            categorical_feature
                                        ].get("base_name", categorical_feature):
                                            attribute_dict["ref-path"]["ref"] = [
                                                {
                                                    "id": categorical_feature_info[
                                                        categorical_feature
                                                    ]["roleplay_ref_id"]
                                                }
                                            ]
                                        perspective_dict["flat-attributes"].setdefault(
                                            "flat-attribute-ref", []
                                        )
                                        perspective_dict["flat-attributes"][
                                            "flat-attribute-ref"
                                        ].append(attribute_dict)

                                        break
                                    level_dict = {
                                        "primary-attribute": attribute.get("id"),
                                        "properties": {"visible": False},
                                    }
                                    hierarchy_dict = {
                                        "id": hier.get("id"),
                                        "flat-level-ref": [level_dict],
                                        "properties": {"visible": True},
                                    }
                                    # check if we already have entries for the dimension and hierarchy and create the entries if not
                                    match = False
                                    for dim in dimensions_dict["flat-dimension-ref"]:
                                        if dim.get("id") == dimension.get("id"):
                                            if dim.get("ref-path", {}).get("ref", []):
                                                if dim.get("ref-path", {}).get("ref", [])[0].get(
                                                    "id", ""
                                                ) == categorical_feature_info[
                                                    categorical_feature
                                                ].get(
                                                    "roleplay_ref_id", ""
                                                ):
                                                    match = True
                                            # if no ref path the dim already in the perspective isn't roleplayed so check if the same is true for the feature
                                            else:
                                                if categorical_feature == categorical_feature_info[
                                                    categorical_feature
                                                ].get("base_name", categorical_feature):
                                                    match = True
                                        if match:
                                            for h in dim.get("flat-hierarchy-ref", []):
                                                if h.get("id") == hier.get("id"):
                                                    h.setdefault("flat-level-ref", [])
                                                    h["flat-level-ref"].append(level_dict)
                                                    break
                                            else:
                                                hierarchy_dict = {
                                                    "id": hier.get("id"),
                                                    "properties": {"visible": True},
                                                }
                                                dim.setdefault("flat-hierarchy-ref", [])
                                                dim["flat-hierarchy-ref"].append(hierarchy_dict)
                                            break
                                    else:
                                        dimension_dict = {
                                            "id": dimension.get("id"),
                                            "flat-hierarchy-ref": [hierarchy_dict],
                                            "properties": {"visible": True},
                                        }
                                        if categorical_feature != categorical_feature_info[
                                            categorical_feature
                                        ].get("base_name", categorical_feature):
                                            dimension_dict["ref-path"] = {
                                                "ref": [
                                                    {
                                                        "id": categorical_feature_info[
                                                            categorical_feature
                                                        ]["roleplay_ref_id"]
                                                    }
                                                ]
                                            }
                                        dimensions_dict["flat-dimension-ref"].append(dimension_dict)
                                    break
                            break
                # else:
                #     continue
                # break
    perspective_dict["flat-dimensions"] = dimensions_dict
    if update:
        project_dict["perspectives"]["perspective"] = [
            x if x["id"] != perspective_id else perspective_dict
            for x in project_dict["perspectives"]["perspective"]
        ]
    else:
        project_dict.get("perspectives", {}).get("perspective", []).append(perspective_dict)
    data_model.project._update_project(project_dict, publish)
    return perspective_id
