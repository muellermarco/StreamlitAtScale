import logging
import uuid
from typing import List, Union
from atscale.base.enums import (
    Aggs,
    MappedColumnKeyTerminator,
    MappedColumnFieldTerminator,
    MappedColumnDataTypes,
    TimeSteps,
)

logger = logging.getLogger(__name__)


def create_data_model_actions_dict_default():
    # dict key pointing at this dict is 'actions'
    return {"properties": {"include-default-drill-through": True}}


def create_data_model_properties_dict_default():
    # dict key pointing at this dict is 'properties'
    return {"visible": False}


def create_dataset_ref_dict(
    dataset_id,
    key_refs=None,
    attribute_refs=None,
    allow_aggregates=True,
    create_hinted_aggregate=False,
):
    dataset = {
        "id": dataset_id,
        "properties": {
            "allow-aggregates": allow_aggregates,
            "create-hinted-aggregate": False,
            "aggregate-destinations": None,
        },
        "logical": {},
    }
    if key_refs or attribute_refs:
        dataset["logical"] = {"key-ref": key_refs, "attribute-ref": attribute_refs}
    if create_hinted_aggregate:
        dataset["properties"]["create-hinted-aggregate"] = True
    return dataset


def create_attribute_dict(
    attribute_id: str,
):
    # not sure what this is for - seems specific to some use cases, but not for adding measures based on existing numeric columns, so adding a version for that
    return {"attribute-id": attribute_id, "properties": {"multiplicity": {}}}


def create_attribute_ref_dict(
    columns: list,
    attribute_id: str,
    complete: Union[bool, str] = True,
):
    complete = str(complete).lower() if isinstance(complete, bool) else complete

    return {"id": attribute_id, "complete": complete, "column": columns}


def create_attribute_key_dict(
    key_id: str,
    columns: int,
    visible: bool,
):
    return {"id": key_id, "properties": {"columns": columns, "visible": visible}}


def create_attribute_key_ref_dict(
    key_id: str,
    columns: list,
    complete: bool,
    unique: bool,
):
    key_ref = create_attribute_ref_dict(attribute_id=key_id, columns=columns, complete=complete)
    key_ref["unique"] = unique
    key_ref["complete"] = str(complete).lower()
    return key_ref


def create_keyed_attribute_dict(
    attribute_id: str,
    key_ref: str,
    name: str,
    visible,
    ordering: str = None,
    caption=None,
    description=None,
    folder=None,
):
    if caption is None:
        caption = name
    keyed_attr = {
        "id": attribute_id,
        "key-ref": key_ref,
        "name": name,
        "properties": {"caption": caption, "type": {"enum": {}}, "visible": visible},
    }
    if ordering is not None:
        keyed_attr["properties"]["ordering"] = {"sort-key": {"order": ordering, "value": {}}}
    if description is not None:
        keyed_attr["properties"]["description"] = description
    if folder is not None:
        keyed_attr["properties"]["folder"] = folder
    return keyed_attr


def create_column_dict(
    name: str,
    data_type: str,
    column_id: str = None,
    expression: str = None,
):
    if column_id is None:
        column_id = str(uuid.uuid4())
    column_json = {"id": column_id, "name": name, "type": {"data-type": data_type}}
    if expression is not None:
        column_json["sqls"] = [{"expression": expression}]
    return column_json


def create_map_column_dict(
    columns: List[dict],
    field_terminator: MappedColumnFieldTerminator,
    key_terminator: MappedColumnKeyTerminator,
    first_char_delim: bool,
    map_key_type: MappedColumnDataTypes,
    map_value_type: MappedColumnDataTypes,
    column_name: str,
):
    return {
        "columns": {"columns": columns},
        "delimited": {
            "field-terminator": field_terminator.value,
            "key-terminator": key_terminator.value,
            "prefixed": first_char_delim,
        },
        "map-key": {"type": map_key_type.value},
        "map-value": {"type": map_value_type.value},
        "name": column_name,
    }


def create_calculated_member_dict(
    id: str,
    member_name: str,
    expression: str,
    caption: str,
    visible: bool,
    description: str = None,
    formatting: dict = None,
    folder: str = None,
):
    new_calculated_measure = {
        "id": id,
        "name": member_name,
        "expression": expression,
        "properties": {"caption": caption, "visible": visible},
    }

    if description is not None:
        new_calculated_measure["properties"]["description"] = description
    if formatting is not None:
        new_calculated_measure["properties"]["formatting"] = formatting
    if folder is not None:
        new_calculated_measure["properties"]["folder"] = folder

    return new_calculated_measure


def create_calculated_member_ref_dict(
    id: str,
):
    return {
        "id": id,
        "XMLName": {
            "Local": "calculated-member-ref",
            "Space": "http://www.atscale.com/xsd/project_2_0",
        },
    }


def create_hierarchy_level_dict(
    visible: bool,
    level_id: str,
    keyed_attribute_id: str,
    level_type: TimeSteps = None,
):
    properties = {"unique-in-parent": False, "visible": visible}
    if level_type:
        properties["level-type"] = level_type.name
    else:
        properties["level-type"] = "Regular"
    return {"id": level_id, "primary-attribute": keyed_attribute_id, "properties": properties}


def create_hierarchy_dict(
    hierarchy_id: str,
    hierarchy_name: str,
    caption: str,
    folder: str,
    description: str,
    visible: bool,
    levels: list,
):
    if caption is None:
        caption = hierarchy_name
    if folder is None:
        folder = ""
    if description is None:
        description = ""
    return {
        "id": hierarchy_id,
        "name": hierarchy_name,
        "properties": {
            "caption": caption,
            "visible": visible,  # should only this one use the provided visible or should all of them?
            # I've seen value of 'always' and 'yes' in other projects and not sure implications of one vs the other.
            "filter-empty": "Yes",
            "default-member": {"all-member": {}},
            "folder": folder,
            "description": description,
        },
        "level": levels,
    }


def create_dimension_dict(
    dim_id: str,
    name: str,
    visible: bool,
    hierarchy_dict: dict = None,
    time_dimension: bool = False,
    participating_datasets: List[str] = None,
    description: str = "",
):
    properties = {"visible": visible}
    if description:
        properties["description"] = description
    if hierarchy_dict:
        hierarchy = [hierarchy_dict]
    else:
        hierarchy = []
    if time_dimension:
        properties["dimension-type"] = "Time"
    dict = {"id": dim_id, "name": name, "properties": properties, "hierarchy": hierarchy}
    if participating_datasets:
        dict["participating-datasets"] = participating_datasets
    return dict


def create_measure_dict(
    measure_id: str,
    measure_name: str,
    agg_type: Aggs,
    caption: str,
    description: str = None,
    formatting: dict = None,
    folder: str = None,
    visible: bool = True,
    key_ref: str = None,
):
    agg_dict = agg_type.get_dict_expression(key_ref)
    properties = {"type": agg_dict, "caption": caption, "visible": visible}
    if description is not None:
        properties["description"] = description
    if formatting is not None:
        properties["formatting"] = formatting
    if folder is not None:
        properties["folder"] = folder

    new_measure = {"id": measure_id, "name": measure_name, "properties": properties}

    return new_measure


def create_dataset_dict(
    dataset_id: str,
    dataset_name: str,
    table_name: str,
    warehouse_id: str,
    columns: List[dict],
    allow_aggregates: bool,
    schema: str = None,
    database: str = None,
):
    dataset = {
        "id": dataset_id,
        "name": dataset_name,
        "properties": {
            "allow-aggregates": allow_aggregates,
            "aggregate-locality": None,
            "aggregate-destinations": None,
        },
        "physical": {
            "connection": {"id": warehouse_id},
            "tables": [{"name": table_name}],
            "immutable": False,
            "columns": columns,
        },
        "logical": {},
    }

    if schema:
        dataset["physical"]["tables"][0]["schema"] = schema
    if database:
        dataset["physical"]["tables"][0]["database"] = database

    return dataset


def create_query_dataset_dict(
    dataset_id: str,
    dataset_name: str,
    warehouse_id: str,
    columns: List[dict],
    allow_aggregates: bool,
    query: str,
):
    dataset = {
        "id": dataset_id,
        "name": dataset_name,
        "properties": {
            "allow-aggregates": allow_aggregates,
            "aggregate-locality": None,
            "aggregate-destinations": None,
        },
        "physical": {
            "connection": {"id": warehouse_id},
            "queries": [{"sqls": [{"expression": query}]}],
            "immutable": False,
            "columns": columns,
        },
        "logical": {},
    }
    return dataset


def create_query_for_post_request(
    query: str,
    project_name: str,
    organization: str,
    use_aggs=True,
    gen_aggs=False,
    fake_results=False,
    use_local_cache=True,
    use_aggregate_cache=True,
    timeout=10,
) -> dict:
    return {
        "language": "SQL",
        "query": query,
        "context": {
            "organization": {"id": organization},
            "environment": {"id": organization},
            "project": {"name": project_name},
        },
        "aggregation": {"useAggregates": use_aggs, "genAggregates": gen_aggs},
        "fakeResults": fake_results,
        "dryRun": False,  # keeping this here, so we check if it works in the future, see AL-512, such a low num ik
        "useLocalCache": use_local_cache,
        "useAggregateCache": use_aggregate_cache,
        "timeout": f"{timeout}.minutes",
    }


def create_cube_dict(query_name: str, caption: str = "", description: str = "") -> dict:
    if not caption:
        caption = query_name
    cube = {
        "id": str(uuid.uuid4()),
        "name": query_name,
        "properties": {
            "caption": caption,
            "description": description,
            "visible": True,
        },
    }
    return cube
