import inspect
import json
import logging
from copy import deepcopy
from datetime import datetime
from typing import Dict, List

from atscale.errors import atscale_errors
from atscale.connection.connection import _Connection
from atscale.parsers import project_parser, dataset_parser as dsp
from atscale.utils import input_utils, project_utils, validation_utils
from atscale.base.enums import RequestType
from atscale.base import endpoints
from atscale.base.templates import create_cube_dict
from inspect import getfullargspec
from atscale.utils.validation_utils import validate_by_type_hints

logger = logging.getLogger(__name__)


class Project:
    """Creates an object corresponding to an AtScale project. References an AtScale Client and takes a project ID
    (and optionally a published project ID) to construct an object that houses DataModels, data sets, and any
    functionality pertaining to projects, such as snapshotting, cloning, publishing, and more.
    """

    def __init__(
        self,
        client: "Client",
        draft_project_id: str,
        published_project_id: str = None,
        include_soft_publish: bool = False,
    ):
        """The Project constructor

        Args:
            client (Client): The Client object that the project's interactions with the semantic layer will leverage
            draft_project_id (str): The draft project's ID
            published_project_id (str, optional): A published project's ID. Defaults to None.
            include_soft_publish (bool, optional): Whether to include soft publishes when looking for publishes. Defaults to False.

        Raises:
            ValueError: an error if insufficient information provided to establish a connection.
        """
        from atscale.client.client import Client

        inspection = getfullargspec(self.__init__)
        validate_by_type_hints(inspection=inspection, func_params=locals())

        if not client:
            raise ValueError("Please create a Client and connect before constructing a project.")
        client._atconn._check_connected(
            "Establishing a connection in the atconn field is required."
        )
        self._atconn: _Connection = client._atconn

        # Please do not store this locally. It's a tmp copy for rest of constructor logic only.
        project_dict = self._atconn._get_draft_project_dict(draft_project_id)
        if not project_dict:
            raise atscale_errors.UserError("There is no project for the provided draft_project_id.")

        self.__project_id: str = draft_project_id
        self.__project_name: str = project_dict.get("name")

        if published_project_id is None:
            try:
                self.select_published_project(include_soft_publish=include_soft_publish)
            except:  # else it was never published so let's default to None
                logger.warning(
                    "Unable to find published project you will not be able to query until publishing"
                )
                self.__published_project_id = None
                self.__published_project_name = None
        else:  # otherwise if they specified a published_project_id, then we need to verify it
            published_projects_list = self._atconn._get_published_projects()
            published_project_dict = project_parser.parse_published_project_by_id(
                published_projects_list, published_project_id
            )
            if published_project_dict is None:
                raise atscale_errors.UserError("There is no such published project.")
            elif project_parser.verify_published_project_dict_against_project_dict(
                project_dict, published_project_dict
            ):
                self.__published_project_id = published_project_id
                self.__published_project_name = published_project_dict.get("name")
            else:
                raise atscale_errors.UserError(
                    "The provided published project id is not associated with the provided project."
                )

    @property
    def draft_project_id(self) -> str:
        """Getter for the draf)project_id instance variable

        Returns:
            str: The draft_project_id
        """
        return self.__project_id

    @draft_project_id.setter
    def draft_project_id(
        self,
        value,
    ):
        """Setter for the draft_project_id instance variable. This property is final; it cannot be reset

        Args:
            value (Any): Setter cannot be used.

        Raises:
            Exception: The user cannot reset the value of the project ID
        """
        raise atscale_errors.UnsupportedOperationException(
            "Value of draft_project_id is final; it cannot be altered."
        )

    @property
    def project_name(self) -> str:
        """Getter for the project_name instance variable

        Returns:
            str: The project_name
        """
        return self.__project_name

    @project_name.setter
    def project_name(
        self,
        value,
    ):
        """Setter for the project_name instance variable. This property is final; it cannot be reset

        Args:
            value (Any): Setter cannot be used

        Raises:
            Exception: The user cannot reset the value of the project name
        """
        raise atscale_errors.UnsupportedOperationException(
            "Value of project_name is final; it cannot be altered."
        )

    @property
    def published_project_id(self) -> str:
        """Getter for the published_project_id instance variable

        Returns:
            str: The published_project_id
        """
        return self.__published_project_id

    @published_project_id.setter
    def published_project_id(
        self,
        value,
    ):
        """Setter for the published_project_id. This property is final; it cannot be reset

        Args:
            value (Any): Setter cannot be used

        Raises:
            Exception: The user cannot reset the value of the published project ID
        """
        raise atscale_errors.UnsupportedOperationException(
            "Value of published_project_id is final; it cannot be altered."
        )

    @property
    def published_project_name(self) -> str:
        """Getter for the published_project_name instance variable

        Returns:
            str: The published_project_name
        """
        return self.__published_project_name

    @published_project_name.setter
    def published_project_name(
        self,
        value,
    ):
        """Setter for the published_project_name instance variable. This property is final; it cannot be reset

        Args:
            value (Any): Setter cannot be used

        Raises:
            Exception: The user cannot reset the value of the published project name
        """
        raise atscale_errors.UnsupportedOperationException(
            "Value of published_project_name is final; it cannot be altered."
        )

    def _get_dict(self):
        return self._atconn._get_draft_project_dict(self.__project_id)

    def get_published_projects(self, include_soft_publish: bool = False) -> List[dict]:
        """Get all published projects associated with this project. There can be multiple publications per id.

        Args:
            include_soft_publish (bool, optional): Whether to include soft publishes when looking for publishes. Defaults to False.

        Returns:
            List[dict]: A list of dictionaries containing metadata about the various published projects
        """
        inspection = getfullargspec(self.get_published_projects)
        validate_by_type_hints(inspection=inspection, func_params=locals())

        project_dict = self._get_dict()
        published_project_list = self._atconn._get_published_projects()
        return project_parser.parse_published_projects_for_project(
            project_dict, published_project_list, include_soft_publish
        )

    def select_published_project(self, include_soft_publish: bool = False):
        """Prompts the user for input and sets the published project on this Project instance to the selected project.

        Args:
            include_soft_publish (bool, optional): Whether to include soft publishes when looking for publishes. Defaults to False.
        """
        inspection = getfullargspec(self.select_published_project)
        validate_by_type_hints(inspection=inspection, func_params=locals())

        published_project_list = self.get_published_projects(include_soft_publish)
        if not published_project_list:
            raise atscale_errors.UserError("There is no published version of this project")
        published_project_dict = input_utils.choose_id_and_name_from_dict_list(
            published_project_list, "Please choose a published project:"
        )
        if published_project_dict is None:
            # then we just don't do anything
            return
            # otherwise we set the id and name for published_project in this class to the selected one
        self.__published_project_id = published_project_dict.get("id")
        self.__published_project_name = published_project_dict.get("name")

    def get_data_model(
        self,
        model_name: str = None,
    ):
        """Returns the DataModel associated with this Project with the given name. If no
        name is provided and there is only one DataModel associated with this Project, then that
        one DataModel will be returned. However, if no name is given and there is more than one
        DataModel associated with this Project, then None will be returned.

        Args:
            model_name (str, optional): the name of the DataModel to be retrieved. Defaults to None.

        Returns:
            DataModel: a DataModel associated with this Project.
        """
        from atscale.data_model import DataModel

        inspection = getfullargspec(self.get_data_model)
        validate_by_type_hints(inspection=inspection, func_params=locals())

        data_model_dict_list = project_parser.get_data_models(self._get_dict())
        data_model_dict = None
        # if there's only one and they didn't specify a name, we'll just return the one we have
        if model_name is None and len(data_model_dict_list) == 1:
            data_model_dict = data_model_dict_list[0]
        # otherwise, let's look for the name
        elif model_name is None and len(data_model_dict_list) > 1:
            raise atscale_errors.UserError(
                "There is more than one data_model. Please provide a model_name."
            )
        else:
            for dmd in data_model_dict_list:
                if dmd.get("name") == model_name:
                    data_model_dict = dmd
                    break
        if data_model_dict is None:
            logger.warning(f"No data model was found with the name {model_name}")
            return None
        data_model_id = data_model_dict.get("id")
        data_model = DataModel(data_model_id, self)
        return data_model

    def select_data_model(
        self,
        data_model_id: str = None,
        name_contains: str = None,
    ):
        """Prompts the user to select a DataModel that the project can access.

        Args:
            data_model_id (str, optional): A data model id, will select the model with the matching id.
                If None, asks user to select from list. Defaults to None.
            name_contains (str, optional): A string to use for string comparison to filter the found data model names.
                Defaults to None.

        Returns:
            DataModel: the selected DataModel
        """
        from atscale.data_model.data_model import DataModel

        inspection = getfullargspec(self.select_data_model)
        validate_by_type_hints(inspection=inspection, func_params=locals())

        if data_model_id is None:
            data_model_dict_list = project_parser.get_data_models(self._get_dict())
            # if they have an idea of the name we can limit the return list
            if name_contains is not None:
                data_model_dict_list = [
                    x for x in data_model_dict_list if name_contains.lower() in x["name"].lower()
                ]
            data_model_dict = input_utils.choose_id_and_name_from_dict_list(
                data_model_dict_list, "Please choose a data model:"
            )
            if data_model_dict is None:
                return None
            data_model_id = data_model_dict.get("id")
            if data_model_id is None:
                msg = "data_model id was None in Project.select_data_model after getting a non None data_model_dict"
                raise Exception(msg)
        data_model = DataModel(data_model_id, self)
        return data_model

    def publish(
        self,
        new_query_name: str = None,
        version_tag: str = None,
    ) -> str:
        """Publishes the project so any changes become available to query

        Args:
            new_query_name (str, optional): The new query name to use for the published project,
            will use the default if None. Defaults to None. Do not use a query_name that already exists.
            version_tag (str, optional): A string to tag the published version with. Defaults to None.

        Raises:
            Exception: If unable to retrieve the published project after publishing

        Returns:
            str: The id of the published project
        """
        inspection = getfullargspec(self.publish)
        validate_by_type_hints(inspection=inspection, func_params=locals())

        data = {}
        if version_tag is not None:
            data["versionTag"] = str(version_tag)
        if new_query_name is None:
            if self.published_project_name != self.project_name:
                # how to publish to previously renamed published project
                data["modifications"] = {
                    "projectId": self.published_project_id,
                    "queryName": self.published_project_name,
                }
        else:  # query name is renaming the project
            data["modifications"] = {"queryName": new_query_name}

        # publishes the project
        u = endpoints._endpoint_design_org(
            self._atconn, f"/project/{self.draft_project_id}/publish"
        )
        d = json.dumps(data)
        response = self._atconn._submit_request(request_type=RequestType.POST, url=u, data=d)

        # update the published_project_id and publsihed_project_name
        # first check if the caller passed in a new name for the published_project
        if new_query_name is None:
            published_project = project_parser.parse_published_project_by_name(
                self.get_published_projects(), self.__published_project_name
            )
        else:
            published_project = project_parser.parse_published_project_by_name(
                self.get_published_projects(), new_query_name
            )

        # if we didn't set published_project above, let's try just finding the most recent one
        if published_project is None:
            published_project = project_parser.parse_most_recent_published_project_for_project(
                self._get_dict(), self.get_published_projects()
            )

        # if we found it,let's update the local variables pointing to its id and name
        if published_project is not None:
            self.__published_project_id = published_project.get("id")
            self.__published_project_name = published_project.get("name")
        else:  # otherwise something went wrong
            raise Exception("Unable to retrieve published project right after publishing.")
        return self.__published_project_id

    def unpublish(self) -> bool:
        """Unpublishes the provided published_project_id making in no longer queryable

        Args:
            published_project_id (str): the id of the published project to unpublish

        Returns:
            bool: Whether the unpublish was successful
        """
        if self.__published_project_id is None:
            logger.warning("No published project associated with this Project object.")
            return True

        responseStatus = self._atconn._unpublish_project(
            published_project_id=self.published_project_id
        )
        if responseStatus:
            self.__published_project_id = None
            self.__published_project_name = None
        return responseStatus

    def _update_project(
        self,
        project_json: dict,
        publish=True,
    ):
        """Updates the project.

        :param json project_json: The local version of the project JSON being pushed to the server.
        :param bool publish: Whether or not the updated project should be published. Defaults to True.
        """
        snap = self.create_snapshot(f"Python snapshot {datetime.now()}")
        # gets/overwrites the project json.
        url = endpoints._endpoint_design_org(
            self._atconn, suffix=f"/project/{self.draft_project_id}"
        )
        try:
            self._atconn._submit_request(
                request_type=RequestType.PUT, url=url, data=json.dumps(project_json)
            )
            if publish is True:
                self.publish()
            self.delete_snapshot(snapshot_id=snap)
        except Exception:
            self.restore_snapshot(snap)
            self.delete_snapshot(snap)
            raise

    def delete(self) -> None:
        """Unpublish all published projects built off this then delete this project

        Returns:
            Nonetype: returns None if the project is empty
        """
        # first we delete any unblished projects that may have been made on this project
        project_dict = self._get_dict()
        if project_dict is None:
            # Then there's nothing to delete
            return None
        published_project_list = self.get_published_projects(include_soft_publish=True)
        for published_project in published_project_list:
            published_project_id = published_project.get("id")
            self._atconn._unpublish_project(published_project_id=published_project_id)
        # deletes the project
        u = endpoints._endpoint_design_org(self._atconn, "/project/" + self.draft_project_id)
        response = self._atconn._submit_request(request_type=RequestType.DELETE, url=u)

    def _update_project_tables(
        self, tables=None, publish=True, project_dict: dict = None, update_project: bool = True
    ):
        """Updates the project's tables after verifying they have edits. updates the source references for the atscale dataset
        :param list of str tables: The tables to update info for. Defaults to None for all tables in the project
        :param bool publish: Whether the updated project should be published. Defaults to True.
        :param dict project_dict: the project_dict to work with. If not passed it will pull a project_dict
        :param bool update_project: if this function should update the draft project. Defaults to True
        """
        logger.debug("ATSCALE.py: updating project tables")

        if not project_dict:
            project_dict = self._get_dict()
        datasets: List[dsp.Dataset] = [
            dsp.Dataset(dset)
            for dset in project_dict["datasets"]["data-set"]
            if not dsp.Dataset(dset).is_qds()
        ]
        table_to_dset: Dict[str, dsp.Dataset] = {ds.table["name"]: ds for ds in datasets}
        if isinstance(tables, str):
            tables = [tables]
        if tables is None:
            tables = list(table_to_dset.keys())
        else:
            missing_tables = [t for t in tables if t not in table_to_dset]
            if len(missing_tables) == len(tables):
                return  # nothing to update cuz no requested tables exist or maybe they r all qds
        requires_update = False
        cache_refreshed = False
        for table_name in tables:
            if table_name not in table_to_dset:
                continue
            dataset = table_to_dset[table_name]
            if dataset.is_qds():
                continue
            if not cache_refreshed:
                # refreshes the table cache
                url = endpoints._endpoint_warehouse(
                    atconn=self._atconn,
                    suffix=f"/conn/{dataset.connection_id}/tables/cacheRefresh",
                )
                self._atconn._submit_request(request_type=RequestType.POST, url=url)
                cache_refreshed = True
            table = dataset.table
            info = ""
            if "database" in table:
                info = "?database=" + table["database"]
            if "schema" in table:
                if info == "":
                    info = "?schema=" + table["schema"]
                else:
                    info = f'{info}&schema={table["schema"]}'
            # gets metadata information on the table
            url = endpoints._endpoint_warehouse(
                self._atconn, f'/conn/{dataset.connection_id}/table/{table["name"]}/info{info}'
            )
            response = self._atconn._submit_request(request_type=RequestType.GET, url=url)
            server_columns = [
                (x["name"], x["column-type"]["data-type"])
                for x in json.loads(response.content)["response"]["columns"]
            ]  # excludes atscale sql columns
            project_columns = [(c.name, c.dtype) for c in dataset.columns if not c.is_calculated()]
            project_calc_columns = [c.column for c in dataset.columns if c.is_calculated()]
            if set(server_columns) != set(project_columns):
                raw_columns = project_utils.create_dataset_columns_from_atscale_table_columns(
                    server_columns
                )
                columns = project_calc_columns + raw_columns
                dataset.columns = columns
                requires_update = True
        if requires_update and update_project:
            self._update_project(project_json=project_dict, publish=publish)

    def create_snapshot(
        self,
        snapshot_name: str,
    ) -> str:
        """Creates a snapshot of the current project.

        Args:
            snapshot_name (str): The name of the snapshot.

        Returns:
            str: The snapshot ID.
        """
        inspection = getfullargspec(self.create_snapshot)
        validate_by_type_hints(inspection=inspection, func_params=locals())

        self._atconn._check_connected(
            err_msg="Establishing a connection in the atconn field is required"
        )

        # creates with snapshot of the given name
        url = endpoints._endpoint_design_org(
            self._atconn, f"/project/{self.draft_project_id}/snapshots"
        )
        tag = {"tag": snapshot_name}
        response = self._atconn._submit_request(
            request_type=RequestType.POST, url=url, data=json.dumps(tag)
        )
        return json.loads(response.content)["response"]["snapshot_id"]

    def update_snapshot(self, snapshot_id: str, new_snapshot_name: str):
        """Updates the snapshot with the given id to have the new name.

        Args:
            snapshot_id (str): The ID of the snapshot to update.
            new_snapshot_name (str): The new name for the snapshot.
        """
        inspection = getfullargspec(self.update_snapshot)
        validate_by_type_hints(inspection=inspection, func_params=locals())

        self._atconn._check_connected(err_msg="Establishing a connection in the client is required")

        # interacts with the snapshot of the given id
        url = endpoints._endpoint_design_org(
            self._atconn, suffix=f"/project/{self.draft_project_id}/snapshots/{snapshot_id}"
        )
        data = {"name": new_snapshot_name}
        self._atconn._submit_request(request_type=RequestType.PATCH, url=url, data=json.dumps(data))

    def delete_snapshot(
        self,
        snapshot_id: str,
    ):
        """Deletes a snapshot with the given id.

        Args:
            snapshot_id (str): The ID of the snapshot to be deleted.
        """
        inspection = getfullargspec(self.delete_snapshot)
        validate_by_type_hints(inspection=inspection, func_params=locals())

        self._atconn._check_connected(
            err_msg="Establishing a connection in the associated Client is required"
        )

        # interacts with the snapshot of the given id
        url = endpoints._endpoint_design_org(
            self._atconn, suffix=f"/project/{self.draft_project_id}/snapshots/{snapshot_id}"
        )
        self._atconn._submit_request(request_type=RequestType.DELETE, url=url)

    def restore_snapshot(
        self,
        snapshot_id: str,
    ):
        """Restores a project to the state captured in a snapshot.

        Args:
            snapshot_id (str): The ID of the snapshot to be restored from.
        """
        inspection = getfullargspec(self.restore_snapshot)
        validate_by_type_hints(inspection=inspection, func_params=locals())

        self._atconn._check_connected(
            err_msg="Establishing a connection in the atconn field is required"
        )

        # interacts with the snapshot of the given id
        url = endpoints._endpoint_design_org(
            self._atconn, f"/project/{self.draft_project_id}/snapshots/{snapshot_id}/restore"
        )
        # in API documentation, says to use put, but doesn't work
        self._atconn._submit_request(request_type=RequestType.GET, url=url)

    def get_snapshots(
        self,
        snapshot_name: str = None,
    ) -> List[dict]:
        """Returns a dictionary of the IDs of snapshots to the snapshot names. If snapshot_name is given the dictionary will be filtered
        to just snapshots with the given name.

        Args:
            snapshot_name (str, optional): The name of the snapshot for which the ID is requested.

        Returns:
            List[dict]: a list of dictionaries with snapshot metadata
        """
        inspection = getfullargspec(self.get_snapshots)
        validate_by_type_hints(inspection=inspection, func_params=locals())

        self._atconn._check_connected(
            err_msg="Establishing a connection in the atconn field is required"
        )

        # returns the snapshot ids of this project
        url = endpoints._endpoint_design_org(
            self._atconn, f"/project/{self.draft_project_id}/snapshots"
        )

        request_resp = self._atconn._submit_request(request_type=RequestType.GET, url=url).text
        response = json.loads(request_resp)["response"]
        if not response:
            return []

        snapshot_list = []
        for i in response:
            if snapshot_name and i["name"] != snapshot_name:
                continue
            id_dict = {"name": i["name"], "id": i["snapshot_id"], "create_date": i["create_date"]}
            snapshot_list.append(id_dict)

        if snapshot_name and len(snapshot_list) > 1:
            logger.warning(
                f"Multiple snapshots with the name {snapshot_name} found, consider renaming one to reduce ambiguity."
            )
        return snapshot_list

    def delete_dataset(
        self,
        dataset_name: str,
        publish: bool = True,
        delete_children: bool = None,
    ) -> None:
        """Deletes any dataset with the given name, case-sensitive from all data models. Also deletes measures built from
        the dataset. If any calculated measures are defined using the deleted features, the user will be prompted yes
        or no to delete each one and if the response is no, the function will abort with no changes made.

        Args:
            dataset_name (str): The dataset name which will be matched to the datasets to delete in the
                project json
            publish (bool): Defaults to True, whether the updated project should be published
            delete_children (bool): Defaults to None to prompt for every calculated_measure dependent on measures
                from the dataset. Setting this parameter to True or False simulates inputting 'y' or 'n',
                respectively, for all prompts.

        Raises:
            atscale_errors.UserError: if there is no dataset with the given name
        """
        logger.warn(
            "Deleting datasets  involved with degnerate dimensions can have unexpected behaviors. If such an error occurs, please resolve your deletion in the Design Canvas"
        )
        from atscale.parsers import data_model_parser

        inspection = getfullargspec(self.delete_dataset)
        validate_by_type_hints(inspection=inspection, func_params=locals())

        # Delete library (project level) datasets
        temp_json = deepcopy(self._get_dict())
        dataset_list = project_parser.get_datasets(temp_json)
        ds_id: str = ""
        new_dataset_list = []
        for dataset in dataset_list:
            if dataset["name"] != dataset_name:
                new_dataset_list.append(dataset)
            else:
                ds_id = dataset["id"]
        if not ds_id:
            raise atscale_errors.UserError(f"No dataset with name {dataset_name} found in project")
        temp_json["datasets"]["data-set"] = new_dataset_list

        # Delete dataset from data model and find measures to delete
        features_to_delete = []
        for index, cube in enumerate(project_parser.get_cubes(project_dict=temp_json)):
            cube_datasets = data_model_parser._get_dataset_refs(cube_dict=cube)
            new_cube_datasets = []
            for ds in cube_datasets:
                if ds["id"] != ds_id:
                    new_cube_datasets.append(ds)
                else:
                    features_to_delete += data_model_parser.attributes_derived_from_ds(
                        cube=cube, dataset=ds
                    )
            cube["data-sets"]["data-set-ref"] = new_cube_datasets
            if features_to_delete:
                if delete_children is None:
                    delete_children = input_utils.prompt_yes_no(
                        "The following features, and any calculated measures referencing them in their "
                        "definition, need to be deleted in order to delete the given dataset. Would you like to "
                        f"delete the dependent features, answering no will abort the dataset deletion. "
                        f"Dependent features: {features_to_delete}. "
                    )
                elif delete_children is not True and delete_children is not False:
                    raise atscale_errors.UserError(
                        "the delete_children parameter must be None, False, or True and nothing else"
                    )
                if delete_children:
                    from atscale.data_model.data_model import DataModel
                    from atscale.utils import feature_utils

                    feature_utils._delete_measures(
                        data_model=DataModel(cube["id"], self),
                        json_dict=temp_json,
                        measure_list=features_to_delete,
                        delete_children=delete_children,
                    )
                else:
                    raise atscale_errors.DependentMeasureException(
                        f"The following measures were protected, so the deletion was aborted: {features_to_delete}"
                    )
        self._update_project(project_json=temp_json, publish=publish)

    def _assert_published_project_id_not_none(
        self,
        method: str = None,
    ):
        method_name = "is" if method is None else f"e {method}"
        if self.__published_project_id is None:
            raise atscale_errors.UserError(
                f"The project needs to be published before calling th{method_name} method"
            )

    def get_data_models(self) -> List[Dict[str, str]]:
        """Prints all Data Models that are visible for the associated Project. Returns a list of dicts
            for each of the listed Projects. List index should match printed index.

        Returns:
            List[Dict[str,str]]: List of 'id':'name' pairs of available Data Models.
        """

        data_model_dict_list = project_parser.get_data_models(self._get_dict())

        print("Note: Data Model ID is expected in Data Model constructor.")
        for i, dct in enumerate(data_model_dict_list):
            print(f"Index:{i} ID: {dct['id']}: Name: {dct['name']}")

        return data_model_dict_list

    def get_connected_warehouse(self):
        """Returns the warehouse id utilized in this project

        Returns:
            str: the warehouse id
        """
        return project_parser.get_project_warehouse(self._get_dict())

    def create_data_model(
        self,
        query_name: str,
        caption: str = "",
        description: str = "",
        publish: bool = True,
    ):
        """Creates a new empty DataModel in the current project and sets the name to the given query_name.

        Args:
            query_name (str): The query name for the newly cloned model.
            caption (str, optional): The caption of the model. Defaults to "" to leave the same as the query_name.
            description (str, optional): The description of the model. Defaults to "".
            publish (bool, optional): Whether to publish the project after creating the new model. Defaults to True.

        Returns:
            DataModel: The DataModel object for the new model.
        """
        from atscale.data_model import DataModel

        inspection = getfullargspec(self.create_data_model)
        validate_by_type_hints(inspection=inspection, func_params=locals())

        project_dict = self._get_dict()
        cubes = project_parser.get_cubes(project_dict)
        for cube in cubes:
            if cube.get("name") == query_name:
                raise atscale_errors.UserError(
                    f"There is already a data model in the project with the query name: {query_name}"
                )
        new_cube = create_cube_dict(query_name, caption, description)
        cubes.append(new_cube)
        project_dict["cubes"]["cube"] = cubes
        self._update_project(project_dict, publish)
        return DataModel(new_cube["id"], self)
