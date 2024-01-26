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


def _endpoint_draft_project(
    atconn,
    suffix: str = "",
):
    return f"{atconn.engine_url}/projects/orgId/{atconn.organization}{suffix}"


def _endpoint_query_view(
    atconn,
    suffix: str = "",
    limit: int = 21,
):
    """Returns the query viewing endpoint with the suffix appended"""
    return (
        f"{atconn.engine_url}/queries/orgId/{atconn.organization}"
        f"?limit={limit}&userId={atconn.username}{suffix}"
    )


def _endpoint_warehouse(
    atconn,
    suffix: str = "",
):
    """<engine_url>/data-sources/ordId/<organization>"""
    return f"{atconn.engine_url}/data-sources/orgId/{atconn.organization}{suffix}"


def _endpoint_expression_eval(
    atconn,
    suffix: str,
):
    return f"{atconn.engine_url}/expression-evaluator/evaluate/orgId/{atconn.organization}{suffix}"


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
    """Gets the version of the atscale instance"""
    return f"{atconn.engine_url}/version{suffix}"


def _endpoint_license_details(
    atconn,
    suffix: str = "",
):
    """Gets the license for this instance"""
    return f"{atconn.engine_url}/license/capabilities"


def _endpoint_atscale_query(
    atconn,
    suffix: str = "",
):
    """Sends an atscale query"""
    return f"{atconn.engine_url}/query/orgId/{atconn.organization}{suffix}"


def _endpoint_load_balancer(
    atconn,
    suffix: str = "",
):
    """Gets load balancer urls"""
    return f"{atconn.engine_url}/settings/loadBalancerUrls/{suffix}"


### design center endpoints
def _endpoint_design_org(
    atconn,
    suffix: str = "",
):
    return f"{atconn.design_center_url}/api/1.0/org/{atconn.organization}{suffix}"


def _endpoint_design_private_org(
    atconn,
    suffix: str = "",
):
    return f"{atconn.design_center_url}/org/{atconn.organization}{suffix}"


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


def _endpoint_engine_settings(
    atconn,
    suffix: str = "",
):
    """Gets the engine settings for this instance"""
    return f"{atconn.design_center_url}/api/1.0/org/{atconn.organization}/engineGeneralSettings"


def _endpoint_user_token(atconn):
    """Gets the token for the user"""
    return f"{atconn.design_center_url}/api/1.0/org/{atconn.organization}/usertoken"


def _endpoint_user_account(atconn):
    """Gets the token for the user"""
    user = urllib.parse.quote_plus(atconn.username)
    return f"{atconn.design_center_url}/api/1.0/org/{atconn.organization}/userAccount/{user}"
