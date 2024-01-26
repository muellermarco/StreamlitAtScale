import logging
import uuid
import json
from typing import List, Dict, Tuple, Union
from pandas import DataFrame

from atscale.data_model import data_model_helpers as dmh
from atscale.errors import atscale_errors
from atscale.base import enums, templates
from atscale.base.enums import Aggs, CheckFeaturesErrMsg
from atscale.parsers import data_model_parser, project_parser, dictionary_parser
from atscale.utils import dimension_utils, feature_utils, project_utils, time_utils, db_utils
from atscale.db.sql_connection import SQLConnection
from atscale.connection.connection import _Connection
from atscale.base import endpoints
from inspect import getfullargspec
from atscale.utils.validation_utils import validate_by_type_hints


logger = logging.getLogger(__name__)


def _add_data_set_ref(
    model_dict: Dict,
    dataset_id: str,
    key_refs=None,
    attribute_refs=None,
    allow_aggregates=True,
    create_hinted_aggregate=False,
):
    """Adds a data-set-ref into the provided model_dict with the given dataset_id

    Args:
        model_dict (Dict): the dict representation of the datamodel to add the dataset to
        dataset_id (str): the id of the dataset to create
    """
    data_set_ref = templates.create_dataset_ref_dict(
        dataset_id=dataset_id,
        key_refs=key_refs,
        attribute_refs=attribute_refs,
        allow_aggregates=allow_aggregates,
        create_hinted_aggregate=create_hinted_aggregate,
    )
    model_dict.setdefault("data-sets", {})
    model_dict["data-sets"].setdefault("data-set-ref", [])
    model_dict["data-sets"]["data-set-ref"].append(data_set_ref)


def _check_conflicts(
    to_add: Union[list, dict, set, str],
    data_model: "DataModel" = None,
    use_published: bool = False,
    project_dict: dict = None,
    errmsg: str = None,
    diff_in_msg: bool = True,
    preexisting: Union[list, dict, set, str] = None,
):
    feature_type = enums.FeatureType.ALL
    if isinstance(to_add, str):
        to_add = [to_add]
    elif isinstance(to_add, dict):
        to_add = list(to_add.keys())
    else:
        to_add = list(to_add)
    if preexisting is not None:
        preexisting = set(preexisting)
    elif use_published:
        preexisting = data_model.get_features(feature_type=feature_type)
    else:
        project_dict = data_model.project._get_dict() if project_dict is None else project_dict
        preexisting = dmh._get_draft_features(
            project_dict=project_dict, feature_type=feature_type, data_model_name=data_model.name
        )
    conflicts = [feat for feat in to_add if feat in preexisting]
    if len(conflicts) > 0:
        if errmsg:
            errmsg = errmsg.format(conflicts) if diff_in_msg else errmsg
        elif len(conflicts) == 1:
            errmsg = f"Invalid name: '{conflicts[0]}'. A feature already exists with that name"
        else:
            errmsg = (
                f"Invalid feature names: {conflicts}. Query name collision with existing features."
            )
        raise atscale_errors.UserError(errmsg)


def _check_features(
    features: Union[list, dict, set],
    check_list: Union[list, dict, set],
    errmsg: str = None,
    diff_in_msg: bool = True,
):
    """Checks that the given feature(s) exist(s) within a specified list of features.

    Args:
        features (Union[list, dict, set]): feature(s) to confirm exist in the provided list. If a dict is passed,
                                           the keys will be used.
        check_list (Union[list, dict, set]): features of the data model to check against. If a dict is passed, the keys
                                             will be used.
        errmsg (str, optional): Error message to raise if feature not found. Defaults to None.
        diff_in_msg (bool, optional): Whether format(sorted(non_existent_features)) should be called on the given errmsg.
                                      Defaults to True.

    Raises:
        atscale_errors.UserError: error is raised if any features of interest not found, can be customized via errmsg arg

    Returns:
        boolean: True if no error found
    """
    set_dif = set(features) - set(check_list)
    if len(set_dif) > 0:
        if errmsg:
            errmsg = errmsg.format(sorted(list(set_dif))) if diff_in_msg else errmsg
            raise atscale_errors.UserError(errmsg)
        else:
            raise atscale_errors.UserError(CheckFeaturesErrMsg.ALL.get_errmsg(is_published=False))
    return True


def _create_dataset_relationship(
    atconn,
    project_dict,
    cube_id,
    database,
    schema,
    table_name,
    join_features,
    warehouse_id,
    join_columns=None,
    roleplay_features=None,
    table_columns=None,
    allow_aggregates=True,
):
    """Mutates and returns the given project_dict to create a dataset, join the given features, and join the dataset
    to the cube if it was not already.

    Args:
        atconn (_Connection): A Connection object connected to the server of the project the parameters correspond to.
        project_dict (dict): The project_dict to mutate and return
        cube_id (str): The id of the cube the dataset will be joined to.
        database (str): The database that the created dataset will point at.
        schema (str): The schema that the created dataset will point at.
        table_name (str): The table that the created dataset will point at.
            This will also become the name of the dataset.
        join_features (list): a list of features in the data model to use for joining.
        join_columns (list, optional): The columns in the dataframe to join to the join_features. List must be either
            None or the same length and order as join_features. Defaults to None to use identical names to the
            join_features. If multiple columns are needed for a single join they should be in a nested list
        roleplay_features (list, optional): The roleplays to use on the relationships. List must be either
            None or the same length and order as join_features. Use '' to not roleplay that relationship.
            Defaults to None.
        table_columns (list, optional): The columns in the table to use for the dataset as returned by _get_table_columns. Defaults to None.
        allow_aggregates (bool, optional): Whether to allow aggregates to be built off of the dataset. Defaults to True.

    Returns:
        Dict: The mutated project_dict
    """
    project_datasets = project_parser.get_datasets(project_dict)

    url = endpoints._endpoint_warehouse(atconn, f"/conn/{warehouse_id}/tables/cacheRefresh")
    atconn._submit_request(request_type=enums.RequestType.POST, url=url)

    # look for a dataset that may already have the table_name for the table we're trying to join to the cube (meaning the table
    # already exists and we're just replacing it or appending it)
    dataset_id = project_parser.find_dataset_with_table(
        project_datasets, table_name=table_name, schema=schema, database=database
    )

    if not dataset_id:  # then we have to create a project_dataset
        # we'll use table_columns for creating a dataset below and then more logic after that
        if table_columns is None:
            table_columns = atconn._get_table_columns(
                warehouse_id=warehouse_id, table_name=table_name, database=database, schema=schema
            )
        existing_datasets = [
            x["name"] for x in project_parser.get_datasets(project_dict=project_dict)
        ]
        dataset_name = table_name
        count = 1
        while dataset_name in existing_datasets:
            dataset_name = f"{table_name}_{count}"
            count += 1
        # the prior code assumed a schema but checked if database was None prior to setting
        project_dataset, dataset_id = project_utils.create_dataset(
            table_name,
            warehouse_id,
            table_columns,
            database,
            schema,
            dataset_name=dataset_name,
            allow_aggregates=allow_aggregates,
        )
        # and we'll add the newly minted dataset to the project_dict
        project_utils.add_dataset(project_dict=project_dict, dataset=project_dataset)
    else:
        dataset_name = project_parser.get_dataset(project_dict=project_dict, dataset_id=dataset_id)[
            "name"
        ]

    return _create_dataset_relationship_from_dataset(
        project_dict=project_dict,
        cube_id=cube_id,
        dataset_name=dataset_name,
        join_features=join_features,
        join_columns=join_columns,
        roleplay_features=roleplay_features,
        allow_aggregates=allow_aggregates,
    )


def _create_dataset_relationship_from_dataset(
    project_dict: dict,
    cube_id: str,
    dataset_name: str,
    join_features: List[str],
    join_columns: List[List[str]] = None,
    roleplay_features: List[str] = None,
    allow_aggregates: bool = True,
    create_hinted_aggregate: bool = False,
):
    """Mutates and returns the given project_dict to join the given features and join the dataset, of the given name,
    to the cube (if not joined already) of the given cube_id.

    Args:
        project_dict (dict): The project_dict to mutate and return.
        cube_id (str): The id of the cube the dataset will be joined to.
        dataset_name (str): The name of the dataset to target. This dataset must exist in project_datasets.
            This will also become the name of the dataset.
        join_features (list): a list of features in the data model to use for joining.
        join_columns (list, optional): The columns in the dataframe to join to the join_features. List must be either
            None or the same length and order as join_features. Defaults to None to use identical names to the
            join_features. If multiple columns are needed for a single join they should be in a nested list
        roleplay_features (list, optional): The roleplays to use on the relationships. List must be either
            None or the same length and order as join_features. Use '' to not roleplay that relationship.
            Defaults to None.
        allow_aggregates (bool, optional): Whether to allow aggregates to be built off of the dataset. Defaults to True.
        create_hinted_aggregate(bool, optional): Whether to generate an aggregate table for all measures and keys in this QDS to improve join performance. Defaults to False.

    Returns:
        Dict: The mutated project_dict
    """
    dataset_id = project_parser.get_dataset(project_dict=project_dict, dataset_name=dataset_name)[
        "id"
    ]

    key_refs = []
    attribute_refs = []
    cube_dict = project_parser.get_cube(project_dict, cube_id)

    found_dataset_ref = False
    cube_dict.setdefault("data-sets", {})
    cube_dict["data-sets"].setdefault("data-set-ref", [])
    for ds_ref in cube_dict["data-sets"]["data-set-ref"]:
        if ds_ref["id"] == dataset_id:
            found_dataset_ref = True
            data_set_ref = ds_ref
            break
    # If we had to create a dataset for the project to point at the new table, then we need to ensure there is also one in the cube referencing it.
    # This check previously referred back to "found" which was based on the project data set being there, but this is really about whether we
    # find it in the cube, which is in the logic immediately above, so I'll do the boolean there instead.
    if not found_dataset_ref:
        data_set_ref = templates.create_dataset_ref_dict(
            dataset_id,
            allow_aggregates=allow_aggregates,
            create_hinted_aggregate=create_hinted_aggregate,
        )

    dataset_key_refs = data_set_ref.get("logical", {}).get("key-ref", [])
    dataset_attribute_refs = data_set_ref.get("logical", {}).get("attribute-ref", [])

    attribute_dict = {}
    for attribute in project_dict.get("attributes", {}).get("keyed-attribute", []):
        attribute_dict[attribute["name"]] = {"dict": attribute, "type": "project"}
    for attribute in cube_dict.get("attributes", {}).get("keyed-attribute", []):
        attribute_dict[attribute["name"]] = {"dict": attribute, "type": "cube"}

    for join_feature, join_column, roleplay_feature in zip(
        join_features, join_columns, roleplay_features
    ):
        # join_feature: str, join_column: List[str], roleplay_feature: str
        # Cols is a list because a level can have a compound key (two key columns) for example: month could have YEAR and MONTH columns since MONTH is just a number from 1-12?

        # looks for an attribute that matches the join feature. If one is found,
        # it determines if user specified it as a roleplay feature. If they did, it looks for the name
        # at the current location to see if it matches the name provided by the user for the roleplay feature
        # and if that is not found, it appends the current name in place, to the provided roleplay  feature,
        # and constructs the json around it, like ref_id, and sets it up to reference the dimension id
        if roleplay_feature != "":
            if "{0}" not in roleplay_feature:
                roleplay_feature = roleplay_feature + " {0}"

        dimension = attribute_dict[join_feature]["dict"]
        dimension_type = attribute_dict[join_feature]["type"]
        # If we already hava a ref skip it
        if (
            len(
                [
                    x
                    for x in dataset_key_refs
                    if x["id"] == dimension["key-ref"]
                    and x.get("ref-path", {}).get("new-ref", {}).get("ref-naming", "")
                    == roleplay_feature
                ]
            )
            == 0
        ):
            key_ref = {
                "id": dimension["key-ref"],
                "unique": False,
                "complete": "partial" if dimension_type == "cube" else "false",
                "column": join_column,
            }
            if roleplay_feature != "":
                ref_id = str(uuid.uuid4())
                ref_path = {
                    "new-ref": {
                        "attribute-id": dimension["id"],
                        "ref-id": ref_id,
                        "ref-naming": roleplay_feature,
                    }
                }
                key_ref["ref-path"] = ref_path
            key_refs.append(key_ref)
        if (
            dimension_type == "cube"
            and len([x for x in dataset_attribute_refs if x["id"] == dimension["id"]]) == 0
        ):
            attr = {"id": dimension["id"], "complete": "partial", "column": join_column}
            attribute_refs.append(attr)

    data_set_ref["logical"].setdefault("key-ref", [])
    data_set_ref["logical"]["key-ref"] = data_set_ref["logical"]["key-ref"] + key_refs
    data_set_ref["logical"].setdefault("attribute-ref", [])
    data_set_ref["logical"]["attribute-ref"] = (
        data_set_ref["logical"]["attribute-ref"] + attribute_refs
    )
    # If we found the dataset ref we are updating in place but if not we need to add it to the list
    if not found_dataset_ref:
        cube_dict.setdefault("data-sets", {})
        cube_dict["data-sets"].setdefault("data-set-ref", [])
        cube_dict["data-sets"]["data-set-ref"].append(data_set_ref)
    return project_dict


def _get_column_type_category(
    column_type: str,
) -> str:
    """returns the category of the given column type

    Args:
        column_type (str): the column type to look up

    Returns:
        str: the category of the column type ('categorical', 'date', or 'numeric')
    """
    type_dict = {
        "string": "categorical",
        "char": "categorical",
        "varchar": "categorical",
        "nchar": "categorical",
        "nvarchar": "categorical",
        "bool": "categorical",
        "boolean": "categorical",
        "bit": "categorical",
        "date": "date",
        "datetime": "datetime",
        "timestamp": "datetime",
        "timestamp_ntz": "datetime",
        "timestamp_ltz": "datetime",
        "timestamp_tz": "datetime",
        # 'time': 'date',
        "int": "numeric",
        "bigint": "numeric",
        "smallint": "numeric",
        "tinyint": "numeric",
        "integer": "numeric",
        "float": "numeric",
        "double": "numeric",
        "decimal": "numeric",
        "dec": "numeric",
        "long": "numeric",
        "numeric": "numeric",
        "int64": "numeric",
        "float64": "numeric",
        "real": "numeric",
    }
    return type_dict.get(column_type.lower().split("(")[0], "unsupported")


def _create_semantic_model(
    atconn: _Connection,
    dbconn: SQLConnection,
    table_name: str,
    project_dict: dict,
    cube_id: str,
    dataset_id: str,
    columns: list,
    generate_date_table: bool,
    default_aggregation_type: Aggs = Aggs.SUM,
):
    """Mutates the provided project_dict to add a semantic layer. NOTE: This does not update the project! Calling methods must still update and publish the project using the resulting project_dict.

    Args:
        atconn (_Connection): AtScale connection
        dbconn (SQLConnection): DB connection
        table_name (str): the name of the table to create a semantic table for
        project_dict (dict): the project dictionary (generally sparse result of creating a new project and adding a dataset)
        cube_id (str): the id for the cube (generally sparse result of creating a new project)
        dataset_id (str): the id for the dataset associated with the table_name for which we will create a semantic layer
        columns (list[tuple]): columns of the table associated with table_name and dataset_id as AtScale sees them, generally with a name and type for each
        generate_date_table (bool): whether to generate a date dimension table. False will use degenerate dimensions for dates
        default_aggregation_type (Aggs): the default aggregation type for numeric columns. Defaults to SUM
    """
    date_cols = []
    for column in columns:
        column_name = column[0]
        column_type = _get_column_type_category(column[1])

        if column_type == "unsupported":
            logger.warning(
                f"column {column_name} is of unsupported type {column[1].lower().split('(')[0]}, skipping the modeling of this column"
            )
            continue

        # make an agg for all the columns we can
        elif column_type == "numeric":
            feature_utils._create_aggregate_feature(
                project_dict=project_dict,
                cube_id=cube_id,
                dataset_id=dataset_id,
                column_name=column_name,
                new_feature_name=f"{column_name}_{default_aggregation_type.name}",
                aggregation_type=default_aggregation_type,
            )

        # this does a string comparison to see if this column type is a DateTime
        elif column_type in ["date", "datetime"]:
            date_cols.append((column_name, column_type))

        # only other option is if it is categorical
        else:
            dimension_utils.create_categorical_dimension_for_column(
                project_dict=project_dict,
                cube_id=cube_id,
                dataset_id=dataset_id,
                column_name=column_name,
            )

    dataset = project_parser.get_dataset(project_dict=project_dict, dataset_id=dataset_id)
    date_key_feature = None
    for column_name, column_type in date_cols:
        # Add a dimension for the date column
        if not generate_date_table:
            try:  # determine_time_levels depends on count(distinct(column_name)) sql working. If the db errors out, then we just skip
                # if the column_type_category is time then start level should be hours

                # time is not currently supported by atscale, we need to look into this with the modeler team
                # if column[1].lower().split('(')[0] == 'time':
                #     time_levels = time_utils.determine_time_levels(
                #         dbconn=dbconn, table_name=table_name, column=column_name, start_level= enums.TimeLevels.Hour)
                # else:
                end_level = max([e.index for e in enums.TimeLevels])
                if column_type == "date":
                    end_level = enums.TimeLevels.Day

                time_levels = time_utils.determine_time_levels(
                    dbconn=dbconn, table_name=table_name, column=column_name, end_level=end_level
                )
            except Exception as e:
                logger.warning(
                    f"Unable to determine TimeLevels in create_semantic_model for column {column_name} and db type {dbconn.platform_type}. The error was{e}"
                )
                # skip the rest and go to the next column in the loop
                continue
            dimension_utils.create_time_dimension_for_column(
                atconn=atconn,
                project_dict=project_dict,
                cube_id=cube_id,
                dataset_id=dataset_id,
                column_name=column_name,
                time_levels=time_levels,
            )
        else:
            join_column = column_name
            if column_type != "date":
                platform = atconn._get_warehouse_platform(dataset["physical"]["connection"]["id"])
                if platform == "databrickssql":
                    platform = "databricks"
                platform_type = enums.PlatformType(platform)
                join_column = f"{column_name}_date"
                project_utils.add_calculated_column_to_project_dataset(
                    atconn=atconn,
                    data_set=dataset,
                    column_name=join_column,
                    expression=enums.TimeLevels.Day.get_sql_expression(column_name, platform_type),
                )
            if not date_key_feature:
                database, schema = db_utils.get_database_and_schema(dbconn=dbconn)
                warehouse_id = project_parser.get_project_warehouse(project_dict)
                try:
                    date_table_name = db_utils.get_atscale_tablename(
                        atconn=atconn,
                        warehouse_id=warehouse_id,
                        database=database,
                        schema=schema,
                        table_name="atscale_date_table",
                    )
                except atscale_errors.UserError:
                    dbconn._generate_date_table()
                    date_table_name = db_utils.get_atscale_tablename(
                        atconn=atconn,
                        warehouse_id=warehouse_id,
                        database=database,
                        schema=schema,
                        table_name="atscale_date_table",
                    )
                columns = atconn._get_table_columns(
                    warehouse_id=warehouse_id,
                    table_name=date_table_name,
                    database=database,
                    schema=schema,
                )
                date_dataset_dict, date_dataset_id = project_utils.create_dataset(
                    date_table_name, warehouse_id, columns, database, schema
                )
                project_utils.add_dataset(project_dict, date_dataset_dict)
                date_key_feature = dimension_utils.create_time_dimension_from_table(
                    project_dict, cube_id, date_dataset_id
                )
            if len(date_cols) > 1:
                roleplay_features = [f"{join_column} {{0}}"]
            else:
                roleplay_features = [""]
            dataset_name = project_parser.get_dataset(
                project_dict=project_dict, dataset_id=dataset_id
            )["name"]
            join_features = [date_key_feature]
            join_columns = [[join_column]]
            _create_dataset_relationship_from_dataset(
                project_dict=project_dict,
                cube_id=cube_id,
                dataset_name=dataset_name,
                join_features=join_features,
                join_columns=join_columns,
                roleplay_features=roleplay_features,
            )

    # The default data_model object when creating a project and writing a dataframe only has a data-set-ref. If we added dimensions above,
    # then we need to add some other dict elements to the data_model. I'm not actually sure how these are used. Just going with some defaults here
    data_model_dict = project_parser.get_cube(project_dict=project_dict, id=cube_id)
    data_model_dict.setdefault("properties", templates.create_data_model_properties_dict_default())
    data_model_dict.setdefault("actions", templates.create_data_model_actions_dict_default())
    data_model_dict.setdefault("calculated-members", {})
    data_model_dict.setdefault("aggregates", {})


def _get_fact_datasets(
    data_model_dict: dict,
    project_dict: Dict,
) -> List[dict]:
    """Gets all fact datasets currently utilized by the DataModel and returns as a list.

    Args:
        data_model (Dict): The dictionary representation of the data model to get datasets of interest from
        project_dict (Dict): the project_dict to extract dataset metadata from

    Returns:
        List[dict]: list of fact datasets
    """
    fact_refs = data_model_parser._get_dataset_refs(cube_dict=data_model_dict)
    id_set = {ref["id"] for ref in fact_refs}
    all_datasets = project_parser.get_datasets(project_dict=project_dict)
    fact_datasets = dictionary_parser.filter_list_of_dicts(
        dict_list=all_datasets, by={"id": id_set}
    )
    return fact_datasets


def _get_fact_dataset(
    data_model_dict: Dict,
    project_dict: Dict = None,
    dataset_name: str = None,
    dataset_id: str = None,
) -> bool:
    """Returns whether a given dataset name or id exists in the data model as a fact table, case-sensitive.

    Args:
        data_model (Dict): The dictionary representation of the DataModel object to search through
        project_dict (Dict): the project dict to look for the dataset in
        dataset_name (str): the name of the dataset to try and find

    Returns:
        bool: true if name found, else false.
    """
    fact_dset_list = _get_fact_datasets(data_model_dict, project_dict)
    return dictionary_parser._find_by_id_or_name(
        item_list=fact_dset_list, item_id=dataset_id, item_name=dataset_name
    )


def _get_dimension_datasets(
    data_model: "DataModel",
    project_dict: Dict,
) -> List[dict]:
    """Gets dimension datasets currently utilized by the DataModel and returns as a list.

    Args:
        data_model (DataModel): the data model to get datasets of interest from
        project_dict (Dict): the project_dict to extract dataset metadata from

    Returns:
        List[dict]: list of dimension datasets
    """
    hierarchies = data_model.get_hierarchies().keys()
    hier_map = _get_roleplay_hierarchy_mapping(data_model=data_model)
    hierarchies_mapped = [hier_map[x] for x in hierarchies]

    participating_datasets = {}
    for dimension in project_dict.get("dimensions", {}).get("dimension", []):
        for hierarchy in dimension.get("hierarchy", []):
            if hierarchy.get("name") in hierarchies_mapped:
                for participating_dataset in dimension.get("participating-datasets", []):
                    participating_datasets[participating_dataset] = True
                break
    all_datasets = []
    for dataset in project_parser.get_datasets(project_dict):
        if dataset.get("id") in participating_datasets:
            all_datasets.append(dataset)
    return all_datasets


def _get_roleplay_hierarchy_mapping(
    data_model,
) -> dict:
    """Gets a dictionary of dictionaries with the hierarchies names and metadata.
    Secondary attributes are treated as their own hierarchies.

    Args:
        data_model (DataModel): The DataModel object to search through

    Returns:
        dict: A dictionary of dictionaries where the hierarchy names are the keys in the outer dictionary
              while the inner keys are the following: 'dimension', 'description', 'caption', 'folder', 'type'(value is Time
              or Standard), 'secondary_attribute'.
    """
    project_dict = data_model.project._get_dict()
    data_model_name = data_model.name

    draft_features = dmh._get_draft_features(
        project_dict=project_dict, data_model_name=data_model_name
    )
    data_model_dict = project_parser.get_data_model(project_dict, data_model.cube_id)

    hierarchy_names_proj = []
    for dim in project_dict.get("dimensions", {}).get("dimension", []):
        hierarchy_list = dim.get("hierarchy", [])
        for hierarchy in hierarchy_list:
            hierarchy_names_proj.append(hierarchy.get("name"))

    hierarchy_names_cube = []
    for dim in data_model_dict.get("dimensions", {}).get("dimension", []):
        hierarchy_list = dim.get("hierarchy", [])
        for hierarchy in hierarchy_list:
            hierarchy_names_cube.append(hierarchy.get("name"))

    all_hierarchies = hierarchy_names_proj + hierarchy_names_cube

    roleplay_to_base = {}
    for key, val in draft_features.items():
        for hierarchy in range(len(val.get("hierarchy", []))):
            roleplay_hier = val.get("hierarchy")[hierarchy]
            base_hier = val.get("base_hierarchy", [])
            if not base_hier:
                base_hier = roleplay_hier
            else:
                base_hier = base_hier[hierarchy]

            if roleplay_hier in roleplay_to_base:
                if base_hier != roleplay_to_base[roleplay_hier]:
                    print(f"messed up on {roleplay_hier} and {base_hier}")
            else:
                roleplay_to_base[roleplay_hier] = base_hier

    for hierarchy in all_hierarchies:
        if hierarchy not in roleplay_to_base:
            roleplay_to_base[hierarchy] = hierarchy

    return roleplay_to_base


def _get_model_dict(
    data_model: "DataModel",
    project_dict: Dict,
) -> Tuple[dict, dict]:
    """Returns one or two dictionaries associated with this data_model

    Args:
        data_model (DataModel): the datamodel to get information from
        project_dict (Dict): the project_dict to extract the datamodel dict from

    Returns:
        Tuple[dict, dict]: returns the cube and perspective respectively, where perspective may be None
    """
    cube_dict = None
    perspective_dict = None

    if data_model.is_perspective():
        perspective_dict = project_parser.get_data_model(project_dict, data_model.id)
        cube_dict = project_parser.get_data_model(project_dict, data_model.cube_id)
    else:
        cube_dict = project_parser.get_data_model(project_dict, data_model.id)
    return cube_dict, perspective_dict


def _get_columns(
    project_dict: Dict,
    dataset_name: str,
) -> dict:
    """Gets all of the currently visible columns in a given dataset, case-sensitive.

    Args:
        project_dict (Dict): the project dict to look for the columns in
        dataset_name (str): the name of the dataset to get columns from, case-sensitive.

    Returns:
        dict: the columns in the given dataset
    """

    dataset_of_int = project_parser.get_dataset(
        project_dict=project_dict, dataset_name=dataset_name
    )

    physical_list = dataset_of_int.get("physical")
    if physical_list is None:
        return {}

    ret_dict = {}
    for col in physical_list.get("columns", []):
        ret_dict[col.get("name")] = {"data_type": col.get("type", {}).get("data-type", "")}
        if col.get("sqls", []):
            ret_dict[col.get("name")]["expression"] = col.get("sqls")[0].get("expression", "")
            ret_dict[col.get("name")]["column_type"] = "calculated"
        else:
            ret_dict[col.get("name")]["expression"] = ""
            if project_utils._check_if_qds(dataset_of_int):
                ret_dict[col.get("name")]["column_type"] = "query"
            else:
                ret_dict[col.get("name")]["column_type"] = "physical"
    for map_col in physical_list.get("map-column", []):
        for col in map_col.get("columns", {}).get("columns", []):
            ret_dict[col.get("name")] = {
                "data_type": col.get("type", {}).get("data-type", ""),
                "expression": "",
                "column_type": "mapped",
            }

    return ret_dict


def _column_exists(
    project_dict: Dict,
    dataset_name: str,
    column_name: str,
) -> bool:
    """Checks if the given column name exists in the dataset.

    Args:
        project_dict (Dict): the project dict to look for the column in
        dataset_name (str): the name of the dataset we pull the columns from, case-sensitive.
        column_name (str): the name of the column to check, case-sensitive

    Returns:
        bool: true if name found, else false.
    """
    all_column_names = _get_columns(project_dict, dataset_name).keys()
    match_found_list = [col_name for col_name in all_column_names if col_name == column_name]

    return len(match_found_list) > 0


def _perspective_check(
    data_model: "DataModel",
    error_msg: str = None,
):
    """Checks if the data_model provided is a perspective and throws an error if so.

    Args:
        data_model (DataModel): The DataModel to check
        error_msg (str, optional): Custom error string. Defaults to None to throw write error.
    """
    inspection = getfullargspec(_perspective_check)
    validate_by_type_hints(inspection=inspection, func_params=locals())

    if error_msg is None:
        error_msg = "Write operations are not supported for perspectives."

    if data_model.is_perspective():
        raise atscale_errors.UserError(error_msg)


def _add_related_hierarchies(
    data_model: "DataModel",
    hierarchy_list: List[str],
    hierarchies_to_check: List[str] = None,
) -> None:
    """Recursively adds hierarchies to hierarchy_list if they are related to a hierarchy in hierarchies_to_check.

    Args:
        data_model (DataModel): The DataModel to check
        hierarchy_list (List[str]): The list of hierarchies to add to.
        hierarchies_to_check (List[str], optional): The list of hierarchies to look  for relationships with. If None will use hierarchy_list.

    Returns:
        None
    """
    if hierarchies_to_check is None:
        hierarchies_to_check = hierarchy_list
    project_dict = data_model.project._get_dict()
    cube_dict = _get_model_dict(data_model, project_dict=project_dict)[0]
    hierarchy_relationship_dict = {}
    # build a dictionary of the hierarchy names and their levels and relationships
    for dimension in project_dict.get("dimensions", {}).get("dimension", []) + cube_dict.get(
        "dimensions", {}
    ).get("dimension", []):
        for hierarchy in dimension.get("hierarchy", []):
            hierarchy_name = hierarchy.get("name")
            hierarchy_relationship_dict[hierarchy_name] = {
                "primary_attribute_keys": [],
                "relationship_keys": [],
            }
            for level in hierarchy.get("level", []):
                hierarchy_relationship_dict[hierarchy_name]["primary_attribute_keys"].append(
                    level.get("primary-attribute")
                )
                for keyed_attribute_ref in level.get("keyed-attribute-ref", []):
                    hierarchy_relationship_dict[hierarchy_name]["relationship_keys"].append(
                        keyed_attribute_ref.get("attribute-id")
                    )
    # call the recursive helper to use the dict to add related hierarchies so we don't have to build it each time
    _add_related_hierarchies_helper(
        hierarchy_list, hierarchies_to_check, hierarchy_relationship_dict
    )


def _add_related_hierarchies_helper(
    hierarchy_list: List[str],
    hierarchies_to_check: List[str],
    hierarchy_relationship_dict: Dict,
) -> None:
    """Recursively adds hierarchies to hierarchy_list if they are related to a hierarchy in hierarchies_to_check.

    Args:
        hierarchy_list (List[str]): The list of hierarchies to add to.
        hierarchies_to_check (List[str]): The list of hierarchies to look  for relationships with.
        hierarchy_relationship_dict (Dict): A dictionary with hierarchy names as keys that contains their attributes and relationships.

    Returns:
        None
    """
    new_hierarchies_to_check = []
    for hierarchy in hierarchies_to_check:
        # the relationship info is only stored in one hierarchy so we need to check both ways
        for key in hierarchy_relationship_dict[hierarchy]["relationship_keys"]:
            for hier in hierarchy_relationship_dict.keys():
                if (
                    hier not in hierarchy_list
                    and key in hierarchy_relationship_dict[hier]["primary_attribute_keys"]
                ):
                    hierarchy_list.append(hier)
                    new_hierarchies_to_check.append(hier)
        for key in hierarchy_relationship_dict[hierarchy]["primary_attribute_keys"]:
            for hier in hierarchy_relationship_dict.keys():
                if (
                    hier not in hierarchy_list
                    and key in hierarchy_relationship_dict[hier]["relationship_keys"]
                ):
                    hierarchy_list.append(hier)
                    new_hierarchies_to_check.append(hier)
    # if we added new hierarchies we recursively call the function to see if there are other hierarchies we need to bring in connected to those new ones
    if len(new_hierarchies_to_check) > 0:
        _add_related_hierarchies_helper(
            hierarchy_list, new_hierarchies_to_check, hierarchy_relationship_dict
        )


def _validate_mdx_syntax(
    atconn: _Connection,
    expression: str,
    raises=True,
) -> str:
    """Passes an MDX expression to the engine for validation

    Args:
        atconn (_Connection): the connection to use for validation
        expression (str): the expression to validate
        raises (bool, optional): Determines behavior if error is found. If
            True it will raise error, else it will return erorr message. Defaults to True.

    Returns:
        str: Either the error or an empty string if no error found
    """
    url = endpoints._endpoint_mdx_syntax_validation(atconn)
    data = {"formula": expression}
    response = atconn._submit_request(
        request_type=enums.RequestType.POST, url=url, data=json.dumps(data)
    )
    resp = json.loads(response.content)["response"]
    if not resp["isSuccess"]:
        if raises:
            raise atscale_errors.UserError(resp["errorMsg"])
        else:
            return resp["errorMsg"]
    return ""


def _check_duplicate_features_get_data(feature_list: List[str]) -> None:
    """Logs appropriate info if duplicate features encountered in get_data

    Args:
        feature_list (List[str]): The list of features to check

    Returns:
        None
    """

    dupe_count = len(feature_list) - len(set(feature_list))

    if dupe_count > 0:
        input_feature_list_len = len(feature_list)
        logger.warning(
            f"The feature_list passed contains {dupe_count} duplicates; the DataFrame returned "
            f"by get_data will contain {input_feature_list_len - dupe_count} features instead of {input_feature_list_len}."
        )
