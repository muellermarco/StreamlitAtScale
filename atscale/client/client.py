import inspect
import json
import logging
from typing import List, Dict, Tuple, Union

from pandas import DataFrame

from atscale.base import config
from atscale.connection.connection import _Connection
from atscale.base import endpoints
from atscale.db.sql_connection import SQLConnection
from atscale.data_model import data_model_helpers as dmh
from atscale.errors import atscale_errors
from atscale.parsers import project_parser
from atscale.project.project import Project
from atscale.utils import db_utils, input_utils, model_utils, project_utils, validation_utils
from atscale.base.enums import RequestType, Aggs
from inspect import getfullargspec
from atscale.utils.validation_utils import validate_by_type_hints

logger = logging.getLogger(__name__)


class Client:
    """Creates a Client with a connection to an AtScale server to allow for interaction with the projects on the server."""

    def __init__(
        self,
        config_path: str = None,
        server: str = None,
        username: str = None,
        organization: str = None,
        password: str = None,
        design_center_server_port: str = None,
        jdbc_driver_class: str = None,
        jdbc_driver_path: str = None,
        verify: Union[str, bool] = None,
    ):
        """All parameters are optional. If none are provided, this method will attempt to use values from the following, local configuration files:
        - ~/.atscale/config - for server, organization, and design_center_server_port
        - ~/.atscale/credentials - for username and password

        If a config_path parameter is provided, all values will be read from that file.

        Any values provided in addition to a config_path parameter will take precedence over values read in from the file at config_path.

        Args:
            config_path (str, optional): path to a configuration file in .INI format with values for the other parameters. Defaults to None.
            server (str, optional): the atscale server instance. Defaults to None.
            username (str, optional): username. Defaults to None.
            organization (str, optional): the atscale organization id. Defaults to None.
            password (str, optional): password. Defaults to None.
            design_center_server_port (str, optional): port for atscale design center. Defaults to '10500'.
            jdbc_driver_class (str, optional): The class of the hive jdbc driver to use. Defaults to com.cloudera.hive.jdbc.HS2Driver.
            jdbc_driver_path (str, optional): The path to the hive jdbc driver to use. Defaults to '' which will not allow querying via jdbc
            verify (str|bool, optional): Whether to verify ssl certs. Can also be the path to the cert to use. Defaults to True.

        Raises:
            ValueError: an error if insufficient information provided to establish a connection.

        Returns:
            Client: an instance of this class
        """
        inspection = getfullargspec(self.__init__)
        validate_by_type_hints(inspection=inspection, func_params=locals())

        # Config will load default config files config.ini, ~/.atscale/config and ~/.atscale/credentials on first call to constructor.
        # It's a singleton, so subsequent calls to it's constructor will simply obtain a reference to the existing instance.
        if config_path is not None:
            cfg = config.Config()
            # Any keys in here that are already in Config will get new values from this file
            cfg.read(config_path)
        # go ahead nad grab the connection values from config
        s, u, p, o, d, dc, dp, v = self._get_connection_parameters_from_config()
        # finally, we'll overwrite values with any they passed in
        if server is not None:
            s = server
        if username is not None:
            u = username
        if organization is not None:
            o = organization
        if password is not None:
            p = password
        if jdbc_driver_class is not None:
            dc = jdbc_driver_class
        if jdbc_driver_path is not None:
            dp = jdbc_driver_path

        if verify is not None:
            v = verify
        elif v is None:
            v = True

        # if someone passed in a value, we'll use that (defaults to None)
        if design_center_server_port is not None:
            # If I use default value of port instead of None, then I won't know if the value here was specified
            # by the user passing it in, or if they didn't pass in the parameter and let it go to default. By using
            # None as default, I know they did not pass in a value. I want one more check if we got it from config
            d = design_center_server_port
        elif d is None:  # if the value wasn't found in the Config file, let's use the default
            d = config.DEFAULT_DESIGN_CENTER_PORT

        # if we didn't find these values in the Config work above and they weren't passed in, then we didn't get enough info
        if s is None:
            raise ValueError(f"Value for server cannot be null.")
        # otherwise we'll go ahead and make the connection object
        self._atconn = _Connection(s, u, p, o, d, dc, dp, v)

    def get_version(self) -> str:
        """A getter function for the current version of the library

        Returns:
            str: The current version of the library
        """
        return config.Config().version

    def connect(self):
        """Initializes the Client object's connection"""
        self._atconn._connect()

    def _get_connection_parameters_from_config(self):
        cfg = config.Config()
        # should be placed in ~/.atscale/credentials then config will grab them
        username = cfg.get("username")
        password = cfg.get("password")
        # Config reads these first from config.ini in project root and then ~/.atscale/config.
        # Would be overwritten with any values from subsequent config_path read in.
        server = cfg.get("server")
        organization = cfg.get("organization")
        design_center_server_port = cfg.get("design_center_server_port")
        jdbc_driver_class = cfg.get(
            "jdbc_driver_class", default_value="org.apache.hive.jdbc.HiveDriver"
        )
        jdbc_driver_path = cfg.get("jdbc_driver_path", default_value="")
        verify = cfg.get("verify")
        return (
            server,
            username,
            password,
            organization,
            design_center_server_port,
            jdbc_driver_class,
            jdbc_driver_path,
            verify,
        )

    def create_empty_project(
        self,
        project_name: str,
    ) -> Project:
        """Creates an empty project in the associated org

        Args:
            project_name (str): The name of the empty project to be created

        Returns:
            Project: An empty project
        """
        inspection = getfullargspec(self.create_empty_project)
        validate_by_type_hints(inspection=inspection, func_params=locals())

        self._atconn._check_connected()

        existing_projects = self.get_projects()
        if len(existing_projects) > 0:
            for x in existing_projects:
                if x["draft_name"] == project_name:
                    raise ValueError(
                        f"Project named {project_name} already exists. Please try a new name."
                    )

        # creates an empty project
        u = endpoints._endpoint_create_empty_project(self._atconn)
        p = {"name": project_name}
        p = json.dumps(p)
        # this call will handle or raise any errors
        response = self._atconn._submit_request(request_type=RequestType.POST, url=u, data=p)
        project_dict = json.loads(response.content)["response"]
        # now we'll use the values to construct a python Project class
        project_id = project_dict.get("id")

        # put this in a try catch
        try:
            logging.disable(logging.WARNING)
            proj = Project(client=self, draft_project_id=project_id)
        finally:
            logging.disable(logging.NOTSET)
        return proj

    def select_project(
        self,
        draft_project_id: str = None,
        published_project_id: str = None,
        name_contains: str = None,
        include_soft_publish: bool = False,
    ) -> Project:
        """Selects a project based on user input

        Args:
            draft_project_id (str, optional): An draft project id, will result in a prompt
                to select a published project if one exists. If None, asks user to select from list of draft
                projects. Defaults to None.
            published_project_id (str, optional): The published project id to use if multiple exist for the given draft
            name_contains (str, optional): A string to use for string comparison to filter the found project names.
                Defaults to None.
            include_soft_publish (bool, optional): Whether to include soft published projects. Defaults to False.

        Returns:
            Project: The desired project
        """
        inspection = getfullargspec(self.select_project)
        validate_by_type_hints(inspection=inspection, func_params=locals())

        self._atconn._check_connected()

        if draft_project_id is not None:
            # the validity of this will be checked in the project constructor
            id = draft_project_id
        else:
            # projects is a list of dicts where each is a project
            projects = self.get_projects()

            # if they have an idea of the name we can limit the return list
            if name_contains is not None:
                projects = [x for x in projects if name_contains.lower() in x["draft_name"].lower()]

            # ask the user to select one of the projects, return dict result
            project_dict = input_utils.choose_id_and_name_from_dict_list(
                projects, "Please choose a project:", id_key="draft_id", name_key="draft_name"
            )
            id = project_dict.get("draft_id")

        project = Project(
            client=self,
            draft_project_id=id,
            published_project_id=published_project_id,
            include_soft_publish=include_soft_publish,
        )
        return project

    def autogen_semantic_model(
        self,
        dbconn: SQLConnection,
        warehouse_id: str,
        project_name: str,
        table_name: str,
        dataframe: DataFrame = None,
        generate_date_table: bool = True,
        default_aggregation_type: Aggs = Aggs.SUM,
        publish: bool = True,
    ) -> Project:
        """Auto-generates a project and semantic layer based on column types and values.
        If a dataframe is provided it will be uploaded to create the table.
        If dataframe is None we will try to use an already existing table with the given table_name.

        Args:
            dbconn (SQLConnection): the database to store our new table
            warehouse_id (str): the name of the database connection in atscale
            project_name (str): name of the new project to create
            table_name (str): name of the table in the source database
            dataframe (DataFrame, optional): the pandas dataframe to build our semantic model from. Defaults to none to use an existing table
            generate_date_table (bool, optional): whether generate a date table in the data warehouse. Defaults to True.
            default_aggregation_type (Aggs): the default aggregation type for numeric columns. Defaults to SUM
            publish (bool, optional): whether created  project should be published. Defaults to True.

        Returns:
            Project: the newly created Project object
        """
        inspection = getfullargspec(self.autogen_semantic_model)
        validate_by_type_hints(inspection=inspection, func_params=locals())

        self._atconn._check_connected()

        if project_name in [project["draft_name"] for project in self.get_projects()]:
            raise ValueError(
                f"A project named {project_name} already exists, please try a new name."
            )
        if dataframe is not None:
            dbconn.write_df_to_db(table_name=table_name, dataframe=dataframe)
            expected_columns = dataframe.columns
        else:
            expected_columns = None
        columns, atscale_table_name, schema, database = dmh._get_atscale_names(
            atconn=self._atconn,
            warehouse_id=warehouse_id,
            dbconn=dbconn,
            table_name=table_name,  # return this table_name but how atscale sees it
            expected_columns=expected_columns,
            include_dtype=True,
        )
        # create a new, empty project
        project = self.create_empty_project(project_name)
        project_dict = project._get_dict()
        # create the data set and add it to the new, empty
        dataset, dataset_id = project_utils.create_dataset(
            warehouse_id=warehouse_id,
            database=database,
            schema=schema,
            table_name=atscale_table_name,
            table_columns=columns,
        )
        project_utils.add_dataset(project_dict, dataset)
        # Grab the single, default data_model from the project and add a data-set-ref to it which references the dataset we just added to the project.
        model_dict = project_parser.get_cubes(project_dict)[0]
        model_utils._add_data_set_ref(model_dict, dataset_id)
        # now we update the data_model by automatically adding any dimensions / measures we can identify
        model_utils._create_semantic_model(
            atconn=self._atconn,
            dbconn=dbconn,
            table_name=atscale_table_name,
            project_dict=project_dict,
            cube_id=model_dict.get("id"),
            dataset_id=dataset_id,
            columns=columns,
            generate_date_table=generate_date_table,
            default_aggregation_type=default_aggregation_type,
        )
        # finally update the project using projet_dict after all the mutations from above
        project._update_project(project_json=project_dict, publish=publish)
        return project

    def get_organizations(self) -> List[Dict[str, str]]:
        """Prints all Organizations for the associated Server if possible and returns a list of dicts
            for each of the listed organizations. List index should match printed index.

        Returns:
            List[Dict[str,str]]: List of 'id':'name' pairs of available orgs.
        """
        self._atconn._check_connected()

        orgList = self._atconn._get_orgs_for_all_users()

        for i, dct in enumerate(orgList):
            print(f"Index:{i} ID: {dct['id']}: Name: {dct['name']}")

        return orgList

    def get_projects(
        self,
        include_soft_publish: bool = False,
    ) -> List[Dict[str, str]]:
        """Prints all Projects that are visible for the associated organization. Returns a list of dicts
            for each of the listed Projects.

        Args:
            include_soft_publish (bool, optional): Whether to include soft published projects. Defaults to False.

        Returns:
            List[Dict[str,str]]: List of 3 item dicts where keys are 'draft_id', 'draft_name', 'published_projects' of available Projects.
        """
        inspection = getfullargspec(self.get_projects)
        validate_by_type_hints(inspection=inspection, func_params=locals())
        self._atconn._check_connected(),

        projectsList = self._atconn._get_projects()
        if projectsList is None:
            return []

        published_project_list = self._atconn._get_published_projects()

        ret_list = []
        for dct in projectsList:
            ret_dict = {}
            ret_dict["draft_id"] = dct["id"]
            ret_dict["draft_name"] = dct["name"]

            # now to deal with the published projects
            specific_published_projects_list = project_parser.parse_published_projects_for_project(
                dct, published_project_list, include_soft_publish
            )
            if not specific_published_projects_list:
                ret_dict["published_projects"] = []
            else:
                published_list = []
                for i, pub_dct in enumerate(specific_published_projects_list):
                    published_dict = {}
                    published_dict["published_id"] = pub_dct["id"]
                    published_dict["published_name"] = pub_dct["name"]
                    published_list.append(published_dict)
                ret_dict["published_projects"] = published_list

            ret_list.append(ret_dict)

        return ret_list

    def get_published_projects(
        self,
        draft_project_id: str,
        include_soft_publish: bool = False,
    ) -> List[Dict[str, str]]:
        """Prints all Published Projects that are visible for the associated organization for the
            given draft project id. Returns a list of dicts for each of the listed Projects. List
            index should match printed index.

        Args:
            draft_project_id (str): The id of the draft project of interest
            include_soft_publish (bool, optional): Whether to include soft published projects. Defaults to False.

        Returns:
            List[Dict[str,str]]: List of 'id':'name' pairs of available published Projects.
        """
        inspection = getfullargspec(self.get_published_projects)
        validate_by_type_hints(inspection=inspection, func_params=locals())

        self._atconn._check_connected()

        draft_project_dict = self._atconn._get_draft_project_dict(draft_project_id)

        published_project_list = self._atconn._get_published_projects()

        specific_published_projects_list = project_parser.parse_published_projects_for_project(
            draft_project_dict, published_project_list, include_soft_publish
        )
        ret_list = []
        for dct in specific_published_projects_list:
            ret_dict = {}
            ret_dict["id"] = dct["id"]
            ret_dict["name"] = dct["name"]
            ret_list.append(ret_dict)

        return ret_list

    def unpublish_project(
        self,
        published_project_id: str,
    ) -> bool:
        """Unpublishes the provided published_project_id making in no longer queryable

        Args:
            published_project_id (str): the id of the published project to unpublish

        Returns:
            bool: Whether the unpublish was successful
        """
        inspection = getfullargspec(self.unpublish_project)
        validate_by_type_hints(inspection=inspection, func_params=locals())

        self._atconn._check_connected()

        return self._atconn._unpublish_project(published_project_id=published_project_id)

    def get_connected_warehouses(self) -> List[Dict]:
        """Returns metadata on all warehouses visible to the connected client

        Raises:
            UserError: If no connection established.

        Returns:
            List[Dict]: The list of available warehouses
        """

        return self._atconn._get_connected_warehouses()

    def get_connected_databases(
        self,
        warehouse_id: str,
    ) -> List[str]:
        """Get a list of databases the organization can access in the provided warehouse.

        Args:
            warehouse_id (str): The atscale warehouse connection to use.

        Returns:
            List[str]: The list of available databases
        """
        inspection = getfullargspec(self.get_connected_databases)
        validate_by_type_hints(inspection=inspection, func_params=locals())

        return self._atconn._get_connected_databases(warehouse_id=warehouse_id)

    def get_connected_schemas(
        self,
        warehouse_id: str,
        database: str,
    ) -> List[str]:
        """Get a list of schemas the organization can access in the provided warehouse and database.

        Args:
            warehouse_id (str): The atscale warehouse connection to use.
            database (str): The database to use.

        Returns:
            List[str]: The list of available tables
        """
        inspection = getfullargspec(self.get_connected_schemas)
        validate_by_type_hints(inspection=inspection, func_params=locals())

        return self._atconn._get_connected_schemas(warehouse_id=warehouse_id, database=database)

    def get_connected_tables(
        self,
        warehouse_id: str,
        database: str,
        schema: str,
    ) -> List[str]:
        """Get a list of tables the organization can access in the provided warehouse, database, and schema.

        Args:
            warehouse_id (str): The atscale warehouse connection to use.
            database (str): The database to use.
            schema (str,): The schema to use.

        Returns:
            List[str]: The list of available tables
        """
        inspection = getfullargspec(self.get_connected_tables)
        validate_by_type_hints(inspection=inspection, func_params=locals())

        return self._atconn._get_connected_tables(
            warehouse_id=warehouse_id, database=database, schema=schema
        )

    def get_table_columns(
        self,
        warehouse_id: str,
        table_name: str,
        database: str = None,
        schema: str = None,
        expected_columns: List[str] = None,
    ) -> List[Tuple]:
        """Get all columns in a given table

        Args:
            warehouse_id (str): The atscale warehouse to use.
            table_name (str): The name of the table to use.
            database (str, optional): The database to use. Defaults to None to use default database
            schema (str, optional): The schema to use. Defaults to None to use default schema
            expected_columns (List[str], optional): A list of expected column names to validate. Defaults to None

        Returns:
             List[Tuple]: Pairs of the columns and data-types (respectively) of the passed table
        """
        inspection = getfullargspec(self.get_table_columns)
        validate_by_type_hints(inspection=inspection, func_params=locals())

        return self._atconn._get_table_columns(
            warehouse_id=warehouse_id,
            table_name=table_name,
            database=database,
            schema=schema,
            expected_columns=expected_columns,
        )

    def get_query_columns(
        self,
        warehouse_id: str,
        query: str,
    ):
        """Get all columns of a direct query, to the given warehouse_id, as they are represented by AtScale.

        Args:
            warehouse_id (str): The atscale warehouse to use.
            query (str): A valid query for the warehouse of the given id, of which to return the resulting columns

        Returns:
            List[Tuple]: A list of columns represented as Tuples of (name, data-type)
        """
        inspection = getfullargspec(self.get_query_columns)
        validate_by_type_hints(inspection=inspection, func_params=locals())

        return self._atconn._get_query_columns(warehouse_id=warehouse_id, query=query)

    def clone_project(
        self,
        base_project: Project,
        clone_name: str,
        publish: bool = True,
    ):
        """Clones the given project.

        Args:
            base_project (Project): The base project to clone.
            clone_name (str): The query name of the new cloned project.
            publish (bool): Defaults to True, whether the new project should be published

        Returns:
            Project: The clone of the current project
        """
        inspection = getfullargspec(self.clone_project)
        validate_by_type_hints(inspection=inspection, func_params=locals())

        self._atconn._check_connected(
            err_msg="Establishing a connection in the atconn field is required"
        )

        cloned_project_id = project_utils.clone_project(
            self._atconn, base_project.draft_project_id, clone_name
        )

        cloned_project = Project(self, cloned_project_id)

        if publish:
            cloned_project.publish()
        return cloned_project
