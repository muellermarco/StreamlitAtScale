from datetime import datetime
from typing import Dict, List

from atscale.parsers import dictionary_parser, data_model_parser

# the built in datetime.fromisoformat seems to fail so manually writing an iso format constant
isoformat = "%Y-%m-%dT%H:%M:%S.%f%z"


def parse_engineid_for_project(
    project_dict: dict,
) -> str:
    # make sure annotations exist
    tmp = project_dict.get("annotations", {})
    tmp = tmp.get("annotation", [])
    if len(tmp) < 1:
        return None

    # if both annotations and annotation exists we can index them to get engineId
    for annotation in project_dict["annotations"]["annotation"]:
        # We're under the impression that a project only ever has one engineID
        # and the published projects refer to that. Therefore, we return the
        # first one we find.
        if annotation.get("name") == "engineId":
            return annotation.get("value")
    return None


# ######################################################################################################################
# Parsing for published projects
# ######################################################################################################################


def parse_published_project_by_id(
    published_project_list: list,
    published_project_id: str,
) -> dict:
    return dictionary_parser.parse_dict_list(published_project_list, "id", published_project_id)


def parse_published_project_by_name(
    published_project_list: list,
    published_project_name: str,
) -> dict:
    return dictionary_parser.parse_dict_list(published_project_list, "name", published_project_name)


def parse_published_projects_for_project(
    project_dict: dict,
    published_project_list: list,
    include_soft_publish: bool = False,
) -> list:
    project_engine_id = parse_engineid_for_project(project_dict)
    filtered_published_projects = []
    for published_project in published_project_list:
        if published_project["linkedProjectId"] == project_engine_id:
            if not include_soft_publish and published_project["publishType"] == "soft_publish":
                continue
            filtered_published_projects.append(published_project)
    return filtered_published_projects


def parse_most_recent_published_project(
    published_project_list: list,
) -> dict:
    if published_project_list is None or len(published_project_list) < 1:
        return None
    # start with the first published project
    published_project = published_project_list[0]
    num_pubs = len(published_project_list)
    if num_pubs < 2:
        return published_project
    publish_date = datetime.strptime(published_project["publishedAt"], isoformat)
    for i in range(1, num_pubs, 1):
        tmp_project = published_project_list[i]
        tmp_date = datetime.strptime(tmp_project.get("publishedAt"), isoformat)
        if tmp_date is not None and tmp_date > publish_date:
            publish_date = tmp_date
            published_project = tmp_project
    return published_project


def parse_most_recent_published_project_for_project(
    project_dict: dict,
    published_project_list: list,
) -> dict:
    # mashup of the two functions above this
    filtered_published_project_list = parse_published_projects_for_project(
        project_dict, published_project_list, include_soft_publish=False
    )
    return parse_most_recent_published_project(filtered_published_project_list)


def verify_published_project_dict_against_project_dict(
    project_dict: dict,
    published_project_dict: dict,
) -> bool:
    engine_id = parse_engineid_for_project(project_dict)
    if published_project_dict.get("linkedProjectId") == engine_id:
        return True
    else:
        return False


##############
# Data Model Stuff#
##############


def get_cubes(
    project_dict: dict,
) -> list:
    """Grabs all cubes from a project
    Args:
        project (dict): a complete draft project specification
    Returns:
        list:  List of all cubes(dict object) in the project, may be empty if none are found.
    """
    cubes = project_dict.setdefault("cubes", {})
    cube = cubes.setdefault("cube", [])
    return cube


def get_cube(
    project_dict: dict,
    id: str,
) -> dict:
    """Searches the project dict to retrieve the cube associated with the provided cube id. When working with a
    perspective, be sure to use the cube_id rather than the data model id since the data_model.id will return the id of
    the perspective while data_model.cube_id will return the id of the associated cube that the perspective is
    restrictively viewing.

    Args:
        project (dict): draft project dict
        id (str): id for the cube to retrieve

    Returns:
        dict: dict for the cube for the provided id or None if one isn't found.
    """
    cubes = get_cubes(project_dict)
    for cube in cubes:
        if cube.get("id") == id:
            return cube
    return {}


def get_perspectives(
    project_dict: dict,
) -> list:
    """Gets all perspectives from a project as a list of dictionaries.
    Args:
        project (dict): a complete draft project specification.
    Returns:
        list: list of perspectives, may be empty if none are found.
    """
    perspectives = project_dict.setdefault("perspectives", {})
    perspective = perspectives.setdefault("perspective", [])
    return perspective


def get_perspective(
    project_dict: dict,
    id: str,
) -> dict:
    """Searches the project dict to retrieve the perspective associated with the provided id.

    Args:
        project (dict): draft project dict
        id (str): id for the perspective to retrieve

    Returns:
        dict: dict for the perspective for the provided id or None if one isn't found.
    """
    perspectives = get_perspectives(project_dict)
    for perspective in perspectives:
        if perspective.get("id") == id:
            return perspective
    return {}


def get_data_models(
    project_dict: dict,
) -> list:
    """Return all data models (cubes or perspectives) associated with a project.

    Args:
        project (dict): the dict representation of a project.

    Returns:
        list: all data models associated with a project, may be empty if none are found.
    """
    return get_cubes(project_dict) + get_perspectives(project_dict)


def get_data_model(
    project_dict: dict,
    id: str,
) -> dict:
    data_models = get_data_models(project_dict)
    for data_model in data_models:
        if data_model.get("id") == id:
            return data_model
    return {}


# ######################################################################################################################
# Parsing out datasets
# ######################################################################################################################


def get_dataset(
    project_dict: dict,
    dataset_id: str = None,
    dataset_name: str = None,
) -> dict:
    dset_list = get_datasets(project_dict=project_dict)
    return dictionary_parser._find_by_id_or_name(
        item_list=dset_list, item_id=dataset_id, item_name=dataset_name
    )


def get_datasets(
    project_dict: dict,
) -> list:
    """Grabs the datasets out of a project dict.

    Args:
        project_dict (dict): a dict describing a project

    Returns:
        list: list of dictionaries, each describing a dataset
    """
    if project_dict is None:
        return []
    ds_dict = project_dict.setdefault("datasets", {})
    return ds_dict.setdefault("data-set", [])


def find_dataset_with_table(
    datasets: list,
    table_name: str,
    database: str = None,
    schema: str = None,
) -> str:
    """Looks through the provided datasets for one that contains the given table_name

    Args:
        datasets (list[dict]): The datasets to look for the table in
        database (str): The database that the table exists in
        schema (str): The schema that the table exists in
        table_name (str): The name of the table to look for

    Returns:
        str: the dataset id for the first dataset found in the datasets list that contains the provided table.
        None if none are found.
    """
    matching_dsets = []

    for ds in datasets:
        # make list of readable datasets
        phys = ds.get("physical")
        if phys:
            ds_rep = {"id": ds.get("id"), "name": ds.get("name")}
            tables = phys.get("tables")
            if tables:
                table = tables[0]
                if table.get("name") == table_name:
                    for key, val in table.items():
                        ds_rep[key] = val
                    if schema is None or ds_rep["schema"] == schema:
                        if database is None or ds_rep["database"] == database:
                            matching_dsets.append(ds_rep)

    if len(matching_dsets) == 1:
        return matching_dsets[0].get("id")
    elif len(matching_dsets) > 1:
        raise Exception(f"Could not identify targeted table out of tables: {matching_dsets}")
    else:
        return None


# ######################################################################################################################
# Warehouse and connections
# ######################################################################################################################


def get_project_warehouse(
    project_dict: dict,
) -> str:
    datasets = get_datasets(project_dict)
    warehouse_id = None
    if len(datasets) > 0:
        physicalList = datasets[0].get("physical")
        if physicalList:
            warehouse_id = physicalList.get("connection")["id"]
    return warehouse_id


def get_connection_by_id(
    connections: list,
    connection_id: str,
):
    for con in connections:
        if con.get("connectionId") == connection_id:
            return con
    return {}


def get_connection_list_for_project_datasets(
    project_datasets: list,
    connections: list,
) -> list:
    """Finds the connection associated with each project_data set and constructs a list of them in the same order
    such that project_dataset[i] references connections[i]. Note, connections may repeat in the returned list as
    more than one project dataset may refer to the same connection.

    Args:
        project_datasets (list): project data sets
        connections (list): connection group connections from the org

    Returns:
        list: a list of connections corresponding to each data set in project_datasets
    """
    project_connections = []
    for project_dataset in project_datasets:
        # If these indexes don't exist somethign went wrong, will trigger an exception
        conn_id = project_dataset["physical"]["connection"]["id"]
        project_connections.append(get_connection_by_id(connections, conn_id))
    return project_connections


# ######################################################################################################################
# Miscellaneous or feature parsing
# ######################################################################################################################


def _get_calculated_members(
    project_dict: dict,
) -> List[Dict]:
    """Grabs the calculated members out of a project dict.

    Args:
        project_dict (dict): a dict describing a calculated members

    Returns:
        list: list of dictionaries describing the calculated members
    """
    if project_dict is None:
        return []
    mem_dict = project_dict.setdefault("calculated-members", {})
    return mem_dict.setdefault("calculated-member", [])


def _get_query_names_from_value_columns(
    project_dict: dict,
    cube_id: str,
    value_columns: List[str],
):
    """Takes in columns and maps to features that have those columns as their value column
    query column
    """
    project_datasets = get_datasets(project_dict)
    # get project and cube attributes. degenerate dimensions are in the cube
    project_attributes = project_dict.get("attributes", {}).get("keyed-attribute", [])

    cube = get_cube(project_dict, cube_id)
    cube_datasets = data_model_parser._get_dataset_refs(cube)
    cube_attributes = cube.get("attributes", {}).get("keyed-attribute", [])

    all_datasets = project_datasets + cube_datasets
    value_columns_dict = {x: "" for x in value_columns}
    val_remaining = len(value_columns)

    for dataset in all_datasets:
        for key_ref in dataset.get("logical", {}).get("attribute-ref", []):
            found_col = key_ref.get("column")
            if len(found_col) == 1 and found_col[0] in value_columns:
                if value_columns_dict[found_col[0]] == "":
                    val_remaining -= 1
                    value_columns_dict[found_col[0]] = key_ref.get("id")
                    if val_remaining == 0:
                        break
        if val_remaining == 0:
            break

    # now map back to the return values
    ret_dict = {}
    for key, value in value_columns_dict.items():
        attribute = dictionary_parser.parse_dict_list(project_attributes, "id", value)
        if attribute is not None:
            ret_dict[key] = attribute["name"]
        else:
            attribute = dictionary_parser.parse_dict_list(cube_attributes, "id", value)
            ret_dict[key] = attribute["name"]

    return ret_dict


def _get_multi_key_query_names_from_features(
    project_dict: dict,
    cube_id: str,
    feature_list: List[str],
) -> Dict[str, List[str]]:
    """Maps the provided features to the query names of the associated multi-keys

    Args:
        project_dict (Dict): the dict representation of the project json.
         (str): The cube id of the AtScale DataModel of interest.
        feature_list (List[str]): The list of features to check the keys of.

    Returns:
        Dict[str,List[str]]: Dict of {provided feature_name}:[{missing feature_name}] pairs
    """
    # get the dict of features: {'key_cols]}
    feature_key_list: dict = _get_feature_keys(
        project_dict=project_dict, cube_id=cube_id, join_features=feature_list
    )
    cols_to_map_list_of_list = [
        feature_key_list[x]["key_cols"] for x in feature_key_list.keys()
    ]  # list of key_cols from all features
    cols_to_map = list(set([item for sublist in cols_to_map_list_of_list for item in sublist]))

    query_names_to_map = _get_query_names_from_value_columns(
        project_dict=project_dict, cube_id=cube_id, value_columns=cols_to_map
    )

    # the return value should be feature: [list of query names making up key]
    ret_dict = {}
    for feature in feature_key_list.keys():
        ret_dict[feature] = [query_names_to_map[x] for x in feature_key_list[feature]["key_cols"]]

    return ret_dict


def _get_feature_keys(
    project_dict: dict,
    cube_id: str,
    join_features: List[str],
):
    key_dict = {}
    project_datasets = get_datasets(project_dict)
    # get project and cube attributes. degenerate dimensions are in the cube
    project_attributes = project_dict.get("attributes", {}).get("keyed-attribute", [])
    cube = get_cube(project_dict, cube_id)
    cube_datasets = data_model_parser._get_dataset_refs(cube)
    cube_attributes = cube.get("attributes", {}).get("keyed-attribute", [])
    for feature in join_features:
        found_dataset = False
        key_cols = []
        attributes = [x for x in project_attributes if x.get("name") == feature]
        if len(attributes) > 0:
            attribute = attributes[0]
            datasets = project_datasets
        else:
            attribute = [x for x in cube_attributes if x.get("name") == feature][0]
            datasets = cube_datasets
        attribute_id = attribute.get("id")
        attribute_key_ref = attribute.get("key-ref")
        for dataset in datasets:
            for attribute_ref in dataset.get("logical", {}).get("attribute-ref", []):
                # if we match the attribute-ref id we know we have the right dataset and can grab the value column
                if attribute_ref.get("id") == attribute_id:
                    for column in attribute_ref.get("column", []):
                        value_col = column
                    found_dataset = True
                    break
            if found_dataset:
                # if we are in the right dataset we now look through the key-refs to find the key columns
                for key_ref in dataset.get("logical", {}).get("key-ref", []):
                    if key_ref.get("id") == attribute_key_ref:
                        for column in key_ref.get("column", []):
                            key_cols.append(column)
                        break
                physical = dataset.get("physical")
                # if we were dealing with a degenerate dimension we are actually in a dataset-ref which doesn't have the physical info
                # but we can grab the actual dataset using the id
                if not physical:
                    physical = get_dataset(
                        project_dict=project_dict, dataset_id=dataset.get("id")
                    ).get("physical")
                tables = physical.get("tables")
                queries = physical.get("queries")
                # fill in the table info if it is a physical table
                if tables:
                    for table in tables:
                        database = table.get("database")
                        schema = table.get("schema")
                        table_name = table.get("name")
                        sql = None
                # fill in the query instead if it is a qds
                elif queries:
                    for query in queries:
                        for sqls in query.get("sqls", []):
                            database = None
                            schema = None
                            table_name = None
                            sql = sqls.get("expression")
                        break
                # we found the dataset so stop looking
                break
        key_dict[feature] = {
            "key_cols": list(key_cols),
            "value_col": value_col,
            "database": database,
            "schema": schema,
            "table_name": table_name,
            "query": sql,
        }
    return key_dict
