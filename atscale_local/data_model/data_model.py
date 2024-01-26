import inspect
import logging
import json
import pandas as pd
from typing import Callable, List, Dict, Union, Any, Tuple

from atscale.errors import atscale_errors
from atscale.db.sql_connection import SQLConnection
from atscale.parsers import (
    data_model_parser,
    project_parser,
    dictionary_parser,
    dataset_parser as dsp,
)
from atscale.project.project import Project
from atscale.utils import model_utils, metadata_utils, project_utils, input_utils, db_utils
from atscale.utils import request_utils, dimension_utils, feature_utils, query_utils
from atscale.utils import validation_utils, bulk_operator_utils
from atscale.utils.dmv_utils import get_dmv_data
from atscale.base import endpoints
from atscale.base.enums import PandasTableExistsActionType, PysparkTableExistsActionType, Level
from atscale.base.enums import Hierarchy, FeatureType, MappedColumnDataTypes, TimeSteps
from atscale.base.enums import FeatureFormattingType, Aggs, MDXAggs, RequestType
from atscale.base.enums import (
    MappedColumnKeyTerminator,
    MappedColumnFieldTerminator,
    CheckFeaturesErrMsg,
)
from inspect import getfullargspec
from atscale.utils.validation_utils import validate_by_type_hints
from atscale.data_model import data_model_helpers

logger = logging.getLogger(__name__)


class DataModel:
    """Creates an object corresponding to an AtScale Data Model. Takes an existing model id and
    AtScale Project object to construct an object that deals with functionality related to model level
    datasets and columns, as well as reading data and writing back predictions.
    """

    def __init__(
        self,
        data_model_id: str,
        project: Project,
    ):
        """A Data Model is an abstraction that represents a perspective or cube within AtScale.

        Args:
            data_model_id (str): the unique identifier of the model in question
            project (Project): the AtScale Project object the model is a part of
        """
        inspection = getfullargspec(self.__init__)
        validate_by_type_hints(inspection=inspection, func_params=locals())

        self.__id = data_model_id
        self.project = project

    @property
    def id(self) -> str:
        """Getter for the id instance variable

        Returns:
            str: The id of this model
        """
        return self.__id

    @id.setter
    def id(
        self,
        value,
    ):
        """Setter for the id instance variable. This variable is final, please construct a new DataModel.

        Args:
            value: setter cannot be used.

        Raises:
            Exception: Raises a value if the setter is attempted.
        """
        raise atscale_errors.UnsupportedOperationException(
            "The value of data_model_id is final; it cannot be altered."
        )

    @property
    def cube_id(self) -> str:
        """Getter for the id of the source cube. If the DataModel is a perspective this will
            return the reference id for the source cube.

        Returns:
            str: The id of the source cube.
        """
        return self.__cube_ref if self.is_perspective() else self.__id

    @property
    def name(self) -> str:
        """Getter for the name instance variable. The name of the data model.

        Returns:
            str: The textual identifier for the data model.
        """
        return self.__name

    @name.setter
    def name(
        self,
        value,
    ):
        """Setter for the name instance variable. This variable is final, please construct a new DataModel.

        Args:
            value: setter cannot be used.

        Raises:
            Exception: Raises a value if the setter is attempted.
        """
        raise atscale_errors.UnsupportedOperationException(
            "The value of data_model_id is final; it cannot be altered."
        )

    @property
    def project(self) -> Project:
        """Getter for the Project instance variable.

        Returns:
            Project: The Project object this model belongs to.
        """
        return self.__project

    @project.setter
    def project(
        self,
        value: Project,
    ):
        """Setter for Project instance variable.

        Args:
            value (Project): The new project to associate the model with.

        Raises:
            ValueError: If the new Project is not associated with the DataModel.
        """
        if value is None:
            raise ValueError("The provided value is None.")
        if not isinstance(value, Project):
            raise ValueError("The provided value is not a Project.")
        project_dict = value._get_dict()
        data_model_dict = project_parser.get_data_model(project_dict, self.__id)
        if not data_model_dict:
            raise ValueError("The provided Project is not associated with this DataModel.")
        self.__project = value
        # If data_model_dict is a cube, then it will have no cube-ref key, and __cube_ref will be set to None, which is valid.
        # If data_model_dict is a perspective, then it will have the key,  and cube_ref will be set.
        self.__cube_ref = data_model_dict.get("cube-ref")
        self.__name = data_model_dict.get("name")

    def get_features(
        self,
        feature_list: List[str] = None,
        folder_list: List[str] = None,
        feature_type: FeatureType = FeatureType.ALL,
        use_published: bool = True,
    ) -> dict:
        """Gets the feature names and metadata for each feature in the published DataModel.

        Args:
            feature_list (List[str], optional): A list of feature query names to return. Defaults to None to return all. All
                features in this list must exist in the model.
            folder_list (List[str], optional): A list of folders to filter by. Defaults to None to ignore folder.
            feature_type (FeatureType, optional): The type of features to filter by. Options
                include FeatureType.ALL, FeatureType.CATEGORICAL, or FeatureType.NUMERIC. Defaults to ALL.
            use_published (bool, optional): whether to get the features of the published or draft data model.
                Defaults to True to use the published version.

        Returns:
            dict: A dictionary of dictionaries where the feature names are the keys in the outer dictionary
                  while the inner keys are the following: 'data_type'(value is a level-type, 'Aggregate', or 'Calculated'),
                  'description', 'expression', caption, 'folder', and 'feature_type'(value is Numeric or Categorical).
        """
        inspection = getfullargspec(self.get_features)
        validate_by_type_hints(inspection=inspection, func_params=locals())

        if use_published:
            ret_dict = data_model_helpers._get_published_features(
                self, feature_list=feature_list, folder_list=folder_list, feature_type=feature_type
            )
        else:
            model_utils._perspective_check(
                self, "Getting draft features is not supported for perspectives."
            )

            project_dict = self.project._get_dict()
            ret_dict = data_model_helpers._get_draft_features(
                project_dict,
                data_model_name=self.name,
                feature_list=feature_list,
                folder_list=folder_list,
                feature_type=feature_type,
            )

            # remove non-queryable features
            # to_del = []
            # for key, val in ret_dict.items():
            #    if not val.get("queryable", True):
            #        to_del.append(key)
            # for key in to_del:
            #    del ret_dict[key]

            for item in ret_dict.values():
                item.pop("roleplay_ref_id", None)
                # item.pop("queryable", None)

        # Added this gate to account for cases where feature_list is not specified
        if feature_list:
            model_utils._check_features(
                features=feature_list,
                check_list=ret_dict,
                errmsg=CheckFeaturesErrMsg.ALL.get_errmsg(is_published=use_published),
            )

        return ret_dict

    def is_perspective(self) -> bool:
        """Checks if this DataModel is a perspective

        Returns:
            bool: true if this is a perspective
        """
        if self.__cube_ref:
            return True
        else:
            return False

    def _get_referenced_project_datasets(self) -> List[dict]:
        """Returns a list of all project datasets referenced by this model, but not ones referenced by a dimension. In
        other words, this returns all fact datasets that exist in this model.

        Returns:
            list[dict]: list of all project datasets referenced by this model
        """
        project_dict = self.__project._get_dict()
        data_model_dict = model_utils._get_model_dict(self, project_dict=project_dict)[0]
        return model_utils._get_fact_datasets(
            data_model_dict=data_model_dict, project_dict=project_dict
        )

    def get_fact_dataset_names(self) -> List[str]:
        """Gets the name of all fact datasets currently utilized by the DataModel and returns as a list.

        Returns:
            List[str]: list of fact dataset names
        """
        project_dict = self.__project._get_dict()
        data_model_dict = model_utils._get_model_dict(self, project_dict=project_dict)[0]
        return [
            ds["name"]
            for ds in model_utils._get_fact_datasets(
                data_model_dict=data_model_dict, project_dict=project_dict
            )
        ]

    def get_dimension_dataset_names(
        self,
    ) -> List[str]:
        """Gets the name of all dimension datasets currently utilized by the DataModel and returns as a list.

        Returns:
            List[str]: list of dimension dataset names
        """
        project_dict = self.__project._get_dict()
        return [ds["name"] for ds in model_utils._get_dimension_datasets(self, project_dict)]

    def get_dataset_names(self, include_unused: bool = False) -> List[str]:
        """Gets the name of all datasets currently utilized by the DataModel and returns as a list.

        Args:
            include_unused (bool, optional): Also return the names of datasets in the project library,
                even if they are not used in the model. Defaults to False to only list datasets used in the model.

        Returns:
            List[str]: list of dataset names
        """
        inspection = getfullargspec(self.get_dataset_names)
        validate_by_type_hints(inspection=inspection, func_params=locals())

        project_dict = self.__project._get_dict()
        if include_unused:
            datasets = project_parser.get_datasets(project_dict=project_dict)
        else:
            data_model_dict = model_utils._get_model_dict(self, project_dict=project_dict)[0]
            fact_dsets = model_utils._get_fact_datasets(data_model_dict, project_dict)
            dimension_dsets = model_utils._get_dimension_datasets(self, project_dict)
            datasets = fact_dsets + dimension_dsets
        names = {dset["name"] for dset in datasets}
        return sorted(list(names))

    def get_dataset(self, dataset_name: str) -> str:
        """Gets the metadata of a dataset.

        Args:
            dataset_name (str): The name of the dataset to pull.

        Returns:
            dict: A dictionary of the metadata for the dataset.
        """
        inspection = getfullargspec(self.get_dataset)
        validate_by_type_hints(inspection=inspection, func_params=locals())

        project_dict = self.__project._get_dict()
        dataset = project_parser.get_dataset(project_dict=project_dict, dataset_name=dataset_name)

        if not dataset:
            raise atscale_errors.UserError(f"Dataset: '{dataset_name}' not found.")

        data_model_dict = model_utils._get_model_dict(self, project_dict=project_dict)[0]
        fact_dsets = [
            ds["name"]
            for ds in model_utils._get_fact_datasets(
                data_model_dict=data_model_dict, project_dict=project_dict
            )
            if ds["name"] == dataset_name
        ]
        dimension_dsets = [
            ds["name"]
            for ds in model_utils._get_dimension_datasets(self, project_dict)
            if ds["name"] == dataset_name
        ]

        ret_dict = {
            "name": dataset["name"],
            "used_in_fact": len(fact_dsets) > 0,
            "used_in_dimension": len(dimension_dsets) > 0,
            "allow_aggregates": dataset["properties"]["allow-aggregates"],
            "warehouse_id": dataset["physical"]["connection"]["id"],
            "columns": [],
        }
        if dataset["physical"].get("queries"):
            ret_dict["sql_expression"] = dataset["physical"]["queries"][0]["sqls"][0]["expression"]
        elif dataset["physical"].get("tables"):
            ret_dict["table_name"] = dataset["physical"]["tables"][0].get("name", "")
            ret_dict["schema"] = dataset["physical"]["tables"][0].get("schema", "")
            ret_dict["database"] = dataset["physical"]["tables"][0].get("database", "")
        for column in dataset["physical"]["columns"]:
            column_dict = {"column_name": column["name"], "data_type": column["type"]["data-type"]}
            if column.get("sqls"):
                column_dict["expression"] = column["sqls"][0]["expression"]
            ret_dict["columns"].append(column_dict)
        return ret_dict

    def dataset_exists(self, dataset_name: str, include_unused: bool = False) -> bool:
        """Returns whether a given dataset_name exists in the data model, case-sensitive.

        Args:
            dataset_name (str): the name of the dataset to try and find
            include_unused (bool, optional): Also return the names of datasets in the project library,
                even if they are not used in the model. Defaults to False to only list datasets used in the model.


        Returns:
            bool: true if name found, else false.
        """
        inspection = getfullargspec(self.dataset_exists)
        validate_by_type_hints(inspection=inspection, func_params=locals())

        return dataset_name in self.get_dataset_names(include_unused=include_unused)

    def get_columns(
        self,
        dataset_name: str,
    ) -> dict:
        """Gets all currently visible columns in a given dataset, case-sensitive.

        Args:
            dataset_name (str): the name of the dataset to get columns from, case-sensitive.

        Returns:
            dict: the columns in the given dataset
        """
        inspection = getfullargspec(self.get_columns)
        validate_by_type_hints(inspection=inspection, func_params=locals())

        project_dict = self.__project._get_dict()
        if not self.dataset_exists(dataset_name, include_unused=True):
            raise atscale_errors.UserError(f"Dataset: '{dataset_name}' not found.")

        return model_utils._get_columns(project_dict, dataset_name=dataset_name)

    def column_exists(
        self,
        dataset_name: str,
        column_name: str,
    ) -> bool:
        """Checks if the given column name exists in the dataset.

        Args:
            dataset_name (str): the name of the dataset we pull the columns from, case-sensitive.
            column_name (str): the name of the column to check, case-sensitive

        Returns:
            bool: true if name found, else false.
        """
        inspection = getfullargspec(self.column_exists)
        validate_by_type_hints(inspection=inspection, func_params=locals())

        project_dict = self.__project._get_dict()

        if not self.dataset_exists(dataset_name, include_unused=True):
            raise atscale_errors.UserError(f"Dataset: '{dataset_name}' not found.")

        return model_utils._column_exists(
            project_dict, dataset_name=dataset_name, column_name=column_name
        )

    def delete_measures(
        self,
        measure_list: List[str],
        publish: bool = True,
        delete_children: bool = None,
    ):
        """Deletes a list of measures from the DataModel. If a measure is referenced in any calculated measures,
         and delete_children is not set, then the user will be prompted with a list of children measures and given the
         choice to delete them or abort.

        Args:
            measure_list (List[str]): the query names of the measures to be deleted
            publish (bool, optional): Defaults to True, whether the updated project should be published
            delete_children (bool, optional): Defaults to None, if set to True or False no prompt will be given in the case of
                any other measures being derived from the given measure_name. Instead, these measures will also be deleted when
                delete_children is True, alternatively, if False, the method will be aborted with no changes to the data model

        Raises:
            DependentMeasureException: if child measures are encountered and the method is aborted
            atscale_errors.UserError: if a measure_name is not found in the data model"""
        model_utils._perspective_check(
            self, "Delete operations are not supported for perspectives."
        )

        inspection = getfullargspec(self.delete_measures)
        validate_by_type_hints(inspection=inspection, func_params=locals())

        json_dict = self.project._get_dict()
        existing = data_model_helpers._get_draft_features(
            project_dict=json_dict, data_model_name=self.name, feature_type=FeatureType.NUMERIC
        )
        model_utils._check_features(
            features=measure_list,
            check_list=existing,
            errmsg=CheckFeaturesErrMsg.NUMERIC.get_errmsg(is_published=False),
        )
        feature_utils._delete_measures(
            data_model=self,
            measure_list=measure_list,
            json_dict=json_dict,
            delete_children=delete_children,
        )
        self.project._update_project(project_json=json_dict, publish=publish)

    def add_query_dataset(
        self,
        dataset_name: str,
        query: str,
        warehouse_id: str = None,
        join_features: List[str] = None,
        join_columns: List[str] = None,
        roleplay_features: List[str] = None,
        publish: bool = True,
        if_exists: PandasTableExistsActionType = PandasTableExistsActionType.FAIL,
        force_replace: bool = False,
        delete_children: bool = None,
        allow_aggregates: bool = True,
        create_hinted_aggregate: bool = False,
    ):
        """Creates a new Query Dataset in this data model which provides results of executing the given query against
        the warehouse of given warehouse_id or the warehouse associated with the data model if warehouse_id is not
        passed.

        Args:
            dataset_name (str): The display and query name of the dataset
            query (str): A valid SQL expression with which to directly query the warehouse of the given warehouse_id.
            warehouse_id (str, optional): The warehouse id of the warehouse this qds and its data model are pointing at.
                Defaults to None to use the warehouse_id of existing datasets in the model.
            join_features (list, optional): a list of feature query names in the data model to use for joining. If None it will not
                join the qds to anything. Defaults to None.
            join_columns (list, optional): The column names in the dataset to join to the join_features. List must be either
                None or the same length and order as join_features. Defaults to None to use identical names to the
                join_features. If multiple columns are needed for a single join they should be in a nested list
            roleplay_features (list, optional): The roleplays to use on the relationships. List must be either
                None or the same length and order as join_features. Use '' to not roleplay that relationship. Defaults to None.
            publish (bool, optional): Whether or not the updated project should be published. Defaults to True.
            if_exists (PandasTableExistsActionType, optional): What to do if a table with table_name already exists. Defaults to PandasTableExistsActionType.FAIL.
            force_replace (bool, optional): When if_exists = REPLACE and this is true, does not prompt. Defaults to False.
            delete_children (bool, optional): Whether dependent features of a dataset should be deleted in the case when
                a dataset already exists and is being replaced. Defaults to None to prompt for input upon this scenario.
            allow_aggregates(bool, optional): Whether to allow aggregates to be built off of this QDS. Defaults to True.
            create_hinted_aggregate(bool, optional): Whether to generate an aggregate table for all measures and keys in this QDS to improve join performance. Defaults to False.
        """
        logger.warn(
            "The function add_query_dataset is will be deprecated in version 2.6, please use DataModel.create_dataset instead. "
        )
        model_utils._perspective_check(self)
        inspection = getfullargspec(self.add_query_dataset)
        validate_by_type_hints(inspection=inspection, func_params=locals())

        project_dict = self.project._get_dict()

        warehouse_id = validation_utils._validate_warehouse_id_parameter(
            atconn=self.project._atconn, project_dict=project_dict, warehouse_id=warehouse_id
        )

        # check if there is an existing dataset with the given name
        existing_dset = project_parser.get_dataset(
            project_dict=project_dict, dataset_name=dataset_name
        )
        # if there was a found dataset, respond based on if_exists parameter.
        if existing_dset:
            if if_exists == PandasTableExistsActionType.FAIL:
                raise ValueError(f"A dataset already exists with the name {dataset_name}")
            elif if_exists == PandasTableExistsActionType.APPEND:
                raise atscale_errors.UnsupportedOperationException(
                    f"Appending to a query dataset is not currently supported."
                )
            else:
                if force_replace == True:
                    delete = True
                else:
                    delete = input_utils.prompt_yes_no(
                        question=f"Dataset {dataset_name} already exists in the project,"
                        f"would you like to replace it? This will delete any "
                        f"previous usages in any model in this project."
                    )
                if not delete:
                    raise ValueError(
                        f"A dataset already exists with the name {dataset_name} and QDS "
                        f"creation has been aborted to protect it."
                    )
                self.project.delete_dataset(
                    dataset_name=dataset_name, delete_children=delete_children, publish=False
                )  # will prompt if it used in any dimensions or measures
                # get fresh dict after deleting dataset
                project_dict = self.project._get_dict()

        # check to see that features are in the data model and can join
        columns = self.project._atconn._get_query_columns(warehouse_id=warehouse_id, query=query)
        column_names = {col[0] for col in columns}
        join_features, join_columns, roleplay_features, _ = data_model_helpers._check_joins(
            project_dict=project_dict,
            cube_id=self.cube_id,
            join_features=join_features,
            join_columns=join_columns,
            roleplay_features=roleplay_features,
            column_set=column_names,
        )
        qds_dict = project_utils._create_query_dataset(
            name=dataset_name,
            query=query,
            columns=columns,
            warehouse_id=warehouse_id,
            allow_aggregates=allow_aggregates,
        )
        project_utils.add_dataset(project_dict=project_dict, dataset=qds_dict)

        # now add ref to data model
        model_utils._create_dataset_relationship_from_dataset(
            project_dict=project_dict,
            cube_id=self.cube_id,
            dataset_name=dataset_name,
            join_features=join_features,
            join_columns=join_columns,
            roleplay_features=roleplay_features,
            allow_aggregates=allow_aggregates,
            create_hinted_aggregate=create_hinted_aggregate,
        )

        self.project._update_project(project_json=project_dict, publish=publish)

    def update_dataset(
        self,
        dataset_name: str,
        allow_aggregates: bool = None,
        create_hinted_aggregate: bool = None,
        publish: bool = True,
    ):
        """Updates aggregate settings for an existing Dataset in the data model.

        Args:
            dataset_name (str): The display and query name of the dataset to edit
            allow_aggregates(bool, optional): The new setting for if aggregates are allowed to be built off of this QDS. Defaults to None for no update.
            create_hinted_aggregate(bool, optional): The setting for if an aggregate table is generated for all measures and keys in this QDS. Defaults to None for no update.
            publish (bool, optional): Whether or not the updated project should be published. Defaults to True.
        """
        model_utils._perspective_check(self)

        # validate the non-null inputs
        validation_utils.validate_required_params_not_none(
            local_vars=locals(),
            inspection=inspect.getfullargspec(self.update_dataset),
        )

        project_dict = self.project._get_dict()

        dset = project_parser.get_dataset(project_dict=project_dict, dataset_name=dataset_name)
        if not dset:
            raise atscale_errors.UserError(
                f"Invalid parameter: dataset name '{dataset_name}' does not exist"
            )
        if (not project_utils._check_if_qds(dset)) and create_hinted_aggregate is not None:
            raise atscale_errors.UserError(
                f"Invalid parameter: create_hinted_aggregate is only available for qds datasets and '{dataset_name}' is not a qds"
            )

        project_utils._update_dataset(
            project_dict=project_dict,
            dataset_name=dataset_name,
            cube_id=self.cube_id,
            allow_aggregates=allow_aggregates,
            create_hinted_aggregate=create_hinted_aggregate,
        )

        self.project._update_project(project_json=project_dict, publish=publish)

    def create_dataset(
        self,
        dataset_name: str,
        table_name: str = None,
        database: str = None,
        schema: str = None,
        query: str = None,
        warehouse_id: str = None,
        allow_aggregates: bool = True,
        create_hinted_aggregate: bool = False,
        publish: bool = True,
    ):
        """Creates a dataset in the data model.

        Args:
            dataset_name (str): The display and query name of the dataset to edit
            table_name (str, optional): The name of the table to use. Defaults to None to use a query.
            database (str, optional): The database of the table to use. Defaults to None to use a query.
            schema(str, optional): The schema of the table to use. Defaults to None to use a query.
            query(str, optional): The sql query if creating a query dataset. Defaults to None to use a table.
            warehouse_id(str, optional): The warehouse to associate the dataset with. Defaults to None to infer from the model.
            allow_aggregates(bool, optional): The new setting for if aggregates are allowed to be built off of this dataset. Defaults to True.
            create_hinted_aggregate(bool, optional): The setting for if an aggregate table is generated for all measures and keys if this is a QDS. Defaults to False.
            publish (bool, optional): Whether or not the updated project should be published. Defaults to True.
        """
        model_utils._perspective_check(self)

        inspection = getfullargspec(self.create_dataset)
        validate_by_type_hints(inspection=inspection, func_params=locals())

        project_dict = self.project._get_dict()

        # check if there is an existing dataset with the given name
        existing_dset = project_parser.get_dataset(
            project_dict=project_dict, dataset_name=dataset_name
        )
        # if there was a found dataset, respond based on if_exists parameter.
        if existing_dset:
            raise ValueError(f"A dataset already exists with the name {dataset_name}")

        warehouse_id = validation_utils._validate_warehouse_id_parameter(
            atconn=self.project._atconn, project_dict=project_dict, warehouse_id=warehouse_id
        )
        if not query:
            create_hinted_aggregate = False
            columns = self.project._atconn._get_table_columns(
                warehouse_id=warehouse_id,
                table_name=table_name,
                database=database,
                schema=schema,
            )
            project_dataset, dataset_id = project_utils.create_dataset(
                table_name,
                warehouse_id,
                columns,
                database,
                schema,
                dataset_name=dataset_name,
                allow_aggregates=allow_aggregates,
            )
        else:
            columns = self.project._atconn._get_query_columns(
                warehouse_id=warehouse_id, query=query
            )
            column_names = {col[0] for col in columns}
            project_dataset = project_utils._create_query_dataset(
                name=dataset_name,
                query=query,
                columns=column_names,
                warehouse_id=warehouse_id,
                allow_aggregates=allow_aggregates,
            )
            dataset_id = project_dataset["id"]

        project_utils.add_dataset(project_dict, project_dataset)
        model_dict = model_utils._get_model_dict(self, project_dict)[0]
        model_utils._add_data_set_ref(
            model_dict,
            dataset_id,
            allow_aggregates=allow_aggregates,
            create_hinted_aggregate=create_hinted_aggregate,
        )
        self.project._update_project(project_json=project_dict, publish=publish)

    def write_feature_importance(
        self,
        dbconn: SQLConnection,
        table_name: str,
        dataframe: pd.DataFrame,
        feature_name_prefix: str,
        folder: str = None,
        publish: bool = True,
        if_exists: PandasTableExistsActionType = PandasTableExistsActionType.FAIL,
        warehouse_id: str = None,
    ):
        """Writes the dataframe with columns containing feature query names and their importances to a table in the database accessed by dbconn with the given table_name.
        Then builds the created table into the data model so the importances can be queried.

        Args:
            dbconn (SQLConnection): connection to the database; should be the same one the model and project are based on
            table_name (str): the name for the table to be created for the given DataFrame
            dataframe (pd.DataFrame): the pandas DataFrame to write to the database
            feature_name_prefix (str): string to prepend to new feature query names to make them easily identifiable
            folder (str): The folder to put the newly created items in. Defaults to None.
            publish (bool, optional): Whether or not the updated project should be published. Defaults to True.
            if_exists (PandasTableExistsActionType, optional): What to do if a table with table_name already exists. Defaults to PandasTableExistsActionType.FAIL.
            warehouse_id (str, optional): The id of the warehouse at which the data model and this dataset point.
                Defaults to None to use the warehouse_id of existing datasets in the model.
        """
        model_utils._perspective_check(self)

        inspection = getfullargspec(self.write_feature_importance)
        validate_by_type_hints(inspection=inspection, func_params=locals())

        project_dict = self.project._get_dict()
        # verify our sql_connection is pointed at a connection that the model points at, and we'll use
        # that info later for join tables
        validation_utils._validate_warehouse_connection(
            atconn=self.project._atconn, project_dict=project_dict, dbconn=dbconn
        )
        warehouse_id = validation_utils._validate_warehouse_id_parameter(
            atconn=self.project._atconn,
            project_dict=project_dict,
            warehouse_id=warehouse_id,
            dbconn_warehouse_id=dbconn.warehouse_id,
        )

        # write the feature importance table to the db
        dbconn.write_df_to_db(table_name=table_name, dataframe=dataframe, if_exists=if_exists)

        if if_exists == PandasTableExistsActionType.REPLACE:
            database, schema = db_utils.get_database_and_schema(dbconn=dbconn)
            atscale_table_name = db_utils.get_atscale_tablename(
                atconn=self.project._atconn,
                warehouse_id=warehouse_id,
                database=database,
                schema=schema,
                table_name=table_name,
            )
            # If we're replacing a table, then the columns may have changed and the data sets need to be updated.
            self.project._update_project_tables(
                tables=[atscale_table_name],
                publish=False,
                project_dict=project_dict,
                update_project=False,
            )

        columns, atscale_table_name, schema, database = data_model_helpers._get_atscale_names(
            atconn=self.project._atconn,
            warehouse_id=warehouse_id,
            table_name=table_name,
            dbconn=dbconn,
            expected_columns=dataframe.columns,  # will warn if aliased
            include_dtype=True,  # columns will be tuples
        )

        # map the dataframe column names to atscale column names
        column_dict = db_utils.get_column_dict(
            atconn=self.project._atconn,
            dbconn=dbconn,
            warehouse_id=warehouse_id,
            atscale_table_name=atscale_table_name,
            dataframe_columns=dataframe.columns,
        )
        # create a dataset for the new table
        columns = self.project._atconn._get_table_columns(
            warehouse_id=warehouse_id,
            table_name=atscale_table_name,
            database=database,
            schema=schema,
            expected_columns=dataframe.columns,
        )
        # create a dataset for the new table
        project_dataset, dataset_id = project_utils.create_dataset(
            atscale_table_name, warehouse_id, columns, database, schema
        )

        # add the dataset into the project dict as well as creates features
        project_utils.add_dataset(project_dict, project_dataset)
        model_dict = model_utils._get_model_dict(self, project_dict)[0]
        model_utils._add_data_set_ref(model_dict, dataset_id)
        for column in dataframe.columns:
            name = column_dict[column]
            if dataframe[column].dtype.kind in "iufc":
                feature_utils._create_aggregate_feature(
                    project_dict=project_dict,
                    cube_id=self.cube_id,
                    dataset_id=dataset_id,
                    column_name=name,
                    new_feature_name=feature_name_prefix + "_feature_importance_" + column,
                    folder=folder,
                    aggregation_type=Aggs.SUM,
                )
            else:
                dimension_utils.create_categorical_dimension_for_column(
                    project_dict=project_dict,
                    cube_id=self.cube_id,
                    dataset_id=dataset_id,
                    column_name=name,
                    base_name=feature_name_prefix + "_feature_name",
                    folder=folder,
                )

        self.project._update_project(project_json=project_dict, publish=publish)

    def writeback(
        self,
        dbconn: SQLConnection,
        table_name: str,
        dataframe: pd.DataFrame,
        join_features: list,
        join_columns: list = None,
        roleplay_features: list = None,
        publish: bool = True,
        if_exists: PandasTableExistsActionType = PandasTableExistsActionType.FAIL,
        warehouse_id: str = None,
    ):
        """Writes the dataframe to a table in the database accessed by dbconn with the given table_name. Joins that table to this
        DataModel by joining on the given join_features or join_columns.

        Args:
            dbconn (SQLConnection): connection to the database; should be the same one the model and project are based on
            table_name (str): the name for the table to be created for the given DataFrame
            dataframe (pd.DataFrame): the pandas DataFrame to write to the database
            join_features (list): a list of feature query names in the data model to use for joining.
            join_columns (list, optional): The column names in the dataframe to join to the join_features. List must be either
                None or the same length and order as join_features. Defaults to None to use identical names to the
                join_features. If multiple columns are needed for a single join they should be in a nested list
            roleplay_features (list, optional): The roleplays to use on the relationships. List must be either
                None or the same length and order as join_features. Use '' to not roleplay that relationship. Defaults to None.
            publish (bool, optional): Whether or not the updated project should be published. Defaults to True.
            if_exists (PandasTableExistsActionType, optional): What to do if a table with table_name already exists. Defaults to PandasTableExistsActionType.FAIL.
            warehouse_id (str, optional): The id of the warehouse at which the data model and this dataset point.
                Defaults to None to use the warehouse_id of existing datasets in the model.

        """
        model_utils._perspective_check(self)

        inspection = getfullargspec(self.writeback)
        validate_by_type_hints(inspection=inspection, func_params=locals())

        project_dict = self.project._get_dict()
        # verify our sql_connection is pointed at a connection that the model points at, and we'll use
        # that info later for join tables
        validation_utils._validate_warehouse_connection(
            atconn=self.project._atconn, project_dict=project_dict, dbconn=dbconn
        )
        warehouse_id = validation_utils._validate_warehouse_id_parameter(
            atconn=self.project._atconn,
            project_dict=project_dict,
            warehouse_id=warehouse_id,
            dbconn_warehouse_id=dbconn.warehouse_id,
        )

        join_features, join_columns, roleplay_features, dataframe = data_model_helpers._check_joins(
            project_dict=project_dict,
            cube_id=self.cube_id,
            join_features=join_features,
            join_columns=join_columns,
            roleplay_features=roleplay_features,
            column_set=dataframe.columns,
            dbconn=dbconn,
            df=dataframe,
        )

        dbconn.write_df_to_db(table_name=table_name, dataframe=dataframe, if_exists=if_exists)

        # If we're replacing a table, then the columns may have changed and the data sets need to be updated.
        if if_exists == PandasTableExistsActionType.REPLACE:
            database, schema = db_utils.get_database_and_schema(dbconn=dbconn)
            atscale_table_name = db_utils.get_atscale_tablename(
                atconn=self.project._atconn,
                warehouse_id=warehouse_id,
                database=database,
                schema=schema,
                table_name=table_name,
            )
            self.project._update_project_tables(
                tables=[atscale_table_name],
                publish=False,
                project_dict=project_dict,
                update_project=False,
            )

        (
            atscale_columns,
            atscale_table_name,
            schema,
            database,
        ) = data_model_helpers._get_atscale_names(
            atconn=self.project._atconn,
            warehouse_id=warehouse_id,
            dbconn=dbconn,
            table_name=table_name,
            expected_columns=dataframe.columns,
            include_dtype=True,  # avoids get_table_columns() call in _create_dataset_relationship
        )

        aliases = {c[0] for c in atscale_columns}
        join_columns: List[List[str]] = data_model_helpers._prep_join_columns_for_join(
            join_columns=join_columns,
            atscale_columns=aliases,
        )

        # create_dataset_relationship now mutates the project_json and returns, then we're responsible for posting
        project_dict = model_utils._create_dataset_relationship(
            atconn=self.project._atconn,
            project_dict=project_dict,
            cube_id=self.cube_id,
            database=database,
            schema=schema,
            table_name=atscale_table_name,
            join_features=join_features,
            join_columns=join_columns,
            roleplay_features=roleplay_features,
            table_columns=atscale_columns,
            warehouse_id=warehouse_id,
        )

        self.project._update_project(project_json=project_dict, publish=publish)

    def add_table(
        self,
        table_name: str,
        schema: str,
        database: str,
        join_features: List[str] = None,
        join_columns: List[str] = None,
        roleplay_features: List[str] = None,
        warehouse_id: str = None,
        allow_aggregates: bool = True,
        publish: bool = True,
    ):
        """Add a table in the data warehouse to the data model

        Args:
            table_name (str): The table to join
            database (str): The database the table belongs to if relevant for the data warehouse.
            schema (str): The schema the table belongs to if relevant for the data warehouse.
            join_features (List[str]): The feature query names in the data model to join on. Defaults to None to create no joins.
            join_columns (list, optional): The column names in the dataframe to join to the join_features. List must be either
                None or the same length and order as join_features. Defaults to None to use identical names to the
                join_features. If multiple columns are needed for a single join they should be in a nested list
            roleplay_features (List[str], optional): The roleplays to use on the relationships. List must be either
                None or the same length and order as join_features. Use '' to not roleplay that relationship. Defaults to None.
            warehouse_id (str, optional): The id of the warehouse at which the data model and this dataset point.
            allow_aggregates(bool, optional): Whether to allow aggregates to be built off of the dataset. Defaults to True.
            publish (bool, optional): Whether or not the updated project should be published. Defaults to True.
        """
        model_utils._perspective_check(self)

        inspection = getfullargspec(self.add_table)
        validate_by_type_hints(inspection=inspection, func_params=locals())

        project_dict = self.project._get_dict()

        warehouse_id = validation_utils._validate_warehouse_id_parameter(
            atconn=self.project._atconn, project_dict=project_dict, warehouse_id=warehouse_id
        )

        atscale_table_name = db_utils.get_atscale_tablename(
            atconn=self.project._atconn,
            warehouse_id=warehouse_id,
            database=database,
            schema=schema,
            table_name=table_name,
        )

        self.project._update_project_tables(
            tables=[atscale_table_name],
            publish=False,
            project_dict=project_dict,
            update_project=False,
        )

        columns, atscale_table_name, schema, database = data_model_helpers._get_atscale_names(
            atconn=self.project._atconn,
            warehouse_id=warehouse_id,
            table_name=table_name,
            database=database,
            schema=schema,
            include_dtype=True,  # tuples of (column_name, column_dtype)
        )
        if atscale_table_name != table_name:
            raise atscale_errors.UserError(
                f"Unable to find table: '{table_name}'. Did you mean '{atscale_table_name}'? "
                f"If the table exists make sure AtScale has access to it"
            )

        # check to see that features are in the data model and can join
        column_names = {column[0] for column in columns}
        join_features, join_columns, roleplay_features, _ = data_model_helpers._check_joins(
            project_dict=project_dict,
            cube_id=self.cube_id,
            join_features=join_features,
            join_columns=join_columns,
            roleplay_features=roleplay_features,
            column_set=column_names,
        )

        project_dict = model_utils._create_dataset_relationship(
            atconn=self.project._atconn,
            project_dict=project_dict,
            cube_id=self.cube_id,
            database=database,
            schema=schema,
            table_name=atscale_table_name,
            join_features=join_features,
            join_columns=join_columns,
            roleplay_features=roleplay_features,
            table_columns=columns,
            warehouse_id=warehouse_id,
            allow_aggregates=allow_aggregates,
        )

        self.project._update_project(project_json=project_dict, publish=publish)

    def create_dataset_relationship(
        self,
        dataset_name: str,
        join_features: List[str],
        join_columns: List[str] = None,
        roleplay_features: List[str] = None,
        publish: bool = True,
    ):
        """Creates a relationship between a dataset and features in the model

        Args:
            dataset_name (str): The dataset to join
            join_features (List[str]): The feature query names in the data model to join on
            join_columns (list, optional): The column names in the dataset to join to the join_features. List must be either
                None or the same length and order as join_features. Defaults to None to use identical names to the
                join_features. If multiple columns are needed for a single join they should be in a nested list
            roleplay_features (List[str], optional): The roleplays to use on the relationships. List must be either
                None or the same length and order as join_features. Use '' to not roleplay that relationship. Defaults to None.
            publish (bool, optional): Whether or not the updated project should be published. Defaults to True.
        """
        model_utils._perspective_check(self)

        inspection = getfullargspec(self.create_dataset_relationship)
        validate_by_type_hints(inspection=inspection, func_params=locals())

        original_project_dict = self.project._get_dict()

        if not project_parser.get_dataset(
            project_dict=original_project_dict, dataset_name=dataset_name
        ):
            raise atscale_errors.UserError(
                f"No dataset with the name {dataset_name} found in project"
            )

        dset = dsp.Dataset(
            project_parser.get_dataset(
                project_dict=self.project._get_dict(), dataset_name=dataset_name
            )
        )

        if not dset.is_qds():
            self.project._update_project_tables(
                tables=[dset.table["name"]],
                publish=False,
                project_dict=original_project_dict,
                update_project=False,
            )  # update the project tables to get the latest columns
        # dataset may have been written from a table and thus aliased upper or lower case

        dataset_columns: List[dsp.Column] = dsp.Dataset(
            project_parser.get_dataset(
                project_dict=original_project_dict, dataset_name=dataset_name
            )
        ).columns
        column_set = {c.name for c in dataset_columns}
        join_columns: List[List[str]] = data_model_helpers._prep_join_columns_for_join(
            join_columns=join_columns, atscale_columns=column_set
        )

        join_features, join_columns, roleplay_features, _ = data_model_helpers._check_joins(
            project_dict=original_project_dict,
            cube_id=self.cube_id,
            join_features=join_features,
            join_columns=join_columns,
            roleplay_features=roleplay_features,
            column_set=column_set,
        )

        project_dict = model_utils._create_dataset_relationship_from_dataset(
            project_dict=original_project_dict,
            cube_id=self.cube_id,
            dataset_name=dataset_name,
            join_features=join_features,
            join_columns=join_columns,
            roleplay_features=roleplay_features,
        )
        self.project._update_project(project_json=project_dict, publish=publish)

    def get_data(
        self,
        feature_list: List[str],
        filter_equals: Dict[str, str] = None,
        filter_greater: Dict[str, str] = None,
        filter_less: Dict[str, str] = None,
        filter_greater_or_equal: Dict[str, str] = None,
        filter_less_or_equal: Dict[str, str] = None,
        filter_not_equal: Dict[str, str] = None,
        filter_in: Dict[str, list] = None,
        filter_between: Dict[str, tuple] = None,
        filter_like: Dict[str, str] = None,
        filter_rlike: Dict[str, str] = None,
        filter_null: List[str] = None,
        filter_not_null: List[str] = None,
        order_by: List[Tuple[str, str]] = None,
        limit: int = None,
        comment: str = None,
        use_aggs: bool = True,
        gen_aggs: bool = True,
        fake_results: bool = False,
        use_local_cache: bool = True,
        use_aggregate_cache: bool = True,
        timeout: int = 10,
        raise_multikey_warning: bool = True,
    ) -> pd.DataFrame:
        """Submits a query against the published project using the supplied information and returns the results in a pandas DataFrame.

        Args:
            feature_list (List[str]): The list of feature query names to query.
            filter_equals (Dict[str, str], optional): Filters results based on the feature equaling the value. Defaults to None.
            filter_greater (Dict[str, str], optional): Filters results based on the feature being greater than the value. Defaults to None.
            filter_less (Dict[str, str], optional): Filters results based on the feature being less than the value. Defaults to None.
            filter_greater_or_equal (Dict[str, str], optional): Filters results based on the feature being greater or equaling the value. Defaults to None.
            filter_less_or_equal (Dict[str, str], optional): Filters results based on the feature being less or equaling the value. Defaults to None.
            filter_not_equal (Dict[str, str], optional): Filters results based on the feature not equaling the value. Defaults to None.
            filter_in (Dict[str, list], optional): Filters results based on the feature being contained in the values. Defaults to None.
            filter_between (Dict[str, tuple], optional): Filters results based on the feature being between the values. Defaults to None.
            filter_like (Dict[str, str], optional): Filters results based on the feature being like the clause. Defaults to None.
            filter_rlike (Dict[str, str], optional): Filters results based on the feature being matched by the regular expression. Defaults to None.
            filter_null (List[str], optional): Filters results to show null values of the specified features. Defaults to None.
            filter_not_null (List[str], optional): Filters results to exclude null values of the specified features. Defaults to None.
            order_by (List[Tuple[str, str]]): The sort order for the returned dataframe. Accepts a list of tuples of the
                feature query name and ordering respectively: [('feature_name_1', 'DESC'), ('feature_2', 'ASC') ...].
                Defaults to None for AtScale Engine default sorting.
            limit (int, optional): Limit the number of results. Defaults to None for no limit.
            comment (str, optional): A comment string to build into the query. Defaults to None for no comment.
            use_aggs (bool, optional): Whether to allow the query to use aggs. Defaults to True.
            gen_aggs (bool, optional): Whether to allow the query to generate aggs. Defaults to True.
            fake_results (bool, optional): Whether to use fake results, often used to train aggregates with queries
                that will frequently be used. Defaults to False.
            use_local_cache (bool, optional): Whether to allow the query to use the local cache. Defaults to True.
            use_aggregate_cache (bool, optional): Whether to allow the query to use the aggregate cache. Defaults to True.
            timeout (int, optional): The number of minutes to wait for a response before timing out. Defaults to 10.
            raise_multikey_warning (str, optional): Whether to warn if a query contains attributes that have multiple key columns. Defaults to True.

        Returns:
            DataFrame: A pandas DataFrame containing the query results.
        """
        inspection = getfullargspec(self.get_data)
        validate_by_type_hints(inspection=inspection, func_params=locals())

        # set use_aggs and gen_aggs to True because we set them in the json when using the api
        # and this stops the flags being commented into the query
        query = query_utils._generate_atscale_query(
            data_model=self,
            feature_list=feature_list,
            filter_equals=filter_equals,
            filter_greater=filter_greater,
            filter_less=filter_less,
            filter_greater_or_equal=filter_greater_or_equal,
            filter_less_or_equal=filter_less_or_equal,
            filter_not_equal=filter_not_equal,
            filter_in=filter_in,
            filter_between=filter_between,
            filter_like=filter_like,
            filter_rlike=filter_rlike,
            filter_null=filter_null,
            filter_not_null=filter_not_null,
            order_by=order_by,
            limit=limit,
            comment=comment,
            raise_multikey_warning=raise_multikey_warning,
        )

        queryResponse = self.project._atconn._post_atscale_query(
            query,
            self.project.project_name,
            use_aggs=use_aggs,
            gen_aggs=gen_aggs,
            fake_results=fake_results,
            use_local_cache=use_local_cache,
            use_aggregate_cache=use_aggregate_cache,
            timeout=timeout,
        )

        df: pd.DataFrame = request_utils.parse_rest_query_response(queryResponse)

        model_utils._check_duplicate_features_get_data(feature_list)

        return df

    def get_data_direct(
        self,
        dbconn: SQLConnection,
        feature_list: List[str],
        filter_equals=None,
        filter_greater=None,
        filter_less=None,
        filter_greater_or_equal=None,
        filter_less_or_equal=None,
        filter_not_equal=None,
        filter_in=None,
        filter_between=None,
        filter_like=None,
        filter_rlike=None,
        filter_null=None,
        filter_not_null=None,
        order_by: List[Tuple[str, str]] = None,
        limit=None,
        comment=None,
        use_aggs=True,
        gen_aggs=True,
        raise_multikey_warning=True,
    ) -> pd.DataFrame:
        """Generates an AtScale query against the published project to get the given features, translates it to a database query, and
        submits it directly to the database using the SQLConnection. The results are returned as a Pandas DataFrame

        Args:
            dbconn (SQLConnection): The connection to use to submit the query to the database.
            feature_list (List[str]): The list of feature query names to query.
            filter_equals (Dict[str, str], optional): A dictionary of features to filter for equality to the value. Defaults to None.
            filter_greater (Dict[str, str], optional): A dictionary of features to filter greater than the value. Defaults to None.
            filter_less (Dict[str, str], optional): A dictionary of features to filter less than the value. Defaults to None.
            filter_greater_or_equal (Dict[str, str], optional): A dictionary of features to filter greater than or equal to the value. Defaults to None.
            filter_less_or_equal (Dict[str, str], optional): A dictionary of features to filter less than or equal to the value. Defaults to None.
            filter_not_equal (Dict[str, str], optional): A dictionary of features to filter not equal to the value. Defaults to None.
            filter_in (Dict[str, list], optional): A dictionary of features to filter in a list. Defaults to None.
            filter_between (Dict[str, tuple], optional): A dictionary of features to filter between the tuple values. Defaults to None.
            filter_like (Dict[str, str], optional): A dictionary of features to filter like the value. Defaults to None.
            filter_rlike (Dict[str, str], optional): A dictionary of features to filter rlike the value. Defaults to None.
            filter_null (List[str], optional): A list of features to filter for null. Defaults to None.
            filter_not_null (List[str], optional): A list of features to filter for not null. Defaults to None.
            order_by (List[Tuple[str, str]]): The sort order for the returned dataframe. Accepts a list of tuples of the
                feature query name and ordering respectively: [('feature_name_1', 'DESC'), ('feature_2', 'ASC') ...].
                Defaults to None for AtScale Engine default sorting.
            limit (int, optional): A limit to put on the query. Defaults to None.
            comment (str, optional): A comment to put in the query. Defaults to None.
            use_aggs (bool, optional): Whether to allow the query to use aggs. Defaults to True.
            gen_aggs (bool, optional): Whether to allow the query to generate aggs. Defaults to True.
            raise_multikey_warning (str, optional): Whether to warn if a query contains attributes that have multiple key columns. Defaults to True.

        Returns:
            DataFrame: The results of the query as a DataFrame
        """
        inspection = getfullargspec(self.get_data_direct)
        validate_by_type_hints(inspection=inspection, func_params=locals())

        df = dbconn.submit_query(
            query_utils._generate_db_query(
                data_model=self,
                atscale_query=query_utils._generate_atscale_query(
                    data_model=self,
                    feature_list=feature_list,
                    filter_equals=filter_equals,
                    filter_greater=filter_greater,
                    filter_less=filter_less,
                    filter_greater_or_equal=filter_greater_or_equal,
                    filter_less_or_equal=filter_less_or_equal,
                    filter_not_equal=filter_not_equal,
                    filter_in=filter_in,
                    filter_between=filter_between,
                    filter_like=filter_like,
                    filter_rlike=filter_rlike,
                    filter_null=filter_null,
                    filter_not_null=filter_not_null,
                    order_by=order_by,
                    limit=limit,
                    comment=comment,
                    raise_multikey_warning=raise_multikey_warning,
                ),
                use_aggs=use_aggs,
                gen_aggs=gen_aggs,
            )
        )

        model_utils._check_duplicate_features_get_data(feature_list)

        return df

    def get_data_jdbc(
        self,
        feature_list: List[str],
        filter_equals: Dict[str, str] = None,
        filter_greater: Dict[str, str] = None,
        filter_less: Dict[str, str] = None,
        filter_greater_or_equal: Dict[str, str] = None,
        filter_less_or_equal: Dict[str, str] = None,
        filter_not_equal: Dict[str, str] = None,
        filter_in: Dict[str, list] = None,
        filter_between: Dict[str, tuple] = None,
        filter_like: Dict[str, str] = None,
        filter_rlike: Dict[str, str] = None,
        filter_null: List[str] = None,
        filter_not_null: List[str] = None,
        order_by: List[Tuple[str, str]] = None,
        limit: int = None,
        comment: str = None,
        use_aggs=True,
        gen_aggs=True,
        raise_multikey_warning=True,
    ) -> pd.DataFrame:
        """Establishes a jdbc connection to Atscale with the supplied information. Then submits query against the published project and returns the results in a pandas DataFrame.

        Args:
            feature_list (List[str]): The list of feature query names to query.
            filter_equals (Dict[str, str], optional): Filters results based on the feature equaling the value. Defaults to None.
            filter_greater (Dict[str, str], optional): Filters results based on the feature being greater than the value. Defaults to None.
            filter_less (Dict[str, str], optional): Filters results based on the feature being less than the value. Defaults to None.
            filter_greater_or_equal (Dict[str, str], optional): Filters results based on the feature being greater or equaling the value. Defaults to None.
            filter_less_or_equal (Dict[str, str], optional): Filters results based on the feature being less or equaling the value. Defaults to None.
            filter_not_equal (Dict[str, str], optional): Filters results based on the feature not equaling the value. Defaults to None.
            filter_in (Dict[str, list], optional): Filters results based on the feature being contained in the values. Defaults to None.
            filter_between (Dict[str, tuple], optional): Filters results based on the feature being between the values. Defaults to None.
            filter_like (Dict[str, str], optional): Filters results based on the feature being like the clause. Defaults to None.
            filter_rlike (Dict[str, str], optional): Filters results based on the feature being matched by the regular expression. Defaults to None.
            filter_null (List[str], optional): Filters results to show null values of the specified features. Defaults to None.
            filter_not_null (List[str], optional): Filters results to exclude null values of the specified features. Defaults to None.
            order_by (List[Tuple[str, str]]): The sort order for the returned dataframe. Accepts a list of tuples of the
                feature query name and ordering respectively: [('feature_name_1', 'DESC'), ('feature_2', 'ASC') ...].
                Defaults to None for AtScale Engine default sorting.
            limit (int, optional): Limit the number of results. Defaults to None for no limit.
            comment (str, optional): A comment string to build into the query. Defaults to None for no comment.
            use_aggs (bool, optional): Whether to allow the query to use aggs. Defaults to True.
            gen_aggs (bool, optional): Whether to allow the query to generate aggs. Defaults to True.
            raise_multikey_warning (str, optional): Whether to warn if a query contains attributes that have multiple key columns. Defaults to True.

        Returns:
            DataFrame: A pandas DataFrame containing the query results.
        """
        inspection = getfullargspec(self.get_data_jdbc)
        validate_by_type_hints(inspection=inspection, func_params=locals())

        query = query_utils._generate_atscale_query(
            data_model=self,
            feature_list=feature_list,
            filter_equals=filter_equals,
            filter_greater=filter_greater,
            filter_less=filter_less,
            filter_greater_or_equal=filter_greater_or_equal,
            filter_less_or_equal=filter_less_or_equal,
            filter_not_equal=filter_not_equal,
            filter_in=filter_in,
            filter_between=filter_between,
            filter_like=filter_like,
            filter_rlike=filter_rlike,
            filter_null=filter_null,
            filter_not_null=filter_not_null,
            order_by=order_by,
            limit=limit,
            comment=comment,
            use_aggs=use_aggs,
            gen_aggs=gen_aggs,
            raise_multikey_warning=raise_multikey_warning,
        )
        conn = self.project._atconn._get_jdbc_connection()
        # can't just use read_sql right now because pandas isn't correctly parsing dates
        # df = pd.read_sql(query, conn)
        curs = conn.cursor()
        curs.execute(query)

        columns = [desc[0] for desc in curs.description]
        types = [desc[1] for desc in curs.description]

        df = pd.DataFrame(curs.fetchall(), columns=columns)
        for column, type in list(zip(columns, types)):
            type_lower = type.values[0].lower()
            if "date" in type_lower or "time" in type_lower:
                df[column] = pd.to_datetime(df[column], errors="coerce", infer_datetime_format=True)

        model_utils._check_duplicate_features_get_data(feature_list)

        return df

    def get_data_spark_jdbc(
        self,
        feature_list: List[str],
        spark_session: "SparkSession",
        jdbc_format: str,
        jdbc_options: Dict[str, str],
        filter_equals: Dict[str, str] = None,
        filter_greater: Dict[str, str] = None,
        filter_less: Dict[str, str] = None,
        filter_greater_or_equal: Dict[str, str] = None,
        filter_less_or_equal: Dict[str, str] = None,
        filter_not_equal: Dict[str, str] = None,
        filter_in: Dict[str, list] = None,
        filter_between: Dict[str, tuple] = None,
        filter_like: Dict[str, str] = None,
        filter_rlike: Dict[str, str] = None,
        filter_null: List[str] = None,
        filter_not_null: List[str] = None,
        order_by: List[Tuple[str, str]] = None,
        limit: int = None,
        comment: str = None,
        use_aggs=True,
        gen_aggs=True,
        raise_multikey_warning=True,
    ):
        """Uses the provided information to establish a jdbc connection to the underlying dwh. Generates a query against the published project and uses
            the provided spark_session to execute. Returns the results in a spark DataFrame.

        Args:
            feature_list (List[str]): The list of feature query names to query.
            spark_session (pyspark.sql.SparkSession): The pyspark SparkSession to execute the query with
            jdbc_format (str): the driver class name. For example: 'jdbc', 'net.snowflake.spark.snowflake', 'com.databricks.spark.redshift'
            jdbc_options (Dict[str,str]): Case-insensitive to specify connection options for jdbc
            filter_equals (Dict[str, str], optional): Filters results based on the feature equaling the value. Defaults to None.
            filter_greater (Dict[str, str], optional): Filters results based on the feature being greater than the value. Defaults to None.
            filter_less (Dict[str, str], optional): Filters results based on the feature being less than the value. Defaults to None.
            filter_greater_or_equal (Dict[str, str], optional): Filters results based on the feature being greater or equaling the value. Defaults to None.
            filter_less_or_equal (Dict[str, str], optional): Filters results based on the feature being less or equaling the value. Defaults to None.
            filter_not_equal (Dict[str, str], optional): Filters results based on the feature not equaling the value. Defaults to None.
            filter_in (Dict[str, list], optional): Filters results based on the feature being contained in the values. Defaults to None.
            filter_between (Dict[str, tuple], optional): Filters results based on the feature being between the values. Defaults to None.
            filter_like (Dict[str, str], optional): Filters results based on the feature being like the clause. Defaults to None.
            filter_rlike (Dict[str, str], optional): Filters results based on the feature being matched by the regular expression. Defaults to None.
            filter_null (List[str], optional): Filters results to show null values of the specified features. Defaults to None.
            filter_not_null (List[str], optional): Filters results to exclude null values of the specified features. Defaults to None.
            order_by (List[Tuple[str, str]]): The sort order for the returned dataframe. Accepts a list of tuples of the
                feature query name and ordering respectively: [('feature_name_1', 'DESC'), ('feature_2', 'ASC') ...].
                Defaults to None for AtScale Engine default sorting.
            limit (int, optional): Limit the number of results. Defaults to None for no limit.
            comment (str, optional): A comment string to build into the query. Defaults to None for no comment.
            use_aggs (bool, optional): Whether to allow the query to use aggs. Defaults to True.
            gen_aggs (bool, optional): Whether to allow the query to generate aggs. Defaults to True.
            raise_multikey_warning (str, optional): Whether to warn if a query contains attributes that have multiple key columns. Defaults to True.

        Returns:
            pyspark.sql.dataframe.DataFrame: A pyspark DataFrame containing the query results.
        """
        inspection = getfullargspec(self.get_data_spark_jdbc)
        validate_by_type_hints(inspection=inspection, func_params=locals())

        try:
            from pyspark.sql import SparkSession
        except ImportError as e:
            raise atscale_errors.AtScaleExtrasDependencyImportError("spark", str(e))

        query = query_utils._generate_db_query(
            self,
            query_utils._generate_atscale_query(
                data_model=self,
                feature_list=feature_list,
                filter_equals=filter_equals,
                filter_greater=filter_greater,
                filter_less=filter_less,
                filter_greater_or_equal=filter_greater_or_equal,
                filter_less_or_equal=filter_less_or_equal,
                filter_not_equal=filter_not_equal,
                filter_in=filter_in,
                filter_between=filter_between,
                filter_like=filter_like,
                filter_rlike=filter_rlike,
                filter_null=filter_null,
                filter_not_null=filter_not_null,
                order_by=order_by,
                limit=limit,
                comment=comment,
                raise_multikey_warning=raise_multikey_warning,
            ),
            use_aggs=use_aggs,
            gen_aggs=gen_aggs,
        )

        logger.info(
            f"get_data_spark_jdbc is only compatible with databricks runtimes >=13.0. Versions less than this will have issues with their built in jdbc drivers."
        )
        df = (
            spark_session.read.format(jdbc_format)
            .options(**jdbc_options)
            .option("query", query)
            .load()
        )

        column_index = range(len(df.columns))
        column_names = df.columns

        for column in column_index:
            df = df.withColumnRenamed(column_names[column], feature_list[column])

        return df

    def get_data_spark(
        self,
        feature_list: List[str],
        spark_session,
        filter_equals: Dict[str, str] = None,
        filter_greater: Dict[str, str] = None,
        filter_less: Dict[str, str] = None,
        filter_greater_or_equal: Dict[str, str] = None,
        filter_less_or_equal: Dict[str, str] = None,
        filter_not_equal: Dict[str, str] = None,
        filter_in: Dict[str, list] = None,
        filter_between: Dict[str, tuple] = None,
        filter_like: Dict[str, str] = None,
        filter_rlike: Dict[str, str] = None,
        filter_null: List[str] = None,
        filter_not_null: List[str] = None,
        order_by: List[Tuple[str, str]] = None,
        limit: int = None,
        comment: str = None,
        use_aggs=True,
        gen_aggs=True,
        raise_multikey_warning: bool = True,
    ):
        """Uses the provided spark_session to execute a query generated by the atscale query engine against the published project.
        Returns the results in a spark DataFrame.

        Args:
            feature_list (List[str]): The list of feature query names to query.
            spark_session (pyspark.sql.SparkSession): The pyspark SparkSession to execute the query with
            filter_equals (Dict[str, str], optional): Filters results based on the feature equaling the value. Defaults to None.
            filter_greater (Dict[str, str], optional): Filters results based on the feature being greater than the value. Defaults to None.
            filter_less (Dict[str, str], optional): Filters results based on the feature being less than the value. Defaults to None.
            filter_greater_or_equal (Dict[str, str], optional): Filters results based on the feature being greater or equaling the value. Defaults to None.
            filter_less_or_equal (Dict[str, str], optional): Filters results based on the feature being less or equaling the value. Defaults to None.
            filter_not_equal (Dict[str, str], optional): Filters results based on the feature not equaling the value. Defaults to None.
            filter_in (Dict[str, list], optional): Filters results based on the feature being contained in the values. Defaults to None.
            filter_between (Dict[str, tuple], optional): Filters results based on the feature being between the values. Defaults to None.
            filter_like (Dict[str, str], optional): Filters results based on the feature being like the clause. Defaults to None.
            filter_rlike (Dict[str, str], optional): Filters results based on the feature being matched by the regular expression. Defaults to None.
            filter_null (List[str], optional): Filters results to show null values of the specified features. Defaults to None.
            filter_not_null (List[str], optional): Filters results to exclude null values of the specified features. Defaults to None.
            order_by (List[Tuple[str, str]]): The sort order for the returned dataframe. Accepts a list of tuples of the
                feature query name and ordering respectively: [('feature_name_1', 'DESC'), ('feature_2', 'ASC') ...].
                Defaults to None for AtScale Engine default sorting.
            limit (int, optional): Limit the number of results. Defaults to None for no limit.
            comment (str, optional): A comment string to build into the query. Defaults to None for no comment.
            use_aggs (bool, optional): Whether to allow the query to use aggs. Defaults to True.
            gen_aggs (bool, optional): Whether to allow the query to generate aggs. Defaults to True.
            raise_multikey_warning (str, optional): Whether to warn if a query contains attributes that have multiple key columns. Defaults to True.
        Returns:
            pyspark.sql.dataframe.DataFrame: A pyspark DataFrame containing the query results.
        """
        inspection = getfullargspec(self.get_data_spark_from_spark)
        validate_by_type_hints(inspection=inspection, func_params=locals())

        try:
            from pyspark.sql import SparkSession
        except ImportError as e:
            raise atscale_errors.AtScaleExtrasDependencyImportError("spark", str(e))

        query = query_utils._generate_db_query(
            self,
            query_utils._generate_atscale_query(
                data_model=self,
                feature_list=feature_list,
                filter_equals=filter_equals,
                filter_greater=filter_greater,
                filter_less=filter_less,
                filter_greater_or_equal=filter_greater_or_equal,
                filter_less_or_equal=filter_less_or_equal,
                filter_not_equal=filter_not_equal,
                filter_in=filter_in,
                filter_between=filter_between,
                filter_like=filter_like,
                filter_rlike=filter_rlike,
                filter_null=filter_null,
                filter_not_null=filter_not_null,
                order_by=order_by,
                limit=limit,
                comment=comment,
                raise_multikey_warning=raise_multikey_warning,
            ),
            use_aggs=use_aggs,
            gen_aggs=gen_aggs,
        )

        # ok here I want to call a sqlconn function that optionally can adjust the default catalog/database of the session and then revert it
        df = spark_session.sql(query)

        column_index = range(len(df.columns))
        column_names = df.columns

        for column in column_index:
            df = df.withColumnRenamed(column_names[column], feature_list[column])

        model_utils._check_duplicate_features_get_data(feature_list)

        return df

    def get_database_query(
        self,
        feature_list: List[str],
        filter_equals: Dict[str, Any] = None,
        filter_greater: Dict[str, Any] = None,
        filter_less: Dict[str, Any] = None,
        filter_greater_or_equal: Dict[str, Any] = None,
        filter_less_or_equal: Dict[str, Any] = None,
        filter_not_equal: Dict[str, Any] = None,
        filter_in: Dict[str, List[Any]] = None,
        filter_between: Dict[str, tuple] = None,
        filter_like: Dict[str, Any] = None,
        filter_rlike: Dict[str, Any] = None,
        filter_null: List[str] = None,
        filter_not_null: List[str] = None,
        order_by: List[Tuple[str, str]] = None,
        limit: int = None,
        comment: str = None,
        use_aggs: bool = True,
        gen_aggs: bool = True,
        raise_multikey_warning=True,
    ) -> str:
        """Returns a database query generated using the published project AtScale to get the given features

        Args:
            feature_list (List[str]): The list of feature query names to query.
            filter_equals (Dict[str, str], optional): A dictionary of features to filter for equality to the value. Defaults to None.
            filter_greater (Dict[str, str], optional): A dictionary of features to filter greater than the value. Defaults to None.
            filter_less (Dict[str, str], optional): A dictionary of features to filter less than the value. Defaults to None.
            filter_greater_or_equal (Dict[str, str], optional): A dictionary of features to filter greater than or equal to the value. Defaults to None.
            filter_less_or_equal (Dict[str, str], optional): A dictionary of features to filter less than or equal to the value. Defaults to None.
            filter_not_equal (Dict[str, str], optional): A dictionary of features to filter not equal to the value. Defaults to None.
            filter_in (Dict[str, list], optional): A dictionary of features to filter in a list. Defaults to None.
            filter_between (Dict[str, tuple], optional): A dictionary of features to filter between the tuple values. Defaults to None.
            filter_like (Dict[str, str], optional): A dictionary of features to filter like the value. Defaults to None.
            filter_rlike (Dict[str, str], optional): A dictionary of features to filter rlike the value. Defaults to None.
            filter_null (List[str], optional): A list of features to filter for null. Defaults to None.
            filter_not_null (List[str], optional): A list of features to filter for not null. Defaults to None.
            order_by (List[Tuple[str, str]]): The sort order for the returned query. Accepts a list of tuples of the
                feature query name and ordering respectively: [('feature_name_1', 'DESC'), ('feature_2', 'ASC') ...].
                Defaults to None for AtScale Engine default sorting.
            limit (int, optional): A limit to put on the query. Defaults to None.
            comment (str, optional): A comment to put in the query. Defaults to None.
            use_aggs (bool, optional): Whether to allow the query to use aggs. Defaults to True.
            gen_aggs (bool, optional): Whether to allow the query to generate aggs. Defaults to True.
            raise_multikey_warning (str, optional): Whether to warn if a query contains attributes that have multiple key columns. Defaults to True.

        Returns:
            str: The generated database query
        """
        inspection = getfullargspec(self.get_database_query)
        validate_by_type_hints(inspection=inspection, func_params=locals())

        return query_utils._generate_db_query(
            data_model=self,
            atscale_query=query_utils._generate_atscale_query(
                data_model=self,
                feature_list=feature_list,
                filter_equals=filter_equals,
                filter_greater=filter_greater,
                filter_less=filter_less,
                filter_greater_or_equal=filter_greater_or_equal,
                filter_less_or_equal=filter_less_or_equal,
                filter_not_equal=filter_not_equal,
                filter_in=filter_in,
                filter_between=filter_between,
                filter_like=filter_like,
                filter_rlike=filter_rlike,
                filter_null=filter_null,
                filter_not_null=filter_not_null,
                order_by=order_by,
                limit=limit,
                comment=comment,
                raise_multikey_warning=raise_multikey_warning,
            ),
            use_aggs=use_aggs,
            gen_aggs=gen_aggs,
        )

    def submit_atscale_query(
        self,
        query: str,
        use_aggs: bool = True,
        gen_aggs: bool = True,
        fake_results: bool = False,
        use_local_cache: bool = True,
        use_aggregate_cache: bool = True,
        timeout: int = 10,
    ) -> pd.DataFrame:
        """Submits the given query against the published project and returns the results in a pandas DataFrame.

        Args:
            query (str): The SQL query to submit.
            use_aggs (bool, optional): Whether to allow the query to use aggs. Defaults to True.
            gen_aggs (bool, optional): Whether to allow the query to generate aggs. Defaults to True.
            fake_results (bool, optional): Whether to use fake results, often used to train aggregates with queries
                that will frequently be used. Defaults to False.
            use_local_cache (bool, optional): Whether to allow the query to use the local cache. Defaults to True.
            use_aggregate_cache (bool, optional): Whether to allow the query to use the aggregate cache. Defaults to True.
            timeout (int, optional): The number of minutes to wait for a response before timing out. Defaults to 10.

        Returns:
            DataFrame: A pandas DataFrame containing the query results.
        """
        inspection = getfullargspec(self.submit_atscale_query)
        validate_by_type_hints(inspection=inspection, func_params=locals())

        queryResponse = self.project._atconn._post_atscale_query(
            query,
            self.project.project_name,
            use_aggs=use_aggs,
            gen_aggs=gen_aggs,
            fake_results=fake_results,
            use_local_cache=use_local_cache,
            use_aggregate_cache=use_aggregate_cache,
            timeout=timeout,
        )

        df: pd.DataFrame = request_utils.parse_rest_query_response(queryResponse)

        return df

    def writeback_spark_jdbc(
        self,
        dbconn: SQLConnection,
        pyspark_dataframe: "pyspark.sql.dataframe.DataFrame",
        jdbc_format: str,
        jdbc_options: Dict[str, str],
        join_features: list,
        join_columns: list = None,
        roleplay_features: list = None,
        table_name: str = None,
        warehouse_id: str = None,
        publish: bool = True,
        if_exists: PysparkTableExistsActionType = PysparkTableExistsActionType.ERROR,
    ):
        """Writes the pyspark dataframe to a table in the database accessed via jdbc with the given table_name. Joins that table to this
        DataModel by joining on the given join_features or join_columns.

        Args:
            dbconn (SQLConnection): connection to the database; should be the same one the model and project are based on
            pyspark_dataframe (pyspark.sql.dataframe.DataFrame): The pyspark dataframe to write
            jdbc_format (str): the driver class name. For example: 'jdbc', 'net.snowflake.spark.snowflake', 'com.databricks.spark.redshift'
            jdbc_options (Dict[str,str]): Case-insensitive to specify connection options for jdbc. The query option is dynamically generated by
                atscale, as a result including a table or query parameter can cause issues.
            join_features (list): a list of feature query names in the data model to use for joining.
            join_columns (list, optional): The columns in the dataframe to join to the join_features. List must be either
                None or the same length and order as join_features. Defaults to None to use identical names to the
                join_features. If multiple columns are needed for a single join they should be in a nested list
            roleplay_features (list, optional): The roleplays to use on the relationships. List must be either
                None or the same length and order as join_features. Use '' to not roleplay that relationship. Defaults to None.
            table_name (str, optional): The name for the table to be created for the given PySpark DataFrame. Can be none if name specified in options
            warehouse_id (str, optional): The warehouse the data model points at and to use for the writeback.
                Defaults to None to use the warehouse used in the project already.
            publish (bool, optional): Whether the updated project should be published. Defaults to True.
            if_exists (PysparkTableExistsActionType, optional): What to do if a table with table_name already exists. Defaults to PysparkTableExistsActionType.ERROR.
        """
        model_utils._perspective_check(self)

        inspection = getfullargspec(self.writeback_spark_jdbc)
        validate_by_type_hints(inspection=inspection, func_params=locals())

        # import the needed spark packages
        try:
            from pyspark.sql import DataFrame
        except ImportError as e:
            raise atscale_errors.AtScaleExtrasDependencyImportError("jdbc", str(e))

        project_dict = self.project._get_dict()
        validation_utils._validate_warehouse_connection(
            atconn=self.project._atconn, project_dict=project_dict, dbconn=dbconn
        )
        warehouse_id = validation_utils._validate_warehouse_id_parameter(
            atconn=self.project._atconn,
            project_dict=project_dict,
            warehouse_id=warehouse_id,
            dbconn_warehouse_id=dbconn.warehouse_id,
        )

        (
            join_features,
            join_columns,
            roleplay_features,
            pyspark_dataframe,
        ) = data_model_helpers._check_joins(
            project_dict=project_dict,
            cube_id=self.cube_id,
            join_features=join_features,
            join_columns=join_columns,
            roleplay_features=roleplay_features,
            column_set=pyspark_dataframe.columns,
            df=pyspark_dataframe,
            dbconn=dbconn,
            spark_input=True,
        )

        dbconn._write_pysparkdf_to_external_db(
            pyspark_dataframe=pyspark_dataframe,
            jdbc_format=jdbc_format,
            jdbc_options=jdbc_options,
            table_name=table_name,
            if_exists=if_exists,
        )

        # If we're replacing a table, then the columns may have changed and the data sets need to be updated.
        if if_exists == PysparkTableExistsActionType.OVERWRITE:
            database, schema = db_utils.get_database_and_schema(dbconn=dbconn)
            atscale_table_name = db_utils.get_atscale_tablename(
                atconn=self.project._atconn,
                warehouse_id=warehouse_id,
                database=database,
                schema=schema,
                table_name=table_name,
            )
            self.project._update_project_tables(
                tables=[atscale_table_name],
                publish=False,
                project_dict=project_dict,
                update_project=False,
            )

        (
            atscale_columns,
            atscale_table_name,
            schema,
            database,
        ) = data_model_helpers._get_atscale_names(
            atconn=self.project._atconn,
            warehouse_id=warehouse_id,
            dbconn=dbconn,
            table_name=table_name,
            expected_columns=pyspark_dataframe.columns,
            include_dtype=True,
        )

        aliases = {c[0] for c in atscale_columns}
        join_columns: List[List[str]] = data_model_helpers._prep_join_columns_for_join(
            join_columns=join_columns,
            atscale_columns=aliases,
        )

        # add_table now mutates the project_json and returns, then we're responsible for posting
        project_dict = model_utils._create_dataset_relationship(
            atconn=self.project._atconn,
            project_dict=project_dict,
            cube_id=self.cube_id,
            database=database,
            schema=schema,
            table_name=atscale_table_name,
            join_features=join_features,
            join_columns=join_columns,
            roleplay_features=roleplay_features,
            table_columns=atscale_columns,
            warehouse_id=warehouse_id,
        )

        self.project._update_project(project_json=project_dict, publish=publish)

    def writeback_spark(
        self,
        pyspark_dataframe: "pyspark.sql.dataframe.DataFrame",
        schema: str,
        table_name: str,
        join_features: list,
        join_columns: list = None,
        roleplay_features: list = None,
        warehouse_id: str = None,
        database: str = None,
        publish: bool = True,
        if_exists: PysparkTableExistsActionType = PysparkTableExistsActionType.ERROR,
    ):
        """Writes the pyspark dataframe to a table in the database accessed via jdbc with the given table_name. Joins that table to this
        DataModel by joining on the given join_features or join_columns.

        Args:
            pyspark_dataframe (pyspark.sql.dataframe.DataFrame): The pyspark dataframe to write
            schema (str): The name of the schema (second part of the three part name) for the table to be created in for the given PySpark DataFrame.
            table_name (str): The name for the table to be created for the given PySpark DataFrame.
            join_features (list): a list of feature query names in the data model to use for joining.
            join_columns (list, optional): The columns in the dataframe to join to the join_features. List must be either
                None or the same length and order as join_features. Defaults to None to use identical names to the
                join_features. If multiple columns are needed for a single join they should be in a nested list
            roleplay_features (list, optional): The roleplays to use on the relationships. List must be either
                None or the same length and order as join_features. Use '' to not roleplay that relationship. Defaults to None.
            warehouse_id (str, optional): The warehouse id to use which points at the warehouse of dbconn and that the
                data model points at. Defaults to None, to use the warehouse previously used in the data model.
            database (str, optional): The name of the database (first part of the three part name if applicable) for the table to be created in for the given PySpark DataFrame. Defaults to None.
            publish (bool, optional): Whether or not the updated project should be published. Defaults to True.
            if_exists (PysparkTableExistsActionType, optional): What to do if a table with table_name already exists. Defaults to PysparkTableExistsActionType.ERROR.
        """
        model_utils._perspective_check(self)

        inspection = getfullargspec(self.writeback_spark)
        validate_by_type_hints(inspection=inspection, func_params=locals())

        # import the needed spark packages
        try:
            from pyspark.sql import DataFrame
        except ImportError as e:
            raise atscale_errors.AtScaleExtrasDependencyImportError("spark", str(e))

        project_dict = self.project._get_dict()

        warehouse_id = validation_utils._validate_warehouse_id_parameter(
            atconn=self.project._atconn,
            project_dict=project_dict,
            warehouse_id=warehouse_id,
        )

        (
            join_features,
            join_columns,
            roleplay_features,
            pyspark_dataframe,
        ) = data_model_helpers._check_joins(
            project_dict=project_dict,
            cube_id=self.cube_id,
            join_features=join_features,
            join_columns=join_columns,
            roleplay_features=roleplay_features,
            column_set=pyspark_dataframe.columns,
            df=pyspark_dataframe,
            spark_input=True,
            use_spark=True,
        )
        table = f"{schema}.{table_name}"
        if database:
            table = f"{database}.{table}"
        pyspark_dataframe.write.mode(if_exists.value).saveAsTable(table)

        # If we're replacing a table, then the columns may have changed and the data sets need to be updated.
        if if_exists == PysparkTableExistsActionType.OVERWRITE:
            atscale_table_name = db_utils.get_atscale_tablename(
                atconn=self.project._atconn,
                warehouse_id=warehouse_id,
                database=database,
                schema=schema,
                table_name=table_name,
            )
            self.project._update_project_tables(
                tables=[atscale_table_name],
                publish=False,
                project_dict=project_dict,
                update_project=False,
            )

        (
            atscale_columns,
            atscale_table_name,
            schema,
            database,
        ) = data_model_helpers._get_atscale_names(
            atconn=self.project._atconn,
            warehouse_id=warehouse_id,
            database=database,
            schema=schema,
            table_name=table_name,
            expected_columns=pyspark_dataframe.columns,
            include_dtype=True,
        )

        aliases = {c[0] for c in atscale_columns}
        join_columns: List[List[str]] = data_model_helpers._prep_join_columns_for_join(
            join_columns=join_columns,
            atscale_columns=aliases,
        )

        # add_table now mutates the project_json and returns, then we're responsible for posting
        project_dict = model_utils._create_dataset_relationship(
            atconn=self.project._atconn,
            project_dict=project_dict,
            cube_id=self.cube_id,
            database=database,
            schema=schema,
            table_name=atscale_table_name,
            join_features=join_features,
            join_columns=join_columns,
            roleplay_features=roleplay_features,
            table_columns=atscale_columns,
            warehouse_id=warehouse_id,
        )

        self.project._update_project(project_json=project_dict, publish=publish)

    def create_secondary_attribute(
        self,
        dataset_name: str,
        new_feature_name: str,
        column_name: str,
        hierarchy_name: str,
        level_name: str,
        description: str = None,
        caption: str = None,
        folder: str = None,
        visible: bool = True,
        publish: bool = True,
    ):
        """Creates a new secondary attribute on an existing hierarchy and level.

        Args:
            dataset_name (str): The dataset containing the column that the secondary attribute will use.
            new_feature_name (str): What the attribute will be called.
            column_name (str): The column that the seconday attribute will use.
            hierarchy_name (str): The query name of the hierarchy to add the attribute to.
            level_name (str): The query name of the level of the hierarchy to add the attribute to.
            description (str, optional): The description for the attribute. Defaults to None.
            caption (str, optional): The caption for the attribute. Defaults to None.
            folder (str, optional): The folder for the attribute. Defaults to None.
            visible (bool, optional): Whether or not the secondary attribute will be visible to BI tools. Defaults to True.
            publish (bool, optional): Whether or not the updated project should be published. Defaults to True.
        """
        model_utils._perspective_check(self)

        inspection = getfullargspec(self.create_secondary_attribute)
        validate_by_type_hints(inspection=inspection, func_params=locals())

        project_json = self.project._get_dict()

        model_utils._check_conflicts(
            data_model=self, to_add=new_feature_name, project_dict=project_json
        )

        if not self.dataset_exists(dataset_name, include_unused=False):
            raise atscale_errors.UserError(
                f"Dataset '{dataset_name}' not associated with given model"
            )

        if not model_utils._column_exists(project_json, dataset_name, column_name):
            raise atscale_errors.UserError(
                f"Column '{column_name}' not found in the '{dataset_name}' dataset"
            )

        feature_utils._check_draft_hierarchy(
            project_json, self.name, hierarchy_name, level_name, expect_base_input=True
        )

        data_set = project_parser.get_dataset(project_dict=project_json, dataset_name=dataset_name)

        # call the helper
        feature_utils._create_secondary_attribute(
            self.cube_id,
            project_json,
            data_set,
            new_feature_name=new_feature_name,
            column_name=column_name,
            hierarchy_name=hierarchy_name,
            level_name=level_name,
            description=description,
            caption=caption,
            folder=folder,
            visible=visible,
        )

        self.project._update_project(project_json=project_json, publish=publish)

    def update_categorical_feature(
        self,
        feature_name: str,
        description: str = None,
        caption: str = None,
        folder: str = None,
        publish: bool = True,
    ):
        """Updates the metadata for an existing categorical feature.

        Args:
            feature_name (str): The name of the feature to update.
            description (str, optional): The new description for the feature. Defaults to None to leave unchanged.
            caption (str, optional): The new caption for the feature. Defaults to None to leave unchanged.
            folder (str, optional): The new folder to put the feature in. Defaults to None to leave unchanged.
            publish (bool, optional): Whether or not the updated project should be published. Defaults to True.
        """
        model_utils._perspective_check(self)

        inspection = getfullargspec(self.update_categorical_feature)
        validate_by_type_hints(inspection=inspection, func_params=locals())

        project_dict = self.project._get_dict()

        features = data_model_helpers._get_draft_features(
            project_dict=project_dict,
            data_model_name=self.name,
            feature_type=FeatureType.CATEGORICAL,
        )

        found = False
        for name, info in features.items():
            if info.get("base_name", name) == feature_name:
                found = True
                break
            elif name == feature_name and name != info.get("base_name", name):
                raise atscale_errors.UserError(
                    f"Feature: '{feature_name}' is roleplayed. Only the base feature can be updated and all roleplays will inherit the changes."
                )
        if found == False:
            raise atscale_errors.UserError(f"Feature: '{feature_name}' not found.")

        if folder is not None and info.get("secondary_attribute", False) == False:
            raise atscale_errors.UserError(
                f"Folders can only be updated for secondary attributes. Feature: '{feature_name}' is a level, so it inherits the folder of its hierarchy."
            )

        feature_utils._update_categorical_feature(
            project_dict=project_dict,
            data_model_name=self.name,
            feature_name=feature_name,
            description=description,
            caption=caption,
            folder=folder,
        )
        if project_dict is not None:
            self.project._update_project(project_json=project_dict, publish=publish)

    def create_filter_attribute(
        self,
        new_feature_name: str,
        hierarchy_name: str,
        level_name: str,
        filter_values: List[str],
        caption: str = None,
        description: str = None,
        folder: str = None,
        visible: str = True,
        publish: bool = True,
    ):
        """Creates a new boolean secondary attribute to filter on a given subset of the level's values.

        Args:
            new_feature_name (str): The query name of the new attribute.
            hierarchy_name (str): The query name of the hierarchy the level belongs to.
            level_name (str): The query name of the level to apply the filter to.
            filter_values (List[str]): The list of values to filter on.
            caption (str): The caption for the feature. Defaults to None.
            description (str): The description for the feature. Defaults to None.
            folder (str): The folder to put the feature in. Defaults to None.
            visible (bool): Whether the created attribute will be visible to BI tools. Defaults to True.
            publish (bool): Whether or not the updated project should be published. Defaults to True.
        """
        model_utils._perspective_check(self)

        inspection = getfullargspec(self.create_filter_attribute)
        validate_by_type_hints(inspection=inspection, func_params=locals())

        project_dict = self.project._get_dict()

        model_utils._check_conflicts(
            to_add=new_feature_name, data_model=self, project_dict=project_dict
        )

        feature_utils._check_draft_hierarchy(
            project_dict, self.name, hierarchy_name, level_name, expect_base_input=True
        )

        feature_utils._create_filter_attribute(
            self,
            project_dict=project_dict,
            new_feature_name=new_feature_name,
            hierarchy_name=hierarchy_name,
            level_name=level_name,
            filter_values=filter_values,
            caption=caption,
            description=description,
            folder=folder,
            visible=visible,
        )
        self.project._update_project(project_json=project_dict, publish=publish)

    def create_mapped_columns(
        self,
        dataset_name: str,
        column_name: str,
        mapped_names: List[str],
        data_types: List[MappedColumnDataTypes],
        key_terminator: MappedColumnKeyTerminator,
        field_terminator: MappedColumnFieldTerminator,
        map_key_type: MappedColumnDataTypes,
        map_value_type: MappedColumnDataTypes,
        first_char_delimited: bool = False,
        publish: bool = True,
    ):
        """Creates a mapped column.  Maps a column that is a key value structure into one or more new columns with the
        name of the given key(s). Types for the source keys and columns, and new columns are required. Valid types include
        'Int', 'Long', 'Boolean', 'String', 'Float', 'Double', 'Decimal', 'DateTime', and 'Date'.

        Args:
            dataset_name (str): The dataset the mapped column will be derived in.
            column_name (str): The name of the column to map.
            mapped_names (list str): The names of the mapped columns.
            data_types (list MappedColumnDataTypes): The types of the mapped columns.
            key_terminator (MappedColumnKeyTerminator): The key terminator. Valid values are ':', '=', and '^'
            field_terminator (MappedColumnFieldTerminator): The field terminator. Valid values are ',', ';', and '|'
            map_key_type (MappedColumnDataTypes): The mapping key type for all the keys in the origin column.
            map_value_type (MappedColumnDataTypes): The mapping value type for all values in the origin column.
            first_char_delimited (bool): Whether the first character is delimited. Defaults to False.
            publish (bool): Whether the updated project should be published. Defaults to True.
        """
        model_utils._perspective_check(self)

        inspection = getfullargspec(self.create_mapped_columns)
        validate_by_type_hints(inspection=inspection, func_params=locals())

        project_dict = self.project._get_dict()

        dset = project_parser.get_dataset(project_dict=project_dict, dataset_name=dataset_name)
        if not dset:
            raise atscale_errors.UserError(
                f"Invalid parameter: dataset name '{dataset_name}' does not exist"
            )
        if project_utils._check_if_qds(dset):
            raise atscale_errors.UserError(
                f"Invalid parameter: dataset name '{dataset_name}' is a qds and cannot have "
                f"calculated columns"
            )

        dset["physical"].setdefault("columns", [])
        dset_columns = [c["name"] for c in dset["physical"]["columns"]]

        model_utils._check_features(
            features=[column_name],
            check_list=dset_columns,
            errmsg=f"Invalid parameter: column name '{column_name}' does not exist in "
            f"dataset '{dataset_name}'",
        )

        feature_utils._create_mapped_columns(
            dataset=dset,
            column_name=column_name,
            mapped_names=mapped_names,
            data_types=data_types,
            key_terminator=key_terminator,
            field_terminator=field_terminator,
            map_key_type=map_key_type,
            map_value_type=map_value_type,
            first_char_delimited=first_char_delimited,
        )

        self.project._update_project(project_json=project_dict, publish=publish)

    def add_column_mapping(
        self,
        dataset_name: str,
        column_name: str,
        mapped_name: str,
        data_type: MappedColumnDataTypes,
        publish: bool = True,
    ):
        """Adds a new mapping to an existing column mapping

        Args:
            dataset_name (str): The dataset the mapping belongs to.
            column_name (str): The column the mapping belongs to.
            mapped_name (MappedColumnDataTypes): The name for the new mapped column.
            data_type (str): The data type of the new mapped column.
            publish (bool, optional): _description_. Defaults to True.
        """
        model_utils._perspective_check(self)

        inspection = getfullargspec(self.add_column_mapping)
        validate_by_type_hints(inspection=inspection, func_params=locals())

        project_dict = self.project._get_dict()

        if not self.dataset_exists(dataset_name, include_unused=True):
            raise atscale_errors.UserError(
                f"No dataset with the name {dataset_name} found in project"
            )

        if not model_utils._column_exists(project_dict, dataset_name, column_name):
            raise atscale_errors.UserError(
                f"Column '{column_name}' not found in the '{dataset_name}' dataset"
            )

        dset = project_parser.get_dataset(project_dict=project_dict, dataset_name=dataset_name)

        if "map-column" not in dset["physical"]:
            raise atscale_errors.UserError(
                f"No mapped column exists in the dataset. Use create_mapped_columns to create one"
            )

        mapping_cols = [c for c in dset["physical"]["map-column"] if c["name"] == column_name]
        if len(mapping_cols) < 1:
            raise atscale_errors.UserError(
                f"No mapped column exists for column: {mapped_name}. Use create_mapped_columns "
                f"to create one"
            )

        already_mapped_w_name = [
            col for col in mapping_cols[0]["columns"]["columns"] if col["name"] == mapped_name
        ]
        if already_mapped_w_name:
            raise atscale_errors.UserError(
                f"There is already a mapping on column '{column_name}' for the key '{mapped_name}'"
            )

        feature_utils._add_column_mapping(
            dataset=dset, column_name=column_name, mapped_name=mapped_name, data_type=data_type
        )

        self.project._update_project(project_json=project_dict, publish=publish)

    def create_calculated_column(
        self,
        dataset_name: str,
        column_name: str,
        expression: str,
        publish: bool = True,
    ):
        """Creates a new calculated column. A calculated column is a column whose value is calculated by a SQL
        expression (referencing one or more columns from the dataset) run at query time for each row.
        See AtScale documentation for more info on calculated columns.

        Args:
            dataset_name (str): The dataset the calculated column will be derived in.
            column_name (str): The name of the column.
            expression (str): The SQL expression for the column.
            publish (bool): Whether the updated project should be published. Defaults to True.

        Raises:
            atscale_errors.UserError: If the given dataset or column does not exist in the data model
        """
        model_utils._perspective_check(self)

        inspection = getfullargspec(self.create_calculated_column)
        validate_by_type_hints(inspection=inspection, func_params=locals())

        project_dict = self.project._get_dict()

        dset = project_parser.get_dataset(project_dict=project_dict, dataset_name=dataset_name)
        if not dset:
            raise atscale_errors.UserError(
                f"Invalid parameter: dataset name '{dataset_name}' does not exist"
            )
        if model_utils._column_exists(
            project_dict=project_dict, dataset_name=dataset_name, column_name=column_name
        ):
            raise atscale_errors.UserError(
                f"Invalid parameter: column_name '{column_name}' already exists in the given "
                f"dataset"
            )
        if project_utils._check_if_qds(dset):
            raise atscale_errors.UserError(
                f"Invalid parameter: dataset name '{dataset_name}' is a qds and cannot have "
                f"calculated columns"
            )

        project_utils.add_calculated_column_to_project_dataset(
            atconn=self.project._atconn,
            data_set=dset,
            column_name=column_name,
            expression=expression,
        )
        self.project._update_project(project_json=project_dict, publish=publish)

    def update_calculated_column(
        self,
        dataset_name: str,
        column_name: str,
        expression: str,
        publish: bool = True,
    ):
        """Updates the SQL expression for a calculated column.

        Args:
            dataset_name (str): The dataset the calculated column exists in.
            column_name (str): The name of the column.
            expression (str): The new SQL expression for the column.
            publish (bool): Whether the updated project should be published. Defaults to True.

        Raises:
            atscale_errors.UserError: If the given dataset or column does not exist in the data model
        """
        model_utils._perspective_check(self)

        inspection = getfullargspec(self.update_calculated_column)
        validate_by_type_hints(inspection=inspection, func_params=locals())

        project_dict = self.project._get_dict()

        dset = project_parser.get_dataset(project_dict=project_dict, dataset_name=dataset_name)
        if not dset:
            raise atscale_errors.UserError(
                f"Invalid parameter: dataset name '{dataset_name}' does not exist"
            )
        if project_utils._check_if_qds(dset):
            raise atscale_errors.UserError(
                f"Invalid parameter: dataset name '{dataset_name}' is a qds and cannot have "
                f"calculated columns"
            )
        if not model_utils._column_exists(
            project_dict=project_dict, dataset_name=dataset_name, column_name=column_name
        ):
            raise atscale_errors.UserError(
                f"Invalid parameter: column_name '{column_name}' does not exist in the given "
                f"dataset"
            )
        column = [
            x for x in dset.get("physical", {}).get("columns", []) if x["name"] == column_name
        ][0]
        dset["physical"]["columns"] = [
            x for x in dset.get("physical", {}).get("columns", []) if x["name"] != column_name
        ]
        project_utils.add_calculated_column_to_project_dataset(
            atconn=self.project._atconn,
            data_set=dset,
            column_name=column_name,
            expression=expression,
            column_id=column["id"],
        )
        self.project._update_project(project_json=project_dict, publish=publish)

    def validate_mdx(self, expression: str) -> str:
        """Verifies if the given MDX Expression is valid for the current data model.

        Args:
            expression (str): The MDX expression for the feature.
        Returns:
            str: The validation response.
        """
        response = model_utils._validate_mdx_syntax(self.project._atconn, expression, raises=False)
        if response == "":
            return "MDX syntax is valid"
        else:
            return response

    def create_calculated_feature(
        self,
        new_feature_name: str,
        expression: str,
        description: str = None,
        caption: str = None,
        folder: str = None,
        format_string: Union[FeatureFormattingType, str] = None,
        visible: bool = True,
        publish: bool = True,
    ):
        """Creates a new calculated feature given a query name and an MDX Expression.

        Args:
            new_feature_name (str): The query name of the new feature.
            expression (str): The MDX expression for the feature.
            description (str): The description for the feature. Defaults to None.
            caption (str): The caption for the feature. Defaults to None to use the new_feature_name.
            folder (str): The folder to put the feature in. Defaults to None.
            format_string (Union[FeatureFormattingType, str]): The format string for the feature. Defaults to None.
            visible (bool): Whether the feature will be visible to BI tools. Defaults to True.
            publish (bool): Whether the updated project should be published. Defaults to True.
        """
        model_utils._perspective_check(self)

        inspection = getfullargspec(self.create_calculated_feature)
        validate_by_type_hints(inspection=inspection, func_params=locals())

        project_json = self.project._get_dict()
        model_utils._check_conflicts(
            to_add=new_feature_name, data_model=self, project_dict=project_json
        )

        model_utils._validate_mdx_syntax(self.project._atconn, expression)

        feature_utils._create_calculated_feature(
            project_dict=project_json,
            cube_id=self.cube_id,
            name=new_feature_name,
            expression=expression,
            description=description,
            caption=caption,
            folder=folder,
            format_string=format_string,
            visible=visible,
        )

        self.project._update_project(project_json=project_json, publish=publish)

    def update_calculated_feature(
        self,
        feature_name: str,
        expression: str = None,
        description: str = None,
        caption: str = None,
        folder: str = None,
        format_string: Union[FeatureFormattingType, str] = None,
        visible: bool = None,
        publish: bool = True,
    ):
        """Update the metadata for a calculated feature.

        Args:
            feature_name (str): The query name of the feature to update.
            expression (str): The new expression for the feature. Defaults to None to leave unchanged.
            description (str): The new description for the feature. Defaults to None to leave unchanged.
            caption (str): The new caption for the feature. Defaults to None to leave unchanged.
            folder (str): The new folder to put the feature in. Defaults to None to leave unchanged.
            format_string (Union[FeatureFormattingType, str]): The new format string for the feature. Defaults to None to leave unchanged.
            visible (bool): Whether the updated feature should be visible. Defaults to None to leave unchanged.
            publish (bool): Whether the updated project should be published. Defaults to True.
        """
        model_utils._perspective_check(self)

        inspection = getfullargspec(self.update_calculated_feature)
        validate_by_type_hints(inspection=inspection, func_params=locals())

        project_dict = self.project._get_dict()
        calculated_measures = data_model_helpers._parse_calculated_features(
            data_model_name=self.name, project_dict=project_dict
        )

        if feature_name not in calculated_measures:
            raise atscale_errors.UserError(
                f"Invalid name: '{feature_name}'. A calculated measure with that name does not exist"
            )

        if expression is not None:
            model_utils._validate_mdx_syntax(self.project._atconn, expression)

        feature_utils._update_calculated_feature(
            project_dict=project_dict,
            feature_name=feature_name,
            expression=expression,
            description=description,
            caption=caption,
            folder=folder,
            format_string=format_string,
            visible=visible,
        )
        self.project._update_project(project_json=project_dict, publish=publish)

    def create_denormalized_categorical_feature(
        self,
        fact_dataset_name: str,
        column_name: str,
        new_feature_name: str,
        description: str = None,
        caption: str = None,
        folder: str = None,
        visible: bool = True,
        publish: bool = True,
    ):
        """Creates a new denormalized categorical feature.

        Args:
            fact_dataset_name (str): The name of the fact dataset to find the column_name.
            column_name (str): The column that the feature will use.
            new_feature_name (str): The query name of the new feature.
            description (str, optional): The description for the feature. Defaults to None.
            caption (str, optional): The caption for the feature. Defaults to None.
            folder (str, optional): The folder to put the feature in. Defaults to None.
            visible (bool, optional): Whether the feature will be visible to BI tools. Defaults to True.
            publish (bool, optional): Whether the updated project should be published. Defaults to True.
        """
        model_utils._perspective_check(self)

        inspection = getfullargspec(self.create_denormalized_categorical_feature)
        validate_by_type_hints(inspection=inspection, func_params=locals())

        project_dict = self.project._get_dict()
        model_utils._check_conflicts(
            to_add=new_feature_name, data_model=self, project_dict=project_dict
        )
        data_model_dict = model_utils._get_model_dict(self, project_dict=project_dict)[0]
        if not model_utils._get_fact_dataset(
            data_model_dict, project_dict, dataset_name=fact_dataset_name
        ):
            raise atscale_errors.UserError(
                f"Fact Dataset '{fact_dataset_name}' not associated with given model"
            )

        if not model_utils._column_exists(project_dict, fact_dataset_name, column_name):
            raise atscale_errors.UserError(
                f"Column '{column_name}' not found in the '{fact_dataset_name}' dataset"
            )

        data_set_project = project_parser.get_dataset(
            project_dict=project_dict, dataset_name=fact_dataset_name
        )
        dataset_id = data_set_project.get("id")
        dimension_utils.create_categorical_dimension_for_column(
            project_dict=project_dict,
            cube_id=self.cube_id,
            dataset_id=dataset_id,
            column_name=column_name,
            base_name=new_feature_name,
            description=description,
            caption=caption,
            folder=folder,
            visible=visible,
        )
        self.project._update_project(project_json=project_dict, publish=publish)

    def create_aggregate_feature(
        self,
        fact_dataset_name: str,
        column_name: str,
        new_feature_name: str,
        aggregation_type: Aggs,
        description: str = None,
        caption: str = None,
        folder: str = None,
        format_string: Union[FeatureFormattingType, str] = None,
        visible: bool = True,
        publish: bool = True,
    ):
        """Creates a new aggregate feature.

        Args:
            fact_dataset_name (str): The fact dataset containing the column that the feature will use.
            column_name (str): The column that the feature will use.
            new_feature_name (str): The query name of the new feature.
            aggregation_type (atscale.utils.enums.Aggs): What aggregation method to use for the feature. Example: Aggs.MAX
                Valid options can be found in utils.Aggs
            description (str): The description for the feature. Defaults to None.
            caption (str): The caption for the feature. Defaults to None.
            folder (str): The folder to put the feature in. Defaults to None.
            format_string (Union[FeatureFormattingType, str]): The format string for the feature. Defaults to None.
            visible (bool, optional): Whether the feature will be visible to BI tools. Defaults to True.
            publish (bool): Whether the updated project should be published. Defaults to True.
        """
        model_utils._perspective_check(self)

        inspection = getfullargspec(self.create_aggregate_feature)
        validate_by_type_hints(inspection=inspection, func_params=locals())

        project_dict = self.project._get_dict()
        model_utils._check_conflicts(
            to_add=new_feature_name, data_model=self, project_dict=project_dict
        )

        data_model_dict = model_utils._get_model_dict(self, project_dict=project_dict)[0]
        dset = model_utils._get_fact_dataset(
            data_model_dict, project_dict, dataset_name=fact_dataset_name
        )
        if not dset:
            raise atscale_errors.UserError(
                f"Fact Dataset '{fact_dataset_name}' not associated with given model"
            )

        if not model_utils._column_exists(project_dict, fact_dataset_name, column_name):
            raise atscale_errors.UserError(
                f"Column '{column_name}' not found in the '{fact_dataset_name}' dataset"
            )
        dataset_id = dset["id"]

        feature_utils._create_aggregate_feature(
            project_dict=project_dict,
            cube_id=self.cube_id,
            dataset_id=dataset_id,
            column_name=column_name,
            new_feature_name=new_feature_name,
            aggregation_type=aggregation_type,
            description=description,
            caption=caption,
            folder=folder,
            format_string=format_string,
            visible=visible,
        )

        self.project._update_project(project_json=project_dict, publish=publish)

    def update_aggregate_feature(
        self,
        feature_name: str,
        description: str = None,
        caption: str = None,
        folder: str = None,
        format_string: Union[FeatureFormattingType, str] = None,
        visible: bool = None,
        publish: bool = True,
    ):
        """Update the metadata for an aggregate feature.

        Args:
            feature_name (str): The query name of the feature to update.
            description (str): The new description for the feature. Defaults to None to leave unchanged.
            caption (str): The new caption for the feature. Defaults to None to leave unchanged.
            folder (str): The new folder to put the feature in. Defaults to None to leave unchanged.
            format_string (Union[FeatureFormattingType, str]): The new format string for the feature. Defaults to None to leave unchanged.
            visible (bool, optional): Whether the feature will be visible to BI tools. Defaults to None to leave unchanged.
            publish (bool): Whether the updated project should be published. Defaults to True.

        Raises:
            atscale_error.UserError: If the given name does not exist in the data model.
        """
        model_utils._perspective_check(self)

        inspection = getfullargspec(self.update_aggregate_feature)
        validate_by_type_hints(inspection=inspection, func_params=locals())

        project_json = self.project._get_dict()
        agg_features = data_model_helpers._parse_aggregate_features(
            data_model_name=self.name, project_dict=project_json
        )

        if feature_name not in agg_features:
            raise atscale_errors.UserError(
                f"Invalid name: '{feature_name}'. A feature with that name does not exist"
            )

        feature_utils._update_aggregate_feature(
            project_dict=project_json,
            cube_id=self.cube_id,
            feature_name=feature_name,
            description=description,
            caption=caption,
            folder=folder,
            format_string=format_string,
            visible=visible,
        )

        self.project._update_project(project_json=project_json, publish=publish)

    def create_rolling_features(
        self,
        new_feature_name: str,
        numeric_feature_name: str,
        hierarchy_name: str,
        level_name: str,
        time_length: int,
        aggregation_types: List[MDXAggs] = None,
        description: str = None,
        caption: str = None,
        folder: str = None,
        format_string: Union[FeatureFormattingType, str] = None,
        visible: bool = True,
        publish: bool = True,
    ) -> List[str]:
        """Creates a rolling calculated numeric feature for the given column. If no list of MDXAggs is provided, rolling calc features
            will be made for Sum, Mean, Min, Max, and Stdev

        Args:
            new_feature_name (str): The query name for the new feature, will be suffixed with the agg type if multiple are
                being created.
            numeric_feature_name (str): The query name of the numeric feature to use for the calculation
            hierarchy_name (str): The query name of the time hierarchy used in the calculation
            level_name (str): The query name of the level within the time hierarchy
            time_length (int): The length of time the feature should be calculated over
            aggregation_types (List[MDXAggs], optional): The type of aggregation to do for the rolling calc. If none, all agg
                types are used.
            description (str, optional): The description for the feature. Defaults to None.
            caption (str, optional): The caption for the feature. Defaults to None.
            folder (str, optional): The folder to put the feature in. Defaults to None.
            format_string (Union[FeatureFormattingType, str], optional): The format string for the feature. Defaults to None.
            visible (bool, optional): Whether the feature will be visible to BI tools. Defaults to True.
            publish (bool, optional): Whether or not the updated project should be published. Defaults to True.)

        Returns:
            List[str]: A list containing the names of the newly-created features.
        """
        model_utils._perspective_check(self)

        inspection = getfullargspec(self.create_rolling_features)
        validate_by_type_hints(inspection=inspection, func_params=locals())

        if not (type(time_length) == int) or time_length < 1:
            raise ValueError(
                f"Invalid parameter value '{time_length}', Length must be an integer greater than zero"
            )

        proj_dict = self.project._get_dict()

        # Check to see that features passed exist in first place
        model_utils._check_features(
            features=[numeric_feature_name],
            check_list=data_model_helpers._get_draft_features(
                project_dict=proj_dict,
                data_model_name=self.name,
                feature_type=FeatureType.ALL,
            ).keys(),
            errmsg=CheckFeaturesErrMsg.ALL.get_errmsg(is_published=False),
        )

        # Check to see that features passed are numeric
        model_utils._check_features(
            features=[numeric_feature_name],
            check_list=data_model_helpers._get_draft_features(
                project_dict=proj_dict,
                data_model_name=self.name,
                feature_type=FeatureType.NUMERIC,
            ).keys(),
            errmsg=CheckFeaturesErrMsg.NUMERIC.get_errmsg(is_published=False),
        )

        # make sure the input is a list
        if aggregation_types is None:
            aggregation_types = [x for x in MDXAggs]

        if type(aggregation_types) != list:
            aggregation_types = [aggregation_types]

        # validate that the columns we are about to make don't already exist.
        project_json = self.project._get_dict()
        measure_list = data_model_helpers._get_draft_features(
            project_dict=project_json, data_model_name=self.name
        )
        if len(aggregation_types) > 1:
            new_feature_names = [new_feature_name + "_" + x.name for x in aggregation_types]
        else:
            new_feature_names = [new_feature_name]

        model_utils._check_conflicts(
            to_add=new_feature_names,
            preexisting=measure_list,
            errmsg="Invalid names: The following features about to be created, {}, "
            "already exist in the model",
        )

        hier_dict, level_dict = feature_utils._check_time_hierarchy(
            data_model=self, hierarchy_name=hierarchy_name, level_name=level_name
        )

        time_dimension = hier_dict[hierarchy_name][Hierarchy.dimension.name]

        for i in range(len(aggregation_types)):
            aggregation_type = aggregation_types[i]
            feat_name = new_feature_names[i]

            feature_utils._create_rolling_agg(
                project_json,
                cube_id=self.cube_id,
                time_dimension=time_dimension,
                agg_type=aggregation_type,
                new_feature_name=feat_name,
                numeric_feature_name=numeric_feature_name,
                time_length=time_length,
                hierarchy_name=hierarchy_name,
                level_name=level_name,
                description=description,
                caption=caption,
                folder=folder,
                format_string=format_string,
                visible=visible,
            )

        self.project._update_project(project_json=project_json, publish=publish)

        new_feature_names_string = ", ".join(new_feature_names)

        logger.info(
            f'Successfully created measures \'{new_feature_names_string}\' {f"in folder {folder}" if folder else ""}'
        )

        return new_feature_names

    def create_lag_feature(
        self,
        new_feature_name: str,
        numeric_feature_name: str,
        hierarchy_name: str,
        level_name: str,
        time_length: int,
        description: str = None,
        caption: str = None,
        folder: str = None,
        format_string: Union[FeatureFormattingType, str] = None,
        visible: bool = True,
        publish: bool = True,
    ):
        """Creates a lagged feature based on the numeric feature and time hierarchy passed in.

        Args:
            new_feature_name (str): The query name of the feature to create.
            numeric_feature_name (str): The query name of the numeric feature to lag.
            hierarchy_name (str): The query name of the time hierarchy to use for lagging.
            level_name (str): The query name of the hierarchy level to use for lagging.
            time_length (int): The length of the lag.
            description (str, optional): A description for the feature. Defaults to None.
            caption (str, optional): A caption for the feature. Defaults to None.
            folder (str, optional): The folder to put the feature in. Defaults to None.
            format_string (Union[FeatureFormattingType, str], optional): A format sting for the feature. Defaults to None.
            visible (bool, optional): Whether the feature should be visible. Defaults to True.
            publish (bool, optional): Whether to publish the project after creating the feature. Defaults to True.
        """
        model_utils._perspective_check(self)

        inspection = getfullargspec(self.create_lag_feature)
        validate_by_type_hints(inspection=inspection, func_params=locals())

        project_json = self.project._get_dict()
        existing_features = data_model_helpers._get_draft_features(
            project_dict=project_json, data_model_name=self.name
        )

        features = [numeric_feature_name]
        check_list = data_model_helpers._get_draft_features(
            feature_type=FeatureType.NUMERIC,
            project_dict=project_json,
            data_model_name=self.name,
        )

        # Check to see that features passed exist in first place
        model_utils._check_features(
            features=features,
            check_list=data_model_helpers._get_draft_features(
                project_dict=project_json,
                data_model_name=self.name,
                feature_type=FeatureType.ALL,
            ).keys(),
            errmsg=CheckFeaturesErrMsg.ALL.get_errmsg(is_published=False),
        )

        # Check to see that features passed are numeric
        model_utils._check_features(
            features=features,
            check_list=check_list,
            errmsg=CheckFeaturesErrMsg.NUMERIC.get_errmsg(is_published=False),
        )

        model_utils._check_conflicts(to_add=new_feature_name, preexisting=existing_features)

        if not (type(time_length) == int) or time_length <= 0:
            raise ValueError(
                f"Invalid parameter value '{time_length}', Length must be an integer greater than zero"
            )

        hier_dict, _ = feature_utils._check_time_hierarchy(
            data_model=self,
            hierarchy_name=hierarchy_name,
            level_name=level_name,
        )

        time_dimension = hier_dict[hierarchy_name][Hierarchy.dimension.name]

        # the project dict that will be edited by the operation

        feature_utils._create_lag_feature(
            project_dict=project_json,
            cube_id=self.cube_id,
            time_dimension=time_dimension,
            new_feature_name=new_feature_name,
            numeric_feature_name=numeric_feature_name,
            hierarchy_name=hierarchy_name,
            level_name=level_name,
            time_length=time_length,
            description=description,
            caption=caption,
            folder=folder,
            format_string=format_string,
            visible=visible,
        )
        self.project._update_project(project_json=project_json, publish=publish)

    def create_time_differencing_feature(
        self,
        new_feature_name: str,
        numeric_feature_name: str,
        hierarchy_name: str,
        level_name: str,
        time_length: int,
        description: str = None,
        caption: str = None,
        folder: str = None,
        format_string: Union[str, FeatureFormattingType] = None,
        visible: bool = True,
        publish: bool = True,
    ):
        """Creates a time over time subtraction calculation. For example, create_time_differencing on the feature 'revenue'
        , time level 'date', and a length of 2 will create a feature calculating the revenue today subtracted by the revenue
        two days ago

        Args:
            new_feature_name (str): The query name of the feature to create.
            numeric_feature_name (str): The query name of the numeric feature to use for the calculation.
            hierarchy_name (str): The query name of the time hierarchy used in the calculation.
            level_name (str): The query name of the level within the time hierarchy
            time_length (int): The length of the lag in units of the given level of the given hierarchy.
            description (str): The description for the feature. Defaults to None.
            caption (str): The caption for the feature. Defaults to None.
            folder (str): The folder to put the feature in. Defaults to None.
            format_string (Union[FeatureFormattingType, str]): The format string for the feature. Defaults to None.
            visible (bool, optional): Whether the feature should be visible. Defaults to True.
            publish (bool): Whether the updated project should be published. Defaults to True.
        """
        model_utils._perspective_check(self)

        inspection = getfullargspec(self.create_time_differencing_feature)
        validate_by_type_hints(inspection=inspection, func_params=locals())

        project_json = self.project._get_dict()

        existing_features = data_model_helpers._get_draft_features(
            project_dict=project_json, data_model_name=self.name
        )

        existing_measures = list(
            dictionary_parser.filter_dict(
                to_filter=existing_features,
                val_filters=[lambda i: i["feature_type"] == FeatureType.NUMERIC.name_val],
            ).keys()
        )

        # Check to see that features passed exist in first place
        model_utils._check_features(
            features=[numeric_feature_name],
            check_list=existing_features,
            errmsg=CheckFeaturesErrMsg.ALL.get_errmsg(is_published=False),
        )

        # Check to see that features passed are numeric
        model_utils._check_features(
            features=[numeric_feature_name],
            check_list=existing_measures,
            errmsg=CheckFeaturesErrMsg.NUMERIC.get_errmsg(is_published=False),
        )

        if not (type(time_length) == int) or time_length < 1:
            raise ValueError(
                f"Invalid parameter value '{time_length}', Length must be an integer greater than zero"
            )
        model_utils._check_conflicts(to_add=new_feature_name, preexisting=existing_features)

        hier_dict, _ = feature_utils._check_time_hierarchy(
            data_model=self, hierarchy_name=hierarchy_name, level_name=level_name
        )

        time_dimension = hier_dict[hierarchy_name][Hierarchy.dimension.name]

        feature_utils._create_time_differencing_feature(
            project_dict=project_json,
            cube_id=self.cube_id,
            time_dimension=time_dimension,
            new_feature_name=new_feature_name,
            numeric_feature_name=numeric_feature_name,
            hierarchy_name=hierarchy_name,
            level_name=level_name,
            time_length=time_length,
            description=description,
            caption=caption,
            folder=folder,
            format_string=format_string,
            visible=visible,
        )

        self.project._update_project(project_json=project_json, publish=publish)

    def create_percentage_features(
        self,
        numeric_feature_name: str,
        hierarchy_name: str,
        level_names: List[str] = None,
        new_feature_names: List[str] = None,
        description: str = None,
        caption: str = None,
        folder: str = None,
        format_string: Union[FeatureFormattingType, str] = None,
        visible: bool = True,
        publish: bool = True,
    ):
        """Creates a set of features calculating the percentage of the given numeric_feature's value compared to each non-leaf
        (i.e. non-base) level in the hierarchy

        Args:
            numeric_feature_name (str): The query name of the numeric feature to use for the calculation
            hierarchy_name (str): The query name of the hierarchy to use for comparisons
            level_names (List[str], optional): The query names for the subset of levels to make percentages for, if None
                generates percentages for all non-leaf levels. Defaults to None.
            new_feature_names (List[str], optional): The query names of the new columns, if None generates
                names. If not None it must be same length and order as level_names. Defaults to None.
            description (str, optional): The description for the feature. Defaults to None.
            caption (str, optional): The caption for the new features. Defaults to None.
            folder (str, optional): The folder to put the new features in. Defaults to None.
            format_string (Union[FeatureFormattingType, str], optional): The format string for the features. Defaults to None.
            visible (bool, optional): Whether the feature will be visible to BI tools. Defaults to True.
            publish (bool, optional): Whether or not the updated project should be published. Defaults to True.
        """
        model_utils._perspective_check(self)

        inspection = getfullargspec(self.create_percentage_features)
        validate_by_type_hints(inspection=inspection, func_params=locals())

        hier_dict, _ = feature_utils._check_time_hierarchy(
            data_model=self, hierarchy_name=hierarchy_name
        )

        dimension_name = hier_dict[hierarchy_name][Hierarchy.dimension.name]
        project_dict = self.project._get_dict()
        measure_list = data_model_helpers._get_draft_features(
            project_dict=project_dict, data_model_name=self.name, feature_type=FeatureType.NUMERIC
        )
        level_list = list(
            get_dmv_data(
                model=self,
                fields=[Level.name, Level.hierarchy],
                filter_by={Level.hierarchy: [hierarchy_name]},
            ).keys()
        )

        # Check to see that features passed exist in first place
        model_utils._check_features(
            features=[numeric_feature_name],
            check_list=data_model_helpers._get_draft_features(
                project_dict=project_dict,
                data_model_name=self.name,
                feature_type=FeatureType.ALL,
            ).keys(),
            errmsg=CheckFeaturesErrMsg.ALL.get_errmsg(is_published=False),
        )

        # Check to see that features passed are numeric
        model_utils._check_features(
            features=[numeric_feature_name],
            check_list=data_model_helpers._get_draft_features(
                project_dict=project_dict,
                data_model_name=self.name,
                feature_type=FeatureType.NUMERIC,
            ).keys(),
            errmsg=CheckFeaturesErrMsg.NUMERIC.get_errmsg(is_published=False),
        )

        # some error checking on the levels
        if level_names:
            if type(level_names) != list:
                level_names = [level_names]
            missing_levels = [x for x in level_names if x not in level_list]
            if missing_levels:
                raise atscale_errors.UserError(
                    f'Level name{"s" if len(missing_levels) > 1 else ""}: {", ".join(missing_levels)} not found '
                    f"in Hierarchy: {hierarchy_name}"
                )
            elif level_list[-1] in level_names:
                raise atscale_errors.UserError(
                    f"Cannot create percentage for leaf node of hierarchy: {level_list[-1]}"
                )
        else:
            level_names = level_list[:-1]

        if (new_feature_names is not None) and (len(new_feature_names) != len(level_names)):
            raise atscale_errors.UserError(
                f"Length of new_feature_names must equal length of level_names"
            )

        if not new_feature_names:
            new_feature_names = [numeric_feature_name + "% of " + level for level in level_names]

        model_utils._check_conflicts(
            data_model=self, to_add=new_feature_names, project_dict=project_dict
        )

        for lev_index, level in enumerate(level_names):
            name = new_feature_names[lev_index]
            feature_utils._create_percentage_feature(
                project_dict=project_dict,
                cube_id=self.cube_id,
                new_feature_name=name,
                numeric_feature_name=numeric_feature_name,
                dimension_name=dimension_name,
                hierarchy_name=hierarchy_name,
                level_name=level,
                description=description,
                caption=caption,
                folder=folder,
                format_string=format_string,
                visible=visible,
            )

        self.project._update_project(project_json=project_dict, publish=publish)

    def create_period_to_date_features(
        self,
        numeric_feature_name: str,
        hierarchy_name: str,
        new_feature_names: List[str] = None,
        level_names: List[str] = None,
        description: str = None,
        folder: str = None,
        format_string: Union[FeatureFormattingType, str] = None,
        visible: bool = True,
        publish: bool = True,
    ) -> str:
        """Creates a period-to-date calculation

        Args:
            numeric_feature_name (str): The query name of the numeric feature to use for the calculation
            hierarchy_name (str): The query name of the time hierarchy used in the calculation
            level_names (List[str], optional): The query names for the subset of levels to make period to date calcs for, if
                None generates period to date for all non-leaf levels. Defaults to None.
            new_feature_names (List[str], optional): The query names of the new columns, if None generates
                names. If not None it must be same length and order as level_names. Defaults to None.
            description (str, optional): The description for the feature. Defaults to None.
            folder (str, optional): The folder to put the feature in. Defaults to None.
            format_string (Union[FeatureFormattingType, str], optional): The format string for the feature. Defaults to None.
            visible (bool, optional): Whether the feature will be visible to BI tools. Defaults to True.
            publish (bool, optional): Whether the updated project should be published. Defaults to True.

        Returns:
            str: A message containing the names of successfully created features
        """
        model_utils._perspective_check(self)

        inspection = getfullargspec(self.create_period_to_date_features)
        validate_by_type_hints(inspection=inspection, func_params=locals())

        project_json = self.project._get_dict()
        hier_dict, _ = feature_utils._check_time_hierarchy(
            data_model=self, hierarchy_name=hierarchy_name
        )
        time_dimension = hier_dict[hierarchy_name][Hierarchy.dimension.name]

        level_list = list(
            get_dmv_data(
                model=self,
                fields=[Level.name, Level.hierarchy],
                filter_by={Level.hierarchy: [hierarchy_name]},
            ).keys()
        )
        measure_list = data_model_helpers._get_draft_features(
            project_dict=project_json, data_model_name=self.name, feature_type=FeatureType.NUMERIC
        )

        # Check to see that features passed exist in first place
        model_utils._check_features(
            features=[numeric_feature_name],
            check_list=data_model_helpers._get_draft_features(
                project_dict=project_json,
                data_model_name=self.name,
                feature_type=FeatureType.ALL,
            ).keys(),
            errmsg=CheckFeaturesErrMsg.ALL.get_errmsg(is_published=False),
        )

        # Check to see that features passed are numeric
        model_utils._check_features(
            features=[numeric_feature_name],
            check_list=measure_list,
            errmsg=CheckFeaturesErrMsg.NUMERIC.get_errmsg(is_published=False),
        )

        # some error checking on the levels
        if level_names:
            if type(level_names) != list:
                level_names = [level_names]
            missing_levels = [x for x in level_names if x not in level_list]
            if missing_levels:
                raise atscale_errors.UserError(
                    f'Level name{"s" if len(missing_levels) > 1 else ""}: {missing_levels} not found '
                    f"in Hierarchy: {hierarchy_name}"
                )
            elif level_list[-1] in level_names:
                raise atscale_errors.UserError(
                    f"Cannot create period for leaf node of hierarchy: {level_list[-1]}"
                )
        else:
            level_names = level_list[:-1]

        if (new_feature_names is not None) and (len(new_feature_names) != len(level_names)):
            raise atscale_errors.UserError(
                f"Length of new_feature_names must equal length of level_names"
            )

        base_level = level_list[-1]
        if not new_feature_names:
            new_feature_names = [
                numeric_feature_name + "_" + level + "_To_" + base_level for level in level_names
            ]

        model_utils._check_conflicts(
            data_model=self, to_add=new_feature_names, project_dict=project_json
        )

        for lev_index, level in enumerate(level_names):
            name = new_feature_names[lev_index]
            feature_utils._create_period_to_date_feature(
                project_dict=project_json,
                cube_id=self.cube_id,
                new_feature_name=name,
                numeric_feature_name=numeric_feature_name,
                hierarchy_name=hierarchy_name,
                level_name=level,
                base_name=base_level,
                time_dimension=time_dimension,
                description=description,
                folder=folder,
                format_string=format_string,
                visible=visible,
            )

        self.project._update_project(project_json=project_json, publish=publish)

    def get_dimensions(self) -> Dict:
        """Gets a dictionary of dictionaries with the published dimension names and metadata.

        Returns:
            dict: A dictionary of dictionaries where the dimension names are the keys in the outer dictionary
                while the inner keys are the following: 'description', 'type'(value is Time or Standard).
        """
        filter_by = {}
        return metadata_utils._get_dimensions(self, filter_by=filter_by)

    def create_dimension(
        self,
        new_dimension_name: str,
        new_hierarchy_name: str,
        new_level_name: str,
        dataset_name: str,
        level_value_column: str,
        level_key_columns: List[str] = None,
        time_dimension: bool = False,
        dimension_description: str = "",
        hierarchy_caption: str = None,
        hierarchy_description: str = "",
        hierarchy_folder: str = "",
        level_type: TimeSteps = TimeSteps.Regular,
        level_caption: str = None,
        level_description: str = "",
        publish: bool = True,
    ):
        """Creates a dimension with one hierarchy and level

        Args:
            new_dimension_name (str): The name of the new dimension to create.
            new_hierarchy_name (str): The name of the hierarchy to create in the dimension.
            new_level_name (str): The name of the level in the new hierarchy.
            dataset_name (str): The name of the dataset to use.
            level_value_column (str): The value column in the dataset to use for the level.
            level_key_columns (List[str], optional):  The key columns in the dataset to use for the level. Defaults to None to use the value column.
            time_dimension (bool, optional): Whether to flag the dimension as a time dimension. Defaults to False.
            dimension_description (str, optional): The description for the dimension. Defaults to "".
            hierarchy_caption (str, optional): The caption for the heirarchy Defaults to None to use new_hierarchy_name.
            hierarchy_description (str, optional): The description for the hierarchy. Defaults to "".
            hierarchy_folder (str, optional): The folder for the hierarchy. Defaults to "".
            level_type (TimeSteps, optional): The TimeSteps for the level if time based. Defaults to TimeSteps.Regular.
            level_caption (str, optional): The caption for the level. Defaults to None to use new_level_name.
            level_description (str, optional): The description for the level. Defaults to "".
            publish (bool, optional): Whether the updated project should be published. Defaults to True.
        """
        model_utils._perspective_check(self)

        inspection = getfullargspec(self.create_dimension)
        validate_by_type_hints(inspection=inspection, func_params=locals())

        project_dict = self.project._get_dict()
        cube = project_parser.get_cube(project_dict=project_dict, id=self.cube_id)

        for dimension in project_dict.get("dimensions", {}).get("dimension", []) + cube.get(
            "dimensions", {}
        ).get("dimension", []):
            if dimension["name"] == new_dimension_name:
                raise atscale_errors.UserError(
                    f"A dimension named '{new_dimension_name}' already exists in the given model"
                )
            for hierarchy in dimension.get("hierarchy", []):
                if hierarchy.get("name") == new_hierarchy_name:
                    raise atscale_errors.UserError(
                        f"A hierarchy named '{new_hierarchy_name}' already exists in the given model"
                    )

        model_utils._check_conflicts(
            to_add=new_level_name, data_model=self, project_dict=project_dict
        )

        dset = project_parser.get_dataset(project_dict, dataset_name=dataset_name)

        if not dset:
            raise atscale_errors.UserError(
                f"Dataset '{dataset_name}' not associated with the project"
            )

        if not self.dataset_exists(dataset_name, include_unused=False):
            raise atscale_errors.UserError(
                f"Dataset '{dataset_name}' not associated with given model"
            )

        if not model_utils._column_exists(project_dict, dataset_name, level_value_column):
            raise atscale_errors.UserError(
                f"Column '{level_value_column}' not found in the '{dataset_name}' dataset"
            )
        if level_key_columns:
            for column in level_key_columns:
                if not model_utils._column_exists(project_dict, dataset_name, column):
                    raise atscale_errors.UserError(
                        f"Column '{column}' not found in the '{dataset_name}' dataset"
                    )
        if time_dimension:
            if level_type == TimeSteps.Regular:
                raise atscale_errors.UserError(
                    f"level_type cannot be TimeSteps.Regular for time dimensions"
                )
        else:
            if level_type != TimeSteps.Regular:
                raise atscale_errors.UserError(
                    f"level_type must be TimeSteps.Regular for non time dimensions"
                )

        dimension_utils.create_dimension(
            project_dict=project_dict,
            cube_id=self.cube_id,
            name=new_dimension_name,
            time_dimension=time_dimension,
            description=dimension_description,
        )
        dimension_utils.create_hierarchy(
            project_dict=project_dict,
            cube_id=self.cube_id,
            name=new_hierarchy_name,
            dimension_name=new_dimension_name,
            dataset_name=dataset_name,
            caption=hierarchy_caption,
            description=hierarchy_description,
            folder=hierarchy_folder,
        )
        dimension_utils.create_level(
            project_dict=project_dict,
            cube_id=self.cube_id,
            level_name=new_level_name,
            dataset_name=dataset_name,
            value_column=level_value_column,
            key_columns=level_key_columns,
            level_type=level_type,
            hierarchy_name=new_hierarchy_name,
            caption=level_caption,
            description=level_description,
        )
        self.project._update_project(project_dict, publish)

    def update_dimension(self, dimension_name: str, description: str = None, publish: bool = True):
        """Update the metadata for the given dimension

        Args:
            dimension_name (str): The name of the dimension to update.
            description (str, optional): The new description for the dimension. Defaults to None to not change.
            publish (bool, optional): Whether the updated project should be published. Defaults to True.
        """
        model_utils._perspective_check(self)

        inspection = getfullargspec(self.update_dimension)
        validate_by_type_hints(inspection=inspection, func_params=locals())

        project_dict = self.project._get_dict()
        cube = project_parser.get_cube(project_dict=project_dict, id=self.cube_id)
        dim = [
            x
            for x in project_dict.get("dimensions", {}).get("dimension", [])
            + cube.get("dimensions", {}).get("dimension", [])
            if x.get("name") == dimension_name
        ][0]
        if dim:
            if description is not None:
                dim["properties"]["description"] = description
        else:
            raise ValueError(
                f"No dimension {dimension_name} found make sure you are using non roleplayed names."
            )
        self.project._update_project(project_dict, publish)

    def create_hierarchy(
        self,
        new_hierarchy_name: str,
        dimension_name: str,
        new_level_name: str,
        dataset_name: str,
        level_value_column: str,
        level_key_columns: List[str] = None,
        hierarchy_caption: str = None,
        hierarchy_description: str = "",
        hierarchy_folder: str = "",
        level_type: TimeSteps = TimeSteps.Regular,
        level_caption: str = None,
        level_description: str = "",
        publish: bool = True,
    ):
        """Creates a hierarchy with one level

        Args:
            new_hierarchy_name (str): The name of the hierarchy to create in the dimension.
            dimension_name (str): Thedimension to add the hierarchy to.
            new_level_name (str): The name of the level in the new hierarchy.
            dataset_name (str): The name of the dataset to use.
            level_value_column (str): The value column in the dataset to use for the level.
            level_key_columns (List[str], optional):  The key columns in the dataset to use for the level. Defaults to None to use the value column.
            hierarchy_caption (str, optional): The caption for the heirarchy Defaults to None to use new_hierarchy_name.
            hierarchy_description (str, optional): The description for the hierarchy. Defaults to "".
            hierarchy_folder (str, optional): The folder for the hierarchy. Defaults to "".
            level_type (TimeSteps, optional): The TimeSteps for the level if time based. Defaults to TimeSteps.Regular.
            level_caption (str, optional): The caption for the level. Defaults to None to use new_level_name.
            level_description (str, optional): The description for the level. Defaults to "".
            publish (bool, optional): Whether the updated project should be published. Defaults to True.
        """
        model_utils._perspective_check(self)

        inspection = getfullargspec(self.create_hierarchy)
        validate_by_type_hints(inspection=inspection, func_params=locals())

        project_dict = self.project._get_dict()
        cube = project_parser.get_cube(project_dict=project_dict, id=self.cube_id)

        model_utils._check_conflicts(
            to_add=new_level_name, data_model=self, project_dict=project_dict
        )

        dset = project_parser.get_dataset(project_dict, dataset_name=dataset_name)

        if not dset:
            raise atscale_errors.UserError(
                f"Dataset '{dataset_name}' not associated with the project"
            )

        if not self.dataset_exists(dataset_name, include_unused=False):
            raise atscale_errors.UserError(
                f"Dataset '{dataset_name}' not associated with given model"
            )

        if not model_utils._column_exists(project_dict, dataset_name, level_value_column):
            raise atscale_errors.UserError(
                f"Column '{level_value_column}' not found in the '{dataset_name}' dataset"
            )
        if level_key_columns:
            for column in level_key_columns:
                if not model_utils._column_exists(project_dict, dataset_name, column):
                    raise atscale_errors.UserError(
                        f"Column '{column}' not found in the '{dataset_name}' dataset"
                    )
        dimension_found = False
        for dimension in project_dict.get("dimensions", {}).get("dimension", []) + cube.get(
            "dimensions", {}
        ).get("dimension", []):
            if dimension["name"] == dimension_name:
                dimension_found = True
                dimension_type = dimension["properties"].get("dimension-type", "non-time")
            for hierarchy in dimension.get("hierarchy", []):
                if hierarchy.get("name") == new_hierarchy_name:
                    raise atscale_errors.UserError(
                        f"A hierarchy named '{new_hierarchy_name}' already exists in the given model"
                    )

        if not dimension_found:
            raise atscale_errors.UserError(
                f"Dimension: '{dimension_name}' not found. Make sure you are not using roleplayed names."
            )

        if dimension_type == "Time":
            if level_type == TimeSteps.Regular:
                raise atscale_errors.UserError(
                    f"level_type cannot be TimeSteps.Regular for time dimensions"
                )
        else:
            if level_type != TimeSteps.Regular:
                raise atscale_errors.UserError(
                    f"level_type must be TimeSteps.Regular for non time dimensions"
                )

        project_dict = self.project._get_dict()
        dimension_utils.create_hierarchy(
            project_dict=project_dict,
            cube_id=self.cube_id,
            name=new_hierarchy_name,
            dimension_name=dimension_name,
            dataset_name=dataset_name,
            caption=hierarchy_caption,
            description=hierarchy_description,
            folder=hierarchy_folder,
        )
        dimension_utils.create_level(
            project_dict=project_dict,
            cube_id=self.cube_id,
            level_name=new_level_name,
            dataset_name=dataset_name,
            value_column=level_value_column,
            key_columns=level_key_columns,
            level_type=level_type,
            hierarchy_name=new_hierarchy_name,
            caption=level_caption,
            description=level_description,
        )
        self.project._update_project(project_dict, publish)

    def update_hierarchy(
        self,
        hierarchy_name: str,
        caption: str = None,
        description: str = None,
        folder: str = None,
        default_member_expression: str = None,
        publish: bool = True,
    ):
        """Update the metadata for the given hierarchy

        Args:
            hierarchy_name (str): The name of the hierarchy to update.
            caption (str, optional): The new caption for the hierarchy. Defaults to None to not change.
            description (str, optional): The new description for the hierarchy. Defaults to None to not change.
            folder (str, optional): The new folder for the hierarchy. Defaults to None to not change.
            default_member_expression (str, optional): The expression for the default member. Defaults to None to not change.
            publish (bool, optional): Whether the updated project should be published. Defaults to True.
        """
        model_utils._perspective_check(self)

        inspection = getfullargspec(self.update_hierarchy)
        validate_by_type_hints(inspection=inspection, func_params=locals())

        project_dict = self.project._get_dict()
        cube = project_parser.get_cube(project_dict=project_dict, id=self.cube_id)
        hierarchy_found = False
        for dimension in project_dict.get("dimensions", {}).get("dimension", []) + cube.get(
            "dimensions", {}
        ).get("dimension", []):
            for hierarchy in dimension.get("hierarchy", []):
                if hierarchy.get("name") == hierarchy_name:
                    hierarchy_found = True
                    if description is not None:
                        hierarchy["properties"]["description"] = description
                    if caption is not None:
                        hierarchy["properties"]["caption"] = caption
                    if folder is not None:
                        hierarchy["properties"]["folder"] = folder
                    if default_member_expression is not None:
                        if default_member_expression == "":
                            hierarchy["properties"]["default-member"] = {"all-member": {}}
                        else:
                            model_utils._validate_mdx_syntax(
                                self.project._atconn, expression=default_member_expression
                            )
                            hierarchy["properties"]["default-member"] = {
                                "literal-member": default_member_expression
                            }
                    break
        if not hierarchy_found:
            raise atscale_errors.UserError(
                f"Hierarchy: '{hierarchy_name}' not found, make sure you are using non roleplayed names."
            )

        self.project._update_project(project_dict, publish)

    def add_level_to_hierarchy(
        self,
        new_level_name: str,
        hierarchy_name: str,
        dataset_name: str,
        value_column: str,
        existing_level: str,
        key_columns: List[str] = None,
        add_above_existing: bool = True,
        level_type: TimeSteps = TimeSteps.Regular,
        caption: str = None,
        description: str = "",
        publish: bool = True,
    ):
        """Adds a new level to the given hierarchy

        Args:
            new_level_name (str): The name of the level in the new hierarchy.
            hierarchy_name (str): The name of the hierarchy to create in the dimension.
            dataset_name (str): The name of the dataset to use.
            value_column (str): The value column in the dataset to use for the level.
            existing_level (str): The existing level to insert the new one at.
            key_columns (List[str], optional):  The key columns in the dataset to use for the level. Defaults to None to use the value column.
            add_above_existing (bool, optional): Whether the new level should be inserted above the existing one. Defaults to True.
            level_type (TimeSteps, optional): The TimeSteps for the level if time based. Defaults to TimeSteps.Regular.
            caption (str, optional): The caption for the level. Defaults to None to use new_level_name.
            description (str, optional): The description for the level. Defaults to "".
            publish (bool, optional): Whether the updated project should be published. Defaults to True.
        """
        model_utils._perspective_check(self)

        inspection = getfullargspec(self.add_level_to_hierarchy)
        validate_by_type_hints(inspection=inspection, func_params=locals())

        project_dict = self.project._get_dict()

        model_utils._check_conflicts(
            to_add=new_level_name, data_model=self, project_dict=project_dict
        )

        dset = project_parser.get_dataset(project_dict, dataset_name=dataset_name)

        if not dset:
            raise atscale_errors.UserError(
                f"Dataset '{dataset_name}' not associated with the project"
            )

        if not self.dataset_exists(dataset_name, include_unused=False):
            raise atscale_errors.UserError(
                f"Dataset '{dataset_name}' not associated with given model"
            )

        if not model_utils._column_exists(project_dict, dataset_name, value_column):
            raise atscale_errors.UserError(
                f"Column '{value_column}' not found in the '{dataset_name}' dataset"
            )
        if key_columns:
            for column in key_columns:
                if not model_utils._column_exists(project_dict, dataset_name, column):
                    raise atscale_errors.UserError(
                        f"Column '{column}' not found in the '{dataset_name}' dataset"
                    )

        attributes = data_model_helpers._get_draft_features(
            project_dict=project_dict,
            data_model_name=self.name,
            feature_type=FeatureType.CATEGORICAL,
        )
        found = False
        for name, info in attributes.items():
            if info.get("base_name", name) == existing_level:
                attribute = info
                found = True
                break
        if not found:
            if existing_level not in attributes:
                raise atscale_errors.UserError(f"Level '{existing_level}' not found.")
            else:
                raise atscale_errors.UserError(
                    f"Level '{existing_level}' is roleplayed. Levels must be added to base hierachies."
                )
        if hierarchy_name not in attribute["base_hierarchy"]:
            raise atscale_errors.UserError(
                f"Level '{existing_level}' does not belong to hierarchy '{hierarchy_name}'"
            )

        dimensions = self.get_dimensions()
        if dimensions[attribute["dimension"]]["type"] == "Time":
            if level_type == TimeSteps.Regular:
                raise atscale_errors.UserError(
                    f"level_type cannot be TimeSteps.Regular for time dimensions"
                )
        else:
            if level_type != TimeSteps.Regular:
                raise atscale_errors.UserError(
                    f"level_type must be TimeSteps.Regular for non time dimensions"
                )

        project_dict = self.project._get_dict()
        dimension_utils.create_level(
            project_dict=project_dict,
            cube_id=self.cube_id,
            level_name=new_level_name,
            dataset_name=dataset_name,
            value_column=value_column,
            key_columns=key_columns,
            level_type=level_type,
            hierarchy_name=hierarchy_name,
            existing_level=existing_level,
            add_above_existing=add_above_existing,
            caption=caption,
            description=description,
        )
        self.project._update_project(project_dict, publish)

    def get_hierarchies(
        self,
        secondary_attribute: bool = False,
        folder_list: List[str] = None,
    ) -> Dict:
        """Gets a dictionary of dictionaries with the published hierarchy names and metadata. Secondary attributes are treated as
             their own hierarchies, they are hidden by default, but can be shown with the secondary_attribute parameter.

        Args:
            secondary_attribute (bool, optional): if we want to filter the secondary attribute field. True will return hierarchies and
                secondary_attributes, False will return only non-secondary attributes. Defaults to False.
            folder_list (List[str], optional): The list of folders in the data model containing hierarchies to exclusively list.
                Defaults to None to not filter by folder.

        Returns:
            dict: A dictionary of dictionaries where the hierarchy names are the keys in the outer dictionary
                while the inner keys are the following: 'dimension', 'description', 'caption', 'folder', 'type'(value is
                Time or Standard), 'secondary_attribute'.
        """
        inspection = getfullargspec(self.get_hierarchies)
        validate_by_type_hints(inspection=inspection, func_params=locals())

        filter_by = {}
        if not secondary_attribute:
            filter_by[Hierarchy.secondary_attribute] = [False]

        # folder list is more involved as we need to append if the dict already exists
        if folder_list is not None:
            if type(folder_list) == str:
                folder_list = [folder_list]
            filter_by[Hierarchy.folder] = folder_list
        return metadata_utils._get_hierarchies(self, filter_by=filter_by)

    def get_hierarchy_levels(
        self,
        hierarchy_name: str,
    ) -> List[str]:
        """Gets a list of strings for the levels of a given published hierarchy

        Args:
            hierarchy_name (str): The query name of the hierarchy

        Returns:
            List[str]: A list containing the hierarchy's levels
        """
        inspection = getfullargspec(self.get_hierarchy_levels)
        validate_by_type_hints(inspection=inspection, func_params=locals())

        return metadata_utils._get_hierarchy_levels(self, hierarchy_name)

    def get_feature_description(
        self,
        feature: str,
    ) -> str:
        """Returns the description of a given published feature.

        Args:
            feature (str): The query name of the feature to retrieve the description of.

        Returns:
            str: The description of the given feature.
        """
        inspection = getfullargspec(self.get_feature_description)
        validate_by_type_hints(inspection=inspection, func_params=locals())

        existing_features = data_model_helpers._get_published_features(data_model=self)

        model_utils._check_features(
            features=[feature],
            check_list=existing_features,
            errmsg=CheckFeaturesErrMsg.ALL.get_errmsg(is_published=True),
        )

        return metadata_utils._get_feature_description(self, feature)

    def get_feature_expression(
        self,
        feature: str,
    ) -> str:
        """Returns the expression of a given published feature.

        Args:
            feature (str): The query name of the feature to return the expression of.

        Returns:
            str: The expression of the given feature.
        """
        inspection = getfullargspec(self.get_feature_expression)
        validate_by_type_hints(inspection=inspection, func_params=locals())

        existing_features = data_model_helpers._get_published_features(data_model=self)

        model_utils._check_features(
            features=[feature],
            check_list=existing_features,
            errmsg=CheckFeaturesErrMsg.ALL.get_errmsg(is_published=True),
        )

        return metadata_utils._get_feature_expression(self, feature=feature)

    def get_all_numeric_feature_names(
        self,
        folder: str = None,
    ) -> List[str]:
        """Returns a list of all published numeric features (ie Aggregate and Calculated Measures) in the data model.

        Args:
            folder (str, optional): The name of a folder in the data model containing measures to exclusively list.
                Defaults to None to not filter by folder.

        Returns:
            List[str]: A list of the query names of numeric features in the data model and, if given, in the folder.
        """
        inspection = getfullargspec(self.get_all_numeric_feature_names)
        validate_by_type_hints(inspection=inspection, func_params=locals())

        return metadata_utils._get_all_numeric_feature_names(self, folder=folder)

    def get_all_categorical_feature_names(
        self,
        folder: str = None,
    ) -> List[str]:
        """Returns a list of all published categorical features (ie Hierarchy levels and secondary_attributes) in the given DataModel.

        Args:
            folder (str, optional): The name of a folder in the DataModel containing features to exclusively list.
                Defaults to None to not filter by folder.

        Returns:
            List[str]: A list of the query names of categorical features in the DataModel and, if given, in the folder.
        """
        inspection = getfullargspec(self.get_all_categorical_feature_names)
        validate_by_type_hints(inspection=inspection, func_params=locals())

        return metadata_utils._get_all_categorical_feature_names(self, folder=folder)

    def get_folders(self) -> List[str]:
        """Returns a list of the available folders in the published DataModel.

        Returns:
            List[str]: A list of the available folders
        """
        return metadata_utils._get_folders(self)

    def get_connected_warehouse(self):
        """Returns the warehouse id utilized in this data_model

        Returns:
            str: the warehouse id
        """
        return self.project.get_connected_warehouse()

    def list_related_hierarchies(
        self,
        dataset_name: str,
    ) -> List[str]:
        """Returns a list of all hierarchies with relationships to the given dataset.

        Args:
            dataset_name (str): The name of a fact dataset to find relationships from.

        Returns:
            List[str]: A list of the names of the hierarchies that have relationships to the dataset.
        """
        inspection = getfullargspec(self.list_related_hierarchies)
        validate_by_type_hints(inspection=inspection, func_params=locals())

        project_dict = self.project._get_dict()
        cube_dict = model_utils._get_model_dict(self, project_dict=project_dict)[0]
        # first find the dataset from the input name
        dataset = dictionary_parser.parse_dict_list(
            project_parser.get_datasets(project_dict), "name", dataset_name
        )
        if dataset is None:
            raise atscale_errors.UserError(f'No fact dataset named "{dataset_name}" found')
        # find the dataset reference using the id
        key_ref_ids = []
        dataset_ref = dictionary_parser.parse_dict_list(
            data_model_parser._get_dataset_refs(cube_dict), "id", dataset.get("id")
        )
        if dataset_ref is None:
            raise atscale_errors.UserError(f'No fact dataset named "{dataset_name}" found')
        # grab all key-refs from the dataset so we can find the attributes
        for key_ref in dataset_ref.get("logical", {}).get("key-ref", []):
            key_ref_ids.append(key_ref.get("id"))
        # loop through project and cube attributes to find matches
        keyed_attribute_ids = []
        project_keyed_attributes = project_dict.get("attributes", {}).get("keyed-attribute")
        cube_keyed_attributes = cube_dict.get("attributes", {}).get("keyed-attribute")
        for keyed_attribute in project_keyed_attributes + cube_keyed_attributes:
            if keyed_attribute.get("key-ref") in key_ref_ids:
                keyed_attribute_ids.append(keyed_attribute.get("id"))
        # loop through project and cube hierarchies to grab the ones that contain the matched attributes
        hierarchy_names = set()
        for dimension in project_dict.get("dimensions", {}).get("dimension", []) + cube_dict.get(
            "dimensions", {}
        ).get("dimension", []):
            for hierarchy in dimension.get("hierarchy", []):
                for level in hierarchy.get("level", []):
                    if level.get("primary-attribute") in keyed_attribute_ids:
                        hierarchy_names.add(hierarchy.get("name"))
                        break
        # augment the list with any other hierarchies that are connected to them with snowflake dimensions
        hierarchy_names = list(hierarchy_names)
        model_utils._add_related_hierarchies(self, hierarchy_names)
        return hierarchy_names

    def list_related_datasets(
        self,
        hierarchy_name: str,
    ) -> List[str]:
        """Returns a list of all fact datasets with relationships to the given hierarchy.

        Args:
            hierarchy_name (str): The query name of a hierarchy to find relationships from.

        Returns:
            List[str]: A list of the names of the datasets that have relationships to the hierarchy.
        """
        inspection = getfullargspec(self.list_related_datasets)
        validate_by_type_hints(inspection=inspection, func_params=locals())

        project_dict = self.project._get_dict()
        cube_dict = model_utils._get_model_dict(self, project_dict=project_dict)[0]
        # make sure we got a valid hierarchy
        keyed_attribute_ids = []
        for dimension in project_dict.get("dimensions", {}).get("dimension", []) + cube_dict.get(
            "dimensions", {}
        ).get("dimension", []):
            hierarchy = dictionary_parser.parse_dict_list(
                dimension.get("hierarchy", []), "name", hierarchy_name
            )
            if hierarchy is not None:
                break
        if hierarchy is None:
            raise atscale_errors.UserError(f'No hierarchy named "{hierarchy_name}" found')
        # the hierarchy we were passed could be a part of a snowflake dimension so we need to add related ones
        hierarchy_names = [hierarchy.get("name")]
        model_utils._add_related_hierarchies(self, hierarchy_names)
        # loop through project and cube hierarchies and grab their attributes if they were in the list
        for dimension in project_dict.get("dimensions", {}).get("dimension", []) + cube_dict.get(
            "dimensions", {}
        ).get("dimension", []):
            for hierarchy in dimension.get("hierarchy", []):
                if hierarchy.get("name") in hierarchy_names:
                    for level in hierarchy.get("level", []):
                        keyed_attribute_ids.append(level.get("primary-attribute"))

        # loop through project and cube attributes to find matches
        key_ref_ids = []
        for keyed_attribute in project_dict.get("attributes", {}).get(
            "keyed-attribute"
        ) + cube_dict.get("attributes", {}).get("keyed-attribute"):
            if keyed_attribute.get("id") in keyed_attribute_ids:
                key_ref_ids.append(keyed_attribute.get("key-ref"))
        # find the dataset refs that contain the matched attributes
        dataset_ids = set()
        for dataset_ref in data_model_parser._get_dataset_refs(cube_dict):
            for key_ref in dataset_ref.get("logical", {}).get("key-ref", []):
                if key_ref.get("id") in key_ref_ids:
                    dataset_ids.add(dataset_ref.get("id"))
                    break
        # find the datasets that the refs match to so we can grab the names
        dataset_names = []
        for dataset in project_parser.get_datasets(project_dict):
            if dataset.get("id") in dataset_ids:
                dataset_names.append(dataset.get("name"))
        return dataset_names

    def create_perspective(
        self,
        new_perspective_name: str,
        dimensions: List[str] = None,
        hierarchies: List[str] = None,
        categorical_features: List[str] = None,
        numeric_features: List[str] = None,
        publish: bool = True,
    ):
        """Creates a perspective that hides the inputs, using the current data model as a base.

        Args:
            new_perspective_name (str): Creates a new perspective based on the current data model. Objects passed in will be hidden by the perspective.
            dimensions (List[str], optional): Dimensions to hide. Defaults to None.
            hierarchies (List[str], optional): Query names of hierarchies to hide. Defaults to None.
            categorical_features (List[str], optional): Query names of categorical features to hide. Defaults to None.
            numeric_features (List[str], optional): Query names of numeric features to hide. Defaults to None.
            publish (bool, optional): Whether to publish the updated project. Defaults to True.

        Returns:
            DataModel: The DataModel object for the created perspective.
        """
        model_utils._perspective_check(
            self, "Perspectives cannot be created from other perspectives"
        )

        inspection = getfullargspec(self.create_perspective)
        validate_by_type_hints(inspection=inspection, func_params=locals())

        perspective_id = data_model_helpers._create_perspective(
            data_model=self,
            name=new_perspective_name,
            dimensions=dimensions,
            hierarchies=hierarchies,
            categorical_features=categorical_features,
            numeric_features=numeric_features,
            publish=publish,
            update=False,
        )
        return DataModel(data_model_id=perspective_id, project=self.project)

    def update_perspective(
        self,
        perspective_name: str,
        dimensions: List[str] = None,
        hierarchies: List[str] = None,
        categorical_features: List[str] = None,
        numeric_features: List[str] = None,
        publish: bool = True,
    ):
        """Updates a perspective to hide the inputs. All items to hide should be in the inputs even if previously hidden.

        Args:
            perspective_name (str): The name of the perspective to update.
            dimensions (List[str], optional): Dimensions to hide. Defaults to None.
            hierarchies (List[str], optional): Query names of hierarchies to hide. Defaults to None.
            categorical_features (List[str], optional): Query names of categorical features to hide. Defaults to None.
            numeric_features (List[str], optional): Query names of numeric features to hide. Defaults to None.
            publish (bool, optional): Whether to publish the updated project. Defaults to True.

        Returns:
            DataModel: The DataModel object for the updated perspective.
        """
        model_utils._perspective_check(
            self, "Perspectives must be updated from their parent data model"
        )

        inspection = getfullargspec(self.update_perspective)
        validate_by_type_hints(inspection=inspection, func_params=locals())

        perspective_id = data_model_helpers._create_perspective(
            data_model=self,
            name=perspective_name,
            dimensions=dimensions,
            hierarchies=hierarchies,
            categorical_features=categorical_features,
            numeric_features=numeric_features,
            publish=publish,
            update=True,
        )
        return DataModel(data_model_id=perspective_id, project=self.project)

    def delete(
        self,
        publish: bool = True,
    ):
        """Deletes the current data model from the project

        Args:
            publish (bool, optional): Whether to publish the updated project. Defaults to True.
        """
        inspection = getfullargspec(self.delete)
        validate_by_type_hints(inspection=inspection, func_params=locals())

        project_dict = self.project._get_dict()
        if self.is_perspective():
            updated_perspectives = [
                x for x in project_dict["perspectives"]["perspective"] if x["id"] != self.id
            ]
            project_dict["perspectives"]["perspective"] = updated_perspectives
        else:
            # If we are deleting a cube we should also delete any perspectives built on top of it
            updated_cubes = [x for x in project_dict["cubes"]["cube"] if x["id"] != self.id]
            project_dict["cubes"]["cube"] = updated_cubes
            if len(project_dict.get("perspectives", {}).get("perspective", [])) > 0:
                updated_perspectives = [
                    x
                    for x in project_dict["perspectives"]["perspective"]
                    if x["cube-ref"] != self.id
                ]
                project_dict["perspectives"]["perspective"] = updated_perspectives
        self.project._update_project(project_dict, publish)

    def bulk_operator(
        self,
        function: Callable,
        parameter_list: List[Dict],
        error_limit: int = 5,
        publish: bool = True,
    ):
        """Performs a specified operation for all parameters in the list. Optimizes validation
        and api calls for better performance on large numbers of operations. Must be chain operations
        of the same underlying function, for example create_aggregate_feature.

        Args:
            function (Callable): The function to call a number of times.
            parameter_list (List[Dict]): The list of parameters for each function call.
            error_limit (int, optional): Defaults to 5, the maximum number of similar errors to collect before abbreviating.
            publish (bool, optional): Defaults to True, whether the updated project should be published
        """
        model_utils._perspective_check(self)

        inspection = getfullargspec(self.bulk_operator)
        validate_by_type_hints(inspection=inspection, func_params=locals())

        # validate error limit
        if error_limit <= 0 or error_limit is None:
            raise ValueError(
                f"Parameter error_limit must be greater than 0, received {error_limit}"
            )

        # check if this is supported function
        bulk_operation = bulk_operator_utils.supported_bulk_operations(function)
        if bulk_operation is None:
            raise atscale_errors.UnsupportedOperationException(
                f"The function {function.__name__} is not supported for bulk operations"
                f" at this time."
            )

        project_dict = self.project._get_dict()
        feature_dict = (
            data_model_helpers._get_draft_features(
                project_dict=project_dict,
                data_model_name=self.name,
                feature_type=FeatureType.ALL,
            ),
        )

        # run our bulk operator
        bulk_operation(
            self.project._atconn,
            project_dict,
            feature_dict,
            self.cube_id,
            parameter_list,
            error_limit=error_limit,
        )
        # publish
        self.project._update_project(project_json=project_dict, publish=publish)

    def clone(
        self,
        query_name: str,
        description: str = "",
        publish: bool = True,
    ):
        """Clones the current DataModel in its project and sets the name to the given query_name.

        Args:
            query_name (str): The name for the newly cloned model.
            description (str, optional): The description of the model. Defaults to "".
            publish (bool, optional): Whether to publish the project after creating the model. Defaults to True.

        Returns:
            DataModel: The DataModel object for the new model.
        """
        model_utils._perspective_check(self, "Clone is not supported for perspectives.")

        inspection = getfullargspec(self.clone)
        validate_by_type_hints(inspection=inspection, func_params=locals())

        for cube in project_parser.get_cubes(self.project._get_dict()):
            if cube.get("name") == query_name:
                raise ValueError(
                    f"There is already a data model in the project with the query name: {query_name}"
                )
        u = endpoints._endpoint_design_org(
            self.project._atconn,
            suffix=f"/project/{self.project.draft_project_id}/cube/{self.id}/copy",
        )
        data = {
            "name": query_name,
            "description": description,
            "copy-security": True,
        }
        d = json.dumps(data)
        response = self.project._atconn._submit_request(
            request_type=RequestType.POST, url=u, data=d
        )
        id = json.loads(response.content)["response"]["id"]
        if publish:
            self.project.publish()
        return DataModel(id, self.project)
