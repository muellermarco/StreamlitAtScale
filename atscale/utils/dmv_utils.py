import re
from typing import Dict, List

from atscale.connection.connection import _Connection
from atscale.base import endpoints
from atscale.errors import atscale_errors
from atscale.base.enums import DMVColumnBaseClass, RequestType


def get_dmv_data(
    model,
    fields: List[DMVColumnBaseClass] = None,
    filter_by: Dict[DMVColumnBaseClass, List[str]] = None,
    id_field: DMVColumnBaseClass = None,
):
    """Returns DMV data for a given query type, on the given project-model in the _Connection as a dict with
    items for each member of that type (ex. date_hierarchy: {}, item_hierarchy: {}).

    Args:
        model (DataModel): The connected DataModel to be queried against
        fields (list of DMVColumnBaseClass fields, optional): A list of keys to query and return. id_field does not need to be
            included. Defaults to None.
        filter_by (dict[DMVColumnBaseClass fields, str], optional): A dict with keys of fields and values of a list of that field's value
            to exclusively include in the return. Defaults to None.
        id_field (DMVColumnBaseClass, optional): The field to split items in the return dict by, the value of this field will be the key in the
            dict. Defaults to None to use the name field of the enum. Defaults to None.
    Raises:
        UserError: If any given key is not a enums.DMVColumnBaseClass enum or the _type parameter is not a enums enum.
        Exception: If there is some other problem communicating with the atscale instance an exception may be raised

    Returns:
        dict: A dict with each member's name as the key, with the corresponding value being a dict with key-value
        pairs for each piece of metadata queried.
    """
    if model.project.published_project_name is None:
        if len(model.project.get_published_projects()) > 0:
            raise atscale_errors.UserError(
                "The project of the provided data_model must have an associated "
                "published project before submitting a DMV query. "
                "Try calling project.select_published_project()"
            )
        else:
            raise atscale_errors.UserError(
                "A published project is required to query against, but there is no "
                "published version of the project of the provided data_model. "
                "A project can be published programmatically by calling Project.publish()"
            )
    if filter_by is None:
        filter_by = {}
    if not fields:
        fields = []
        if not id_field:
            raise ValueError("One of either fields or id_field need to have a value")
    elif id_field is None:
        id_field = fields[0].__class__.name

    # type checking
    schemas_in_fields = {f.__class__.__name__ for f in fields}
    if len(schemas_in_fields) > 1:
        raise atscale_errors.UserError(
            f"Conflicting DMV fields. The fields parameter contains query keys from the "
            f"following schemas: {schemas_in_fields}"
        )
    if id_field is not None and fields and id_field.__class__ != fields[0].__class__:
        raise atscale_errors.UserError(
            f"The schema '{id_field.__class__.__name__}' used for the id_field parameter "
            f"does not match the schema '{fields[0].__class__.__name__}' used in fields."
        )
    conflicting_filter_keys = set()
    for key in filter_by.keys():
        if key.__class__ != id_field.__class__:
            conflicting_filter_keys.add(key.__class__.__name__)
    if conflicting_filter_keys:
        raise atscale_errors.UserError(
            f"The following schemas {conflicting_filter_keys} used for the filter_by "
            f"parameter do not match the schema '{id_field.__class__.__name__}' "
            f"used in fields."
        )

    filter_after_querying = {}
    filter_in_query = {}

    # sometimes the member names are slightly different than what the dmv query expects. We can translate them as needed
    for key, value in filter_by.items():
        if key.requires_translation():
            filter_after_querying[key] = value
        else:
            filter_in_query[key] = value

    query = _generate_dmv_query_statement(
        fields=fields, filter_by=filter_in_query, id_field=id_field
    )
    rows = _submit_dmv_query(
        atconn=model.project._atconn,
        query=query,
        project_name=model.project.published_project_name,
        model_name=model.name,
    )
    dict = _parse_dmv_helper(
        rows=rows, fields=fields, id_field=id_field, filter_by=filter_after_querying
    )
    return dict


def _submit_dmv_query(
    atconn: _Connection,
    project_name: str,
    model_name: str,
    query: str,
):
    """Submits a DMV Query to this atscale connection and returns a list of rows expressed as xml strings.
        DMV queries hit the published project, meaning any changes that are only in the draft of the project will not
        be queryable through a DMV query

    Args:
        atconn (_Connection): The atscale connection to execute queries against
        project_name (str): The published project to execute the dmv query against
        model_name (str): The model to execute the dmv query against
        query (str): The content of the dmv query itself, a more limited version of a sql query

    Returns:
        List[str]: the string representation of the xml as a list of rows
    """
    query_body = _dmv_query_body(statement=query, project_name=project_name, model_name=model_name)
    url = endpoints._endpoint_dmv_query(atconn)
    response = atconn._submit_request(
        request_type=RequestType.POST, url=url, data=query_body, content_type="xml"
    )

    xml_text = str(response.content)

    rows = re.findall("<row>(.*?)</row>", xml_text)

    return rows


def _generate_dmv_query_statement(
    fields: List[DMVColumnBaseClass] = None,
    filter_by: Dict[DMVColumnBaseClass, List[str]] = None,
    id_field: DMVColumnBaseClass = None,
):
    """Generates a query statement to feed into submit_dmv_query, will query the given keys in the schema of the given
     type. If filter_by_names is passed, then the query will only query for the given names, otherwise it will query
     all. For example, querying Measure type without passing some filter_by akin to {Measure.name : [<measure_name>]} will
     query all measures that exist in the model.

    Args:
        fields (List[DMVColumnBaseClass], optional): The specific fields to query. Defaults to None to query all.
        filter_by (Dict[DMVColumnBaseClass, List[str]], optional): A dict with keys of fields and values of a list of that field's value
                to include in the return. Defaults to None.
        id_field (DMVColumnBaseClass, optional): The field to split items of the query by. Defaults to None.

    Returns:
        str: a DMV query statement
    """
    if fields is None:
        fields = []

    # this will throw an error if fields and id_fields are both none. Since this is a private helper, the check for this is done outside of this function
    if id_field is None:
        id_field = fields[0].__class__.name
        id_name = f"[{id_field.__class__.name.value}]"
    else:
        id_name = f"[{id_field.value}]"

    fields = ", ".join([f"{id_name}"] + [f"[{k.value}]" for k in fields if k != id_field])
    schema = id_field.schema
    where_clause = id_field.where
    if filter_by:
        if not where_clause:
            where_clause = " WHERE "
        else:
            where_clause += " AND "
        filter_clauses = [
            "(" + " OR ".join(f"[{k.value}] = '{name}'" for name in filter_by[k]) + ")"
            for k in filter_by.keys()
        ]
        where_clause += " AND ".join(filter_clauses)
    return f"SELECT {fields} FROM {schema}{where_clause}"


def _dmv_query_body(
    statement: str,
    project_name: str,
    model_name: str,
):
    """Creates the dmv query body for the given statement, project, and model.

    Args:
        statement (str): The dmv query statement.
        project_name (str): The query name of the project to query.
        model_name (str): The query name of the data model to query.

    Returns:
        str: a DMV query body
    """
    return f"""<?xml version="1.0" encoding="UTF-8"?>
                <Envelope xmlns="http://schemas.xmlsoap.org/soap/envelope/">
                    <Body>
                        <Execute xmlns="urn:schemas-microsoft-com:xml-analysis">
                            <Command>
                            <Statement>{statement}</Statement>
                            </Command>
                            <Properties>
                            <PropertyList>
                                <Catalog>{project_name}</Catalog>
                            </PropertyList>
                            </Properties>
                            <Parameters xmlns:xsd="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
                            <Parameter>
                                <Name>CubeName</Name>
                                <Value xsi:type="xsd:string">{model_name}</Value>
                            </Parameter>
                            </Parameters>
                        </Execute>
                    </Body>
                </Envelope>"""


def _parse_dmv_helper(
    rows: List[str],
    fields: List[DMVColumnBaseClass],
    id_field: DMVColumnBaseClass,
    filter_by: Dict[DMVColumnBaseClass, List[str]] = {},
) -> Dict[str, dict]:
    """Parses the given rows of xml text into a dict with keys determined by the values of the id_field and values being the selected members of the
        appropriate DMVColumnBaseClass

    Args:
        rows (List[str]): str rows of xml text from a DMV Query response
        fields (List[DMVColumnBaseClass]): The fields of interest to include in the response
        id_field (DMVColumnBaseClass): The enum members whose values will be the keys of the response dict
        filter_by (Dict[DMVColumnBaseClass, List[str]], optional): the values of the enum members to omit from the reponse

    Returns:
        Dict[str, dict]: A dictionary of the {id_field_values: {enum_members: enum_member_values_in_response}}
    """
    # convert filter_by values to dict to save iterating fully for every filtered out value
    filter_by = {k: {v: True for v in l} for k, l in filter_by.items()}
    result = {}

    # this will throw an error if fields and id_fields are both none. Since this is a private helper, the check for this is done outside of this function
    if id_field is None:
        id_field = fields[0].__class__.name

    # iterate over the dmv query response, pulling the metadata out
    for row in rows:
        # marker if something is in the flagged to be filtered out
        ignore = False
        id_untranslated = re.search(id_field.to_regex(), row)[1]
        name = id_field.translate(val=id_untranslated)
        if (
            id_field in filter_by and name not in filter_by[id_field]
        ):  # names will be parsed out in query unless change
            continue
        sub_dict = {}
        for term in fields:
            value = re.search(term.to_regex(), row)
            if value:
                value = value[1]
                # if the row has a filter member but the value of that filter member is not in the provided list, we ignore this row
                if term in filter_by and term.translate(value) not in filter_by[term]:
                    # If we hit a value that means we should filter we mark it to ignore so we don't add it to the dict
                    ignore = True
                    break
                sub_dict[term.name] = term.translate(value)
            else:
                sub_dict[term.name] = ""
        # if not marked to ignore due to filters, process the row
        if not ignore:
            # if the key is already in the dict we only want to append to fields with new values
            if result.get(name):
                for field in result[name]:
                    if type(result[name][field]) is not list:
                        if result[name][field] != sub_dict[field]:
                            result[name][field] = [result[name][field]]
                            result[name][field].append(sub_dict[field])
                    else:
                        if sub_dict[field] not in result[name][field]:
                            result[name][field].append(sub_dict[field])
            else:
                # this means the result[name] can either map to a dict of {str:str} or {str:[str]}
                result[name] = sub_dict
    return result
