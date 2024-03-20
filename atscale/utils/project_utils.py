import json
import uuid
import urllib.parse
from typing import Dict, List, Tuple

from atscale.connection.connection import _Connection
from atscale.base import endpoints, templates, enums
from atscale.parsers import data_model_parser, project_parser


def create_project(
    client: "Client",
    project_dict: Dict,
):
    """Creates a new project using the project_dict provided

    Args:
        client (Client): the client to add the project with
        project_dict (Dict): the project metadata to build the project with

    Returns:
        Project: An instance of the Project object representing the new project
    """
    # creates a project with the given project dict
    u = endpoints._endpoint_design_create_project(client._atconn)
    response = client._atconn._submit_request(
        request_type=enums.RequestType.POST, url=u, data=json.dumps(project_dict)
    )
    project_dict = json.loads(response.content)["response"]
    # now we'll use the values to construct a python Project class
    project_id = project_dict.get("id")

    from atscale.project.project import Project

    return Project(client=client, draft_project_id=project_id)


def clone_project(
    atconn: _Connection,
    original_project_id: str,
    new_project_name: str,
) -> str:
    """makes a clone of the orginal projects dictionary with a new project name

    Args:
        original_project (Project): the orginal project to make a clone of
        new_project_name (str): the name of the clone

    Returns:
        str: the id of the clone
    """
    url_name = urllib.parse.quote(new_project_name, safe="")
    url = endpoints._endpoint_design_clone_project(
        atconn, project_id=original_project_id, new_project_name=url_name
    )
    response = atconn._submit_request(request_type=enums.RequestType.POST, url=f"{url}", data={})
    new_project_id = json.loads(response.content)["response"]["copiedProjectData"]["id"]
    return new_project_id


def create_dataset_columns_from_atscale_table_columns(
    table_columns: List,
) -> List:
    """Takes information about table columns as formatted by AtScale and formats them for reference in a dataset specification.

    Args:
        table_columns (list): a list of table columns formatted as referenced by AtScale

    Returns:
        List: a list of python dictionaries that represent table columns formatted for use in an AtScale data set.
    """
    columns = []
    for name, d_type in table_columns:
        column = templates.create_column_dict(name=name, data_type=d_type)
        columns.append(column)
    return columns


def create_dataset(
    project_dict: dict,
    table_name: str,
    warehouse_id: str,
    table_columns: List[Tuple[str, str]],
    database: str = None,
    schema: str = None,
    dataset_name: str = None,
    allow_aggregates: bool = True,
    incremental_indicator: str = None,
    grace_period: int = 0,
    safe_to_join_to_incremental: bool = False,
) -> Tuple[Dict, str]:
    """Creates a dataset dictionary from the provided table

    Args:
        project_dict(dict): The dictionary of the project to add the dataset to.
        table_name (str): The name of the new dataset
        warehouse_id (str): the warehouse to look for the table in
        table_columns (list): the AtScale table columns to turn into dataset columns
        database (str, optional): the database to find the table in. Defaults to None.
        schema (str, optional): the schema to find the table in. Defaults to None.
        dataset_name (str, optional): the name of the dataset to be created. Defaults to None to use table_name.
        allow_aggregates (bool, optional): Whether to allow aggregates to be built off of the dataset. Defaults to True.
        incremental_indicator (string, optional): The indicator column for incremental builds. Defaults to None to not enable incremental builds.
        grace_period (int, optional): The grace period for incremental builds. Defaults to 0.
        safe_to_join_to_incremental (bool, optional): Whether it is safe to join from this dataset to one with incremental builds enabled. Defaults to False.

    Returns:
        Tuple(Dict, str): The dataset_dict and dataset_id of the created dataset
    """
    if not dataset_name:
        dataset_name = table_name
    columns = create_dataset_columns_from_atscale_table_columns(table_columns)
    dataset_id = str(uuid.uuid4())
    dataset = templates.create_dataset_dict(
        dataset_id=dataset_id,
        dataset_name=dataset_name,
        table_name=table_name,
        warehouse_id=warehouse_id,
        columns=columns,
        schema=schema,
        database=database,
        allow_aggregates=allow_aggregates,
        incremental_indicator=incremental_indicator,
        grace_period=grace_period,
        safe_to_join_to_incremental=safe_to_join_to_incremental,
    )
    project_dict.get("datasets", {}).setdefault("data-set", []).append(dataset)
    return dataset, dataset_id


def _create_query_dataset(
    project_dict: dict,
    name: str,
    query: str,
    columns: List[Tuple[str, str]],
    warehouse_id: str,
    allow_aggregates: bool,
    incremental_indicator: str = None,
    grace_period: int = 0,
    safe_to_join_to_incremental: bool = False,
) -> Dict:
    """Takes a name, sql expression, columns as returned by connection._get_query_columns(), and the
    warehouse_id of the connected warehouse to query against.

    Args:
        project_dict(dict): The dictionary of the project to add the dataset to.
        name(str): The display and query name of the dataset
        query(str): A valid SQL expression with which to directly query the warehouse of the given warehouse_id.
        columns (List): the columns from the resulting query.
        warehouse_id(str): The warehouse id of the warehouse this qds and its project are pointing at.
        allow_aggregates(bool): Whether or not aggregates should be built off of this QDS.
        incremental_indicator (string, optional): The indicator column for incremental builds. Defaults to None to not enable incremental builds.
        grace_period (int, optional): The grace period for incremental builds. Defaults to 0.
        safe_to_join_to_incremental (bool, optional): Whether it is safe to join from this dataset to one with incremental builds enabled. Defaults to False.

    Returns:
        Dict: The dict to append to project_dict['datasets']['dataset']
    """
    column_dict_list = create_dataset_columns_from_atscale_table_columns(table_columns=columns)
    dataset_id = str(uuid.uuid4())
    dataset = templates.create_query_dataset_dict(
        dataset_id=dataset_id,
        dataset_name=name,
        warehouse_id=warehouse_id,
        columns=column_dict_list,
        allow_aggregates=allow_aggregates,
        query=query,
        incremental_indicator=incremental_indicator,
        grace_period=grace_period,
        safe_to_join_to_incremental=safe_to_join_to_incremental,
    )
    project_dict["datasets"].setdefault("data-set", []).append(dataset)
    return dataset, dataset_id


def _update_dataset(
    project_dict: Dict,
    dataset_name: str,
    cube_id: str,
    create_hinted_aggregate: bool = None,
    allow_aggregates: bool = None,
    incremental_indicator: str = None,
    grace_period: int = None,
    safe_to_join_to_incremental: bool = None,
    create_fact_from_dimension: bool = False,
) -> Dict:
    """Takes a dataset and gives a new setting for allowing aggregates and hinted_aggs

    Args:
        project_dict (Dict): The project we're editing
        dataset_name (str): The name of the dataset we are updating.
        cube_id (str): The id of the cube we are updating
        create_hinted_aggregate (bool, optional): Whether to create a hinted agg on publish. Defaults to None for no update.
        allow_aggregates(bool, optional): Whether to allow aggregates to be built off this dataset. Defaults to None for no update.
        incremental_indicator (string, optional): The indicator column for incremental builds. Defaults to None for no update.
        grace_period (int, optional): The grace period for incremental builds. Defaults to None for no update.
        create_fact_from_dimension (bool, optional): Whether to create a fact dataset if the current dataset is only used with dimensions. Defaults to False.
        safe_to_join_to_incremental (bool, optional): Whether it is safe to join from this dataset to one with incremental builds enabled. Defaults to None for no update.

    Returns:
        Dict: The edited project_dict
    """

    dset = project_parser.get_dataset(project_dict=project_dict, dataset_name=dataset_name)
    dataset_properties = dset.get("properties", {})

    if allow_aggregates is not None:
        dataset_properties["allow-aggregates"] = allow_aggregates

    if safe_to_join_to_incremental is not None:
        dset["physical"]["immutable"] = safe_to_join_to_incremental

    if incremental_indicator is not None:
        if incremental_indicator == "":
            ref_id = (
                dset.get("logical", {})
                .get("incremental-indicator", {})
                .get("key-ref", {})
                .get("id")
            )
            del dset["logical"]["incremental-indicator"]
            if ref_id:
                dset["logical"]["key-ref"] = [
                    x for x in dset.get("logical", {}).get("key-ref", []) if x.get("id") != ref_id
                ]
                project_dict.setdefault("attributes", {})["attribute-key"] = [
                    x
                    for x in project_dict.get("attributes", {}).get("attribute-key", [])
                    if x.get("id") != ref_id
                ]
        else:
            ref_id = (
                dset.get("logical", {})
                .get("incremental-indicator", {})
                .get("key-ref", {})
                .get("id")
            )
            if ref_id:
                ref = [
                    x for x in dset.get("logical", {}).get("key-ref", []) if x.get("id") == ref_id
                ]
                ref[0]["column"] = [incremental_indicator]
            else:
                ref_id = str(uuid.uuid4())
                dset.setdefault("logical", {})["incremental-indicator"] = {
                    "grace-period": grace_period if grace_period is not None else 0,
                    "key-ref": {"id": ref_id},
                }
                dset["logical"].setdefault("key-ref", []).append(
                    {
                        "column": [incremental_indicator],
                        "complete": "true",
                        "id": ref_id,
                        "unique": False,
                    }
                )
                attribute_key = {
                    "id": ref_id,
                    "properties": {"columns": 1, "visible": True},
                }
                project_dict.setdefault("attributes", {}).setdefault("attribute-key", []).append(
                    attribute_key
                )
    elif grace_period is not None:
        if dset.get("logical", {}).get("incremental-indicator"):
            dset["logical"]["incremental-indicator"]["grace-period"] = grace_period

    dataset_id = dset["id"]
    cube_dict = project_parser.get_cube(project_dict, cube_id)

    dataset_refs = data_model_parser._get_dataset_refs(cube_dict=cube_dict)
    dataset_ref = [dataset_ref for dataset_ref in dataset_refs if dataset_ref["id"] == dataset_id]

    if len(dataset_ref) > 0:
        dataset_properties = dataset_ref[0].setdefault("properties", {})
        if create_hinted_aggregate is not None:
            dataset_properties["create-hinted-aggregate"] = create_hinted_aggregate
        if allow_aggregates is not None:
            dataset_properties["allow-aggregates"] = allow_aggregates
    else:
        if create_fact_from_dimension:
            if allow_aggregates is None:
                # inherit from the project level
                allow_aggregates = dataset_properties["allow-aggregates"]

            if create_hinted_aggregate is None:
                create_hinted_aggregate = False

            data_set_ref = templates.create_dataset_ref_dict(
                dataset_id,
                [],
                [],
                create_hinted_aggregate=create_hinted_aggregate,
                allow_aggregates=allow_aggregates,
            )
            cube_dict.setdefault("data-sets", {}).setdefault("data-set-ref", []).append(
                data_set_ref
            )


def add_calculated_column_to_project_dataset(
    atconn: _Connection,
    data_set: Dict,
    column_name: str,
    expression: str,
    column_id: str = None,
):
    """Mutates the provided data_set by adding a calculated column based on the provided column_name and expression.

    Args:
        atconn (_Connection): an AtScale connection
        data_set (Dict): the data set to be mutated
        column_name (str): the name of the new calculated column
        expression (str): the sql expression that will create the values for the calculated column
        column_id (str): the id for the column. Defaults to None to generate one.
    """
    conn = data_set["physical"]["connection"]["id"]
    table = data_set["physical"]["tables"][0]
    table_name = table["name"]
    database = table.get("database", None)
    schema = table.get("schema", None)

    # submit a request to calculate the data type of the expression
    url = endpoints._endpoint_expression_eval_data_types(
        atconn,
        connection_id=conn,
        table_name=table_name,
    )
    data = {"dbschema": schema, "expression": expression, "database": database}
    response = atconn._submit_request(
        request_type=enums.RequestType.POST,
        url=url,
        data=data,
        content_type="x-www-form-urlencoded",
    )

    resp = json.loads(response.text)
    data_type = resp["response"]["data-type"]

    new_column = templates.create_column_dict(
        name=column_name, expression=expression, data_type=data_type, column_id=column_id
    )

    data_set["physical"].setdefault("columns", []).append(new_column)


def _check_if_qds(
    data_set: Dict,
) -> bool:
    """Checks if a data set is a qds.

    Args:
        data_set (Dict): the data set to be checked

    Returns:
        bool: True if this is a qds
    """
    return len(data_set.get("physical", {}).get("queries", [])) > 0
