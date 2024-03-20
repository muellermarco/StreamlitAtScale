import urllib


### engine side endpoints
def _endpoint_connection_groups(
    atconn,
) -> str:
    return f"{atconn.engine_url}/connection-groups/orgId/{atconn.organization}"


def _endpoint_published_project_list(
    atconn,
    suffix: str = "",
):
    return f"{atconn.engine_url}/projects/published/orgId/{atconn.organization}{suffix}"


def _endpoint_draft_project_unpublish(
    atconn,
    published_project_id: str,
):
    return f"{atconn.engine_url}/projects/orgId/{atconn.organization}/schema/{published_project_id}"


def _endpoint_query_view_recent_queries(
    atconn,
    date_time: str,
    limit: int = 21,
):
    """Returns the queries from the previous 5 minutes"""
    return (
        f"{atconn.engine_url}/queries/orgId/{atconn.organization}"
        f"?limit={limit}&userId={atconn.username}&querySource=user"
        f"&queryStarted=5m&queryDateTimeStart={date_time}"
    )


def _endpoint_warehouse_databases(
    atconn,
    warehouse_id: str,
):
    """<engine_url>/data-sources/ordId/<organization>"""
    return f"{atconn.engine_url}/data-sources/orgId/{atconn.organization}/conn/{warehouse_id}/databases"


def _endpoint_warehouse_all_schemas(
    atconn,
    warehouse_id: str,
    database=None,
):
    """<engine_url>/data-sources/ordId/<organization>"""
    if database is not None:
        database = f"?database={database}"
    return f"{atconn.engine_url}/data-sources/orgId/{atconn.organization}/conn/{warehouse_id}/schemas{database}"


def _endpoint_warehouse_all_tables(
    atconn,
    warehouse_id: str,
    schema: str,
    database=None,
):
    """<engine_url>/data-sources/ordId/<organization>"""
    if database is not None:
        suffix = f"?database={database}&schema={schema}"
    else:
        suffix = f"?schema={schema}"
    return f"{atconn.engine_url}/data-sources/orgId/{atconn.organization}/conn/{warehouse_id}/tables{suffix}"


def _endpoint_warehouse_single_table_info(
    atconn,
    warehouse_id: str,
    table: str,
    schema=None,
    database=None,
):
    """<engine_url>/data-sources/ordId/<organization>"""
    suffix = ""
    if database is not None:
        suffix += f"?database={database}"
        if schema is not None:
            suffix += f"&schema={schema}"
    elif schema is not None:
        suffix += f"?schema={schema}"
    return f"{atconn.engine_url}/data-sources/orgId/{atconn.organization}/conn/{warehouse_id}/table/{table}/info{suffix}"


def _endpoint_warehouse_tables_cacheRefresh(
    atconn,
    warehouse_id: str,
):
    """<engine_url>/data-sources/ordId/<organization>"""
    return f"{atconn.engine_url}/data-sources/orgId/{atconn.organization}/conn/{warehouse_id}/tables/cacheRefresh"


def _endpoint_warehouse_query_info(
    atconn,
    warehouse_id: str,
):
    """<engine_url>/data-sources/ordId/<organization>"""
    return f"{atconn.engine_url}/data-sources/orgId/{atconn.organization}/conn/{warehouse_id}/query/info"


def _endpoint_expression_eval_data_types(
    atconn,
    connection_id: str,
    table_name: str,
):
    return f"{atconn.engine_url}/expression-evaluator/evaluate/orgId/{atconn.organization}/conn/{connection_id}/table/{table_name}"


def _endpoint_mdx_syntax_validation(
    atconn,
):
    return f"{atconn.engine_url}/mdx-expression/value/validate"


def _endpoint_dmv_query(
    atconn,
    suffix: str = "",
):
    return f"{atconn.engine_url}/xmla/{atconn.organization}{suffix}"


def _endpoint_jdbc_port(
    atconn,
    suffix: str = "",
):
    """Gets the jdbc port for the org"""
    return f"{atconn.engine_url}/organizations/orgId/{atconn._organization}{suffix}"


def _endpoint_engine_version(
    atconn,
    suffix: str = "",
):
    """Gets the version of the AtScale instance"""
    return f"{atconn.engine_url}/version{suffix}"


def _endpoint_license_details(
    atconn,
    suffix: str = "",
):
    """Gets the license for this instance"""
    return f"{atconn.engine_url}/license/capabilities"


def _endpoint_atscale_query_submit(
    atconn,
):
    """Sends an AtScale query"""
    return f"{atconn.engine_url}/query/orgId/{atconn.organization}/submit"


def _endpoint_design_draft_project(
    atconn,
    draft_project_id: str,
):
    return (
        f"{atconn.design_center_url}/api/1.0/org/{atconn.organization}/project/{draft_project_id}"
    )


def _endpoint_design_publish_project(
    atconn,
    draft_project_id: str,
):
    return f"{atconn.design_center_url}/api/1.0/org/{atconn.organization}/project/{draft_project_id}/publish"


def _endpoint_design_copy_draft_project(
    atconn,
    draft_project_id: str,
    cube_id: str,
):
    return f"{atconn.design_center_url}/api/1.0/org/{atconn.organization}/project/{draft_project_id}/cube/{cube_id}/copy"


def _endpoint_design_all_snapshots(
    atconn,
    draft_project_id: str,
):
    return f"{atconn.design_center_url}/api/1.0/org/{atconn.organization}/project/{draft_project_id}/snapshots"


def _endpoint_design_specific_snapshot(
    atconn,
    draft_project_id: str,
    snapshot_id: str,
):
    return f"{atconn.design_center_url}/api/1.0/org/{atconn.organization}/project/{draft_project_id}/snapshots/{snapshot_id}"


def _endpoint_design_restore_snapshot(
    atconn,
    draft_project_id: str,
    snapshot_id: str,
):
    return f"{atconn.design_center_url}/api/1.0/org/{atconn.organization}/project/{draft_project_id}/snapshots/{snapshot_id}/restore"


def _endpoint_design_create_project(atconn):
    return f"{atconn.design_center_url}/api/1.0/org/{atconn.organization}/project"


def _endpoint_design_clone_project(
    atconn,
    project_id: str,
    new_project_name: str,
):
    url_parameters = f"access=copy&newName={new_project_name}&speculativeAggregate=false"
    return f"{atconn.design_center_url}/api/1.0/org/{atconn.organization}/project/{project_id}/copy?{url_parameters}"


def _endpoint_design_private_org_full_query(
    atconn,
    query_id: str,
    sub_query_id: str,
):
    return (
        f"{atconn.design_center_url}/org/{atconn.organization}"
        f"/fullquerytext/queryId/{query_id}?subquery={sub_query_id}"
    )


def _endpoint_auth_bearer(
    atconn,
    suffix: str = "",
):
    """Pings auth endpoint and generates a bearer token"""
    return f"{atconn.design_center_url}/{atconn.organization}/auth{suffix}"


def _endpoint_jwt(
    atconn,
):
    """Endpoint for getting JWT token"""
    return f"{atconn.design_center_url}/jwt/get"


def _endpoint_session(
    atconn,
):
    """Endpoint for getting the current session"""
    return f"{atconn.design_center_url}/api/1.0/sessiontoken"


def _endpoint_login_screen(
    atconn,
    suffix: str = "",
):
    """endpoint for the general login screen, get information without credentials"""
    return f"{atconn.design_center_url}/login{suffix}"


def _endpoint_project_folder(
    atconn,
    suffix: str = "",
):
    """endpoint for the project folders screen that has the urls embedded"""
    return f"{atconn.design_center_url}/org/{atconn.organization}/folders{suffix}"


def _endpoint_list_projects(
    atconn,
    suffix: str = "",
):
    """gets all draft projects"""
    return f"{atconn.design_center_url}/api/1.0/org/{atconn.organization}/projects{suffix}"


def _endpoint_create_empty_project(
    atconn,
    suffix: str = "",
):
    """creates an empty project"""
    return (
        f"{atconn.design_center_url}/api/1.0/org/{atconn.organization}/project/createEmpty{suffix}"
    )


def _endpoint_engine_settings(atconn):
    """Gets the engine settings for this instance"""
    return f"{atconn.design_center_url}/api/1.0/org/{atconn.organization}/engineGeneralSettings"


def _endpoint_user_account(atconn):
    """Gets the token for the user"""
    user = urllib.parse.quote_plus(atconn._user_id)
    return f"{atconn.design_center_url}/api/1.0/org/{atconn.organization}/userAccount/{user}"
