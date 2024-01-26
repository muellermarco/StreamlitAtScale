import logging
from typing import List
import uuid
from atscale.base import templates

from atscale.connection.connection import _Connection
from atscale.parsers import data_model_parser, project_parser
from atscale.utils import project_utils, feature_utils
from atscale.base.enums import TimeLevels, TimeSteps, PlatformType

logger = logging.getLogger(__name__)


def _generate_calculated_columns_for_date_column(
    atconn: _Connection,
    data_set_project: dict,
    column_name: str,
    time_levels: list,
) -> dict:
    """
    Creates the calculated columns for extracting the time_levels from the date column referred to by column_name. Aggregating by dates
    can get involved. For instance, weeks can span months and years (e.g. Jan 1 comes on Wednesday). To address this, we use year (and
    sometimes day) values in aggregate keys to help differentiate aggregation levels. For instance, there may be more than one year of
    data and we need to differentate week 52 in one year from week 52 in another year before aggregating by week. For levels more fine
    grained than a day (e.g. hour, minute, etc) we also may use day in an aggregate key to help differentate levels (e.g. 1pm on day 1
    vs 2pm on day 2). For that reason, this method may introduce calculated columns for year or day in the returned calculated_columns
    dict, even if those levels were not specified in the provided time_levels parameter.

    Args:
        atconn (_Connection): AtScale connection
        data_set_project (dict): a data set at the project level
        column_name (str): the name of the date column in a database, as referenced by AtScale, to generate calculated columns for that are associated with th eprovided TimeLevels
        time_levels (list): a list of TimeLevels enums for which to create calculated columns (for breaking out the parts of the date column_name)

    Returns:
        dict: a dict object where keys are the names of the time_levels and values are the names of the created calculated column for that leveel. May additionally contain a year and
        day calculated column, even if not specified in the provided time_levels, for purposes of creating aggregate keys.
    """
    platform = atconn._get_warehouse_platform(
        warehouse_id=data_set_project["physical"]["connection"]["id"]
    )
    # consolidating the behavior for databricks platforms
    if platform == "databricks":
        platform = "databrickssql"
    platform_type = PlatformType(platform)
    calculated_columns = {}  # let's keep track of calculated columns as we go
    # create calculated columns for everything in TimeLevels
    for level in time_levels:
        calc_col_name = column_name + "_" + level.name
        project_utils.add_calculated_column_to_project_dataset(
            atconn=atconn,
            data_set=data_set_project,
            column_name=calc_col_name,
            expression=level.get_sql_expression(column_name, platform_type),
        )
        # In the AtScale object model, even though the calculated column is added to the project dataset and has an id,
        # other things that reference it (like an attribute in a hierarchy) do not actually reference that id; they just
        # use the calculated column name. We therefore track a dict of level to associated calc_col_name mappings to return
        # for any subsequent code that may need to generate such references.
        calculated_columns[level.name] = calc_col_name

    if not TimeLevels.Year.name in calculated_columns.keys():
        # We'll make a calculated column for year because it's required for aggregate keys on any levels other than year.
        year_calc_col_name = column_name + "_" + TimeLevels.Year.name
        calculated_columns[TimeLevels.Year] = year_calc_col_name
        project_utils.add_calculated_column_to_project_dataset(
            atconn=atconn,
            data_set=data_set_project,
            column_name=year_calc_col_name,
            expression=level.get_sql_expression(column_name, platform_type),
        )

    # If we have levels below the day level, then we'll also need a day calculated column for aggregate keys.
    # Note that level.index starts at 0 for year and increments, so "lower" levels have higher index values.
    if (
        any(TimeLevels.Day.index < l.index for l in time_levels)
    ) and not TimeLevels.Day.name in calculated_columns.keys():  # if we have any sub day levels and day is not already in calculated_columns
        # add a calculated day column
        day_calc_col_name = column_name + "_" + TimeLevels.Day.name
        calculated_columns[TimeLevels.Day] = day_calc_col_name
        project_utils.add_calculated_column_to_project_dataset(
            atconn=atconn,
            data_set=data_set_project,
            column_name=day_calc_col_name,
            expression=level.get_sql_expression(column_name, platform_type),
        )

    return calculated_columns


def create_time_dimension_for_column(
    atconn: _Connection,
    project_dict: dict,
    cube_id: str,
    dataset_id: str,
    column_name: str,
    time_levels: List[TimeLevels],
    base_name: str = None,
    description: str = None,
    caption: str = None,
    folder: str = None,
    visible: bool = True,
):
    """Mutates the provided project_dict in place to create a dimension with TimeLevels (see TimeLevels enum)
    for different time windows (e.g. day, week, month) for the provided column_name and related parameters.

    Args:
        atconn (_Connection): AtScale connection
        project_dict (dict): the dict associated with an AtScale project
        cube_id (str): the id for the cube where we will create the dimension
        dataset_id (str): the id for the dataset in the project associated with the table that corresponds with the column we're creating the dimension for
        column_name (str): the name of the colunm we're creating a dimension for
        time_levels (list[TimeLevels]): a list of leves from the TimeLevels enum
        base_name (str, optional): The base name to use to generate object names. Defaults to None to use the column_name.
        description (str, optional): a description for the dimension to be created. Defaults to None.
        caption (str, optional): a caption for the hierarchy to be created for the dimension. Defaults to None.
        folder (str, optional): a folder to put the dimension in. Defaults to None.
        visible (bool, optional): whether the dimension and related items to be created shouild be visible. Defaults to True.
    """

    # Let's get the dataset from the project so we can add calculated columns to it.
    # Remember there are datasets in project, and data-set-ref in the data model. We will have to modify both.
    data_set_project = project_parser.get_dataset(project_dict=project_dict, dataset_id=dataset_id)
    # we'll grab the data_model where most of the changes will occur
    data_model_dict = project_parser.get_cube(project_dict=project_dict, id=cube_id)

    # Start data_model mutations by filling in the attributes element in case it's empty
    # setdefault only has effect if attributes element doesn't exist yet
    data_model_dict.setdefault("attributes", {})

    calculated_columns = _generate_calculated_columns_for_date_column(
        atconn=atconn,
        data_set_project=data_set_project,
        column_name=column_name,
        time_levels=time_levels,
    )

    # I think the order in which levels are created/added may matter, possibly in what's determined to be the "leaf"
    time_levels.sort(key=lambda level: level.index)

    levels = {}  # we'll store levels as we go
    for level in time_levels:  # create a hierarchy level for each of the time_levels
        # Every TimeLevel has year for one of its key columns. See _generate_calculated_columns_for_date_column for more info.
        k = calculated_columns.get(TimeLevels.Year.name)
        keys = [k]
        # We don't need to add more keys for TimeLevels.Year. But for anything lower than year, we need a key for it's level itself.
        # Note that TimeLevels.index starts at 0 for year and goes up. So "lower" levels have higher index values.
        if level.index > TimeLevels.Year.index:
            keys.append(calculated_columns.get(level.name))
        # any level below day additionally needs the day calculated column for a key
        if level.index > TimeLevels.Day.index:
            keys.append(calculated_columns.get(TimeLevels.Day.name))

        # used in attribute-key and keyed-attribute json elements
        ref_id = str(uuid.uuid4())

        # Set attribute-key element values. This seems mostly superfluous (but the data_model will break without it) since the visible field also occures in keyed-attribute
        # below which references this. The main thing that changes is number of columns, which I believe is associated with key columns.
        attribute_key_dict = templates.create_attribute_key_dict(
            key_id=ref_id, columns=len(keys), visible=visible
        )
        data_model_dict["attributes"].setdefault("attribute-key", [])
        data_model_dict["attributes"]["attribute-key"].append(attribute_key_dict)

        # set keyed-attribute element values
        keyed_attribute_id = str(uuid.uuid4())
        keyed_attribute_name = calculated_columns.get(level.name)
        new_keyed_attribute = templates.create_keyed_attribute_dict(
            attribute_id=keyed_attribute_id,
            key_ref=ref_id,
            name=keyed_attribute_name,
            visible=visible,
            ordering="ascending",
        )
        data_model_dict["attributes"].setdefault("keyed-attribute", [])
        data_model_dict["attributes"]["keyed-attribute"].append(new_keyed_attribute)

        # create the hierarchy level, to be used in creating the hierarchy and dimension below this loop
        level_id = str(uuid.uuid4())
        new_level = templates.create_hierarchy_level_dict(
            visible=visible,
            level_id=level_id,
            keyed_attribute_id=keyed_attribute_id,
            level_type=level.timestep,
        )
        levels[level.name] = new_level

        # data-set-ref appears in project json after the dimensions, however, we need to add things to it in this loop.
        # So it may look a little out of order, but it needs to be here. We finish up by creating the dimension below the loop.

        # Grab the data_set_ref in the data_model that references the dataset in the project.
        # get_data_set_ref delists and returns the first dict inside of the data-set-ref list
        data_set_ref = data_model_parser.get_data_set_ref(
            data_model_dict=data_model_dict, dataset_id=dataset_id
        )
        # key-ref element under the "logcal" json element.
        key_ref_dict = templates.create_attribute_key_ref_dict(
            key_id=ref_id, complete=True, columns=keys, unique=False
        )

        data_set_ref["logical"].setdefault("key-ref", [])
        data_set_ref["logical"]["key-ref"].append(key_ref_dict)
        # attribute-ref element under the "logcal" element
        attribute_ref_dict = templates.create_attribute_ref_dict(
            columns=[calculated_columns.get(level.name)], attribute_id=keyed_attribute_id
        )  # I actually don't know if column is used from this dict by the engine. But I see it only have one value, even if the associated level has multiple cols in its key
        data_set_ref["logical"].setdefault("attribute-ref", [])
        data_set_ref["logical"]["attribute-ref"].append(attribute_ref_dict)

    # create a hierarchy for the data_model with the levels we just created
    if base_name is None:
        base_name = column_name
    hierarchy_id = str(uuid.uuid4())
    new_hierarchy = templates.create_hierarchy_dict(
        hierarchy_id=hierarchy_id,
        hierarchy_name=f"{base_name}_Hierarchy",
        caption=caption,
        folder=folder,
        description=description,
        visible=visible,
        levels=list(levels.values()),
    )

    # create a new denormalized dimension dict with hierarchy
    dimension_id = str(uuid.uuid4())
    new_dimension = templates.create_dimension_dict(
        hierarchy_dict=new_hierarchy,
        dim_id=dimension_id,
        name=f"{base_name}_Dimension",
        visible=visible,
        time_dimension=True,
    )

    # add the new denomralized dimension to the data_model (dimensions usually sit in project but denormalized dimensions reside entirely in the data_model)
    data_model_dict.setdefault("dimensions", {})
    data_model_dict["dimensions"].setdefault("dimension", [])
    data_model_dict["dimensions"]["dimension"].append(new_dimension)


def create_dimension(
    project_dict: dict, cube_id: str, name: str, time_dimension: bool, description: str = ""
):
    dimension_id = str(uuid.uuid4())
    new_dimension = templates.create_dimension_dict(
        dim_id=dimension_id,
        name=name,
        time_dimension=time_dimension,
        visible=True,
        description=description,
    )
    new_dimension_ref = {"id": dimension_id}
    project_dict.setdefault("dimensions", {})
    project_dict["dimensions"].setdefault("dimension", [])
    project_dict["dimensions"]["dimension"].append(new_dimension)

    cube = project_parser.get_cube(project_dict=project_dict, id=cube_id)
    cube["dimensions"].setdefault("dimension-ref", [])
    cube["dimensions"]["dimension-ref"].append(new_dimension_ref)


def create_hierarchy(
    project_dict: dict,
    cube_id: str,
    name: str,
    dimension_name: str,
    dataset_name: str,
    caption: str = None,
    description: str = "",
    folder: str = "",
):
    hierarchy_id = str(uuid.uuid4())
    new_hierarchy = templates.create_hierarchy_dict(
        hierarchy_id=hierarchy_id,
        hierarchy_name=name,
        caption=caption,
        folder=folder,
        description=description,
        visible=True,
        levels=[],
    )

    cube = project_parser.get_cube(project_dict=project_dict, id=cube_id)
    found = False
    for dimension in project_dict.get("dimensions", {}).get("dimension", []):
        if dimension["name"] == dimension_name:
            dimension.setdefault("hierarchy", [])
            dimension["hierarchy"].append(new_hierarchy)
            dataset_id = project_parser.get_dataset(project_dict, dataset_name=dataset_name).get(
                "id"
            )
            if dataset_id not in dimension.get("participating_datasets", []):
                dimension.setdefault("participating_datasets", [])
                dimension["participating_datasets"].append(dataset_id)
            existing_ref = False
            cube["dimensions"].setdefault("dimension-ref", [])
            for ref in cube["dimensions"]["dimension-ref"]:
                if dimension["id"] == ref["id"]:
                    existing_ref = True
                    break
            if existing_ref:
                new_dimension_ref = {"id": dimension["id"]}
                cube["dimensions"]["dimension-ref"].append(new_dimension_ref)
            found = True
            break
    if not found:
        cube = project_parser.get_cube(project_dict=project_dict, id=cube_id)
        for dimension in cube.get("dimensions", {}).get("dimension", []):
            if dimension["name"] == dimension_name:
                dimension.setdefault("hierarchy", [])
                dimension["hierarchy"].append(new_hierarchy)
                break


def create_level(
    project_dict: dict,
    cube_id: str,
    level_name: str,
    dataset_name: str,
    value_column: str,
    hierarchy_name: str,
    key_columns: List[str] = None,
    level_type: TimeSteps = TimeSteps.Regular,
    existing_level: str = None,
    add_above_existing: bool = True,
    caption: str = None,
    description: str = "",
):
    if not key_columns:
        key_columns = [value_column]
    # used in attribute-key and keyed-attribute json elements
    ref_id = str(uuid.uuid4())

    # Set attribute-key element values. This seems mostly superfluous (but the data_model will break without it) since the visible field also occures in keyed-attribute
    # below which references this. The main thing that changes is number of columns, which I believe is associated with key columns.
    attribute_key_dict = templates.create_attribute_key_dict(
        key_id=ref_id, columns=len(key_columns), visible=True
    )
    project_dict["attributes"].setdefault("attribute-key", [])
    project_dict["attributes"]["attribute-key"].append(attribute_key_dict)

    # set keyed-attribute element values
    keyed_attribute_id = str(uuid.uuid4())
    new_keyed_attribute = templates.create_keyed_attribute_dict(
        attribute_id=keyed_attribute_id,
        key_ref=ref_id,
        name=level_name,
        ordering="ascending",
        visible=True,
        caption=caption,
        description=description,
    )

    existing_attribute_id = None
    if existing_level:
        for attribute in project_dict["attributes"]["keyed-attribute"]:
            if attribute.get("name") == existing_level:
                existing_attribute_id = attribute.get("id")
                break

    # create the hierarchy level, to be used in creating the hierarchy and dimension below this loop
    level_id = str(uuid.uuid4())
    new_level = templates.create_hierarchy_level_dict(
        level_id=level_id,
        keyed_attribute_id=keyed_attribute_id,
        level_type=level_type,
        visible=True,
    )

    # key-ref element under the "logical" json element.
    key_ref_dict = templates.create_attribute_key_ref_dict(
        key_id=ref_id, complete=True, columns=key_columns, unique=False
    )
    dataset = project_parser.get_dataset(project_dict, dataset_name=dataset_name)

    # attribute-ref element under the "logical" element
    attribute_ref_dict = templates.create_attribute_ref_dict(
        columns=[value_column], attribute_id=keyed_attribute_id
    )

    found = False
    for dimension in project_dict.get("dimensions", {}).get("dimension", []):
        for hierarchy in dimension.get("hierarchy", []):
            if hierarchy.get("name") == hierarchy_name:
                found = True
                if not existing_level:
                    hierarchy.setdefault("level", [])
                    hierarchy["level"].append(new_level)
                else:
                    updated_levels_list = []
                    for level in hierarchy.get("level", []):
                        if level.get("primary-attribute") == existing_attribute_id:
                            if add_above_existing:
                                updated_levels_list.append(new_level)
                                updated_levels_list.append(level)
                            else:
                                updated_levels_list.append(level)
                                updated_levels_list.append(new_level)
                        else:
                            updated_levels_list.append(level)
                    hierarchy["level"] = updated_levels_list

                project_dict["attributes"].setdefault("attribute-key", [])
                project_dict["attributes"]["attribute-key"].append(attribute_key_dict)

                project_dict["attributes"].setdefault("keyed-attribute", [])
                project_dict["attributes"]["keyed-attribute"].append(new_keyed_attribute)

                dataset["logical"].setdefault("key-ref", [])
                dataset["logical"]["key-ref"].append(key_ref_dict)
                dataset["logical"].setdefault("attribute-ref", [])
                dataset["logical"]["attribute-ref"].append(attribute_ref_dict)
                break
    if not found:
        cube = project_parser.get_cube(project_dict=project_dict, id=cube_id)
        for dimension in cube.get("dimensions", {}).get("dimension", []):
            for hierarchy in dimension.get("hierarchy", []):
                if hierarchy.get("name") == hierarchy_name:
                    if not existing_level:
                        hierarchy.setdefault("level", [])
                        hierarchy["level"].append(new_level)
                    else:
                        updated_levels_list = []
                        for level in hierarchy.get("level", []):
                            if level.get("primary-attribute") == existing_attribute_id:
                                if add_above_existing:
                                    updated_levels_list.append(new_level)
                                    updated_levels_list.append(level)
                                else:
                                    updated_levels_list.append(level)
                                    updated_levels_list.append(new_level)
                            else:
                                updated_levels_list.append(level)
                        hierarchy["level"] = updated_levels_list

                    cube["attributes"].setdefault("attribute-key", [])
                    cube["attributes"]["attribute-key"].append(attribute_key_dict)

                    cube["attributes"].setdefault("keyed-attribute", [])
                    cube["attributes"]["keyed-attribute"].append(new_keyed_attribute)

                    for dataset_ref in cube.get("data-sets", {}).get("data-set-ref", []):
                        if dataset_ref["id"] == dataset["id"]:
                            dataset_ref["logical"].setdefault("key-ref", [])
                            dataset_ref["logical"]["key-ref"].append(key_ref_dict)
                            dataset_ref["logical"].setdefault("attribute-ref", [])
                            dataset_ref["logical"]["attribute-ref"].append(attribute_ref_dict)
                            break
                    break


def create_categorical_dimension_for_column(
    project_dict: dict,
    cube_id: str,
    dataset_id: str,
    column_name: str,
    base_name: str = None,
    description: str = None,
    caption: str = None,
    folder: str = None,
    visible: bool = True,
):
    """Creates a categorical dimension with a single level of a hierarchy for a column.

    Args:
        project_dict (dict): python dict for project
        cube_id (str): id for the cube
        dataset_id (str): id for the dataset associated with the table where the column resides
        column_name (str): name of the column to create the dimension for
        base_name (str, optional): The base name to use to generate object names. Defaults to None to use the column_name.
        description (str, optional): description of the new dimension. Defaults to None.
        caption (str, optional): caption for the new dimension. Defaults to None.
        folder (str, optional): folder to put the new dimension in. Defaults to None.
        visible (bool, optional): whether the dimension should be put in. Defaults to True.
    """

    # we'll grab the data_model or "cube" where most of the changes will occur
    data_model_dict = project_parser.get_cube(project_dict=project_dict, id=cube_id)
    # Start data_model mutations by filling in the attributes element in case it's empty
    # only has effect if attributes element doesn't exist yet
    data_model_dict.setdefault("attributes", {})

    # used in attribute-key and keyed-attribute json elements
    ref_id = str(uuid.uuid4())
    # attribute-key element values. This seems mostly superfluous since the visible field also occures in keyed-attribute below which references this.
    # The main thing that changes is number of columns, which I believe is associated with key columns.
    attribute_key_dict = templates.create_attribute_key_dict(
        key_id=ref_id,
        # Number of columns in aggregate key. We create an aggregate key list below of all previously defined levels plus the calc col for this one
        columns=1,
        visible=visible,
    )
    data_model_dict["attributes"].setdefault("attribute-key", [])
    data_model_dict["attributes"]["attribute-key"].append(attribute_key_dict)

    # keyed-attribute element values
    keyed_attribute_id = str(uuid.uuid4())
    if base_name is None:
        base_name = column_name
    new_keyed_attribute = templates.create_keyed_attribute_dict(
        attribute_id=keyed_attribute_id,
        key_ref=ref_id,
        name=base_name,
        visible=visible,
        caption=caption,
        description=description,
    )
    data_model_dict["attributes"].setdefault("keyed-attribute", [])
    data_model_dict["attributes"]["keyed-attribute"].append(new_keyed_attribute)

    # create the dimension : start with hierarchy level and hierarchy
    # create the hierarchy level
    level_id = str(uuid.uuid4())
    new_level = templates.create_hierarchy_level_dict(
        visible=visible, level_id=level_id, keyed_attribute_id=keyed_attribute_id
    )

    # create a hierarchy
    hierarchy_id = str(uuid.uuid4())
    new_hierarchy = templates.create_hierarchy_dict(
        hierarchy_id=hierarchy_id,
        hierarchy_name=f"{base_name}_Hierarchy",
        caption=caption,
        folder=folder,
        description=description,
        visible=visible,
        levels=[new_level],
    )

    # create a new denormalized dimension dict with hierarchy
    dimension_id = str(uuid.uuid4())
    new_dimension = templates.create_dimension_dict(
        hierarchy_dict=new_hierarchy,
        dim_id=dimension_id,
        name=f"{base_name}_Dimension",
        visible=visible,
    )

    # add the new denomralized dimension to the data_model (dimensions usually sit in project but denormalized dimensions reside in the data_model)
    data_model_dict.setdefault("dimensions", {})
    data_model_dict["dimensions"].setdefault("dimension", [])
    data_model_dict["dimensions"]["dimension"].append(new_dimension)

    # Grab the data_set_ref in the data_model that references the dataset in the project. get_data_set_ref delists and returns the first dict inside of the data-set-ref list
    data_set_ref = data_model_parser.get_data_set_ref(
        data_model_dict=data_model_dict, dataset_id=dataset_id
    )
    # key-ref element under the "logical" json element.
    key_ref_dict = templates.create_attribute_key_ref_dict(
        key_id=ref_id, complete=True, columns=[column_name], unique=False
    )
    data_set_ref["logical"].setdefault("key-ref", [])
    data_set_ref["logical"]["key-ref"].append(key_ref_dict)
    # attribute-ref element under the "logical" element
    attribute_ref_dict = templates.create_attribute_ref_dict(
        columns=[column_name], attribute_id=keyed_attribute_id
    )
    data_set_ref["logical"].setdefault("attribute-ref", [])
    data_set_ref["logical"]["attribute-ref"].append(attribute_ref_dict)


def create_time_dimension_from_table(
    project_dict: dict,
    cube_id: str,
    dataset_id: str,
):
    """Mutates the provided project_dict in place to create a date dimension from a date table.

    Args:
        project_dict (dict): python dict for project
        cube_id (str): id for the cube
        dataset_id (str): id for the dataset containing the date info
    """

    # Let's get the dataset from the project so we can add calculated columns to it.
    # Remember there are datasets in project, and data-set-ref in the data model. We will have to modify both.
    dataset = project_parser.get_dataset(project_dict=project_dict, dataset_id=dataset_id)
    # need to account for db changing case
    if len([x for x in dataset.get("physical").get("columns") if x.get("name") == "year"]) > 0:
        year = "year"
        month = "month"
        date = "date"
        month_name = "month_name"
        day_name = "day_name"
    else:
        year = "YEAR"
        month = "MONTH"
        date = "DATE"
        month_name = "MONTH_NAME"
        day_name = "DAY_NAME"

    # Start data_model mutations by filling in the attributes element in case it's empty
    # setdefault only has effect if attributes element doesn't exist yet
    project_dict.setdefault("attributes", {})

    time_levels = [(year, TimeLevels.Year), (month, TimeLevels.Month), (date, TimeLevels.Day)]

    levels = {}  # we'll store levels as we go
    for level, level_type in time_levels:  # create a hierarchy level for each of the time_levels
        keys = [level]
        if level == month:
            keys.append(year)

        # used in attribute-key and keyed-attribute json elements
        ref_id = str(uuid.uuid4())

        # Set attribute-key element values. This seems mostly superfluous (but the data_model will break without it) since the visible field also occures in keyed-attribute
        # below which references this. The main thing that changes is number of columns, which I believe is associated with key columns.
        attribute_key_dict = templates.create_attribute_key_dict(
            key_id=ref_id, columns=len(keys), visible=True
        )
        project_dict["attributes"].setdefault("attribute-key", [])
        project_dict["attributes"]["attribute-key"].append(attribute_key_dict)

        # set keyed-attribute element values
        keyed_attribute_id = str(uuid.uuid4())
        keyed_attribute_name = level.lower()
        new_keyed_attribute = templates.create_keyed_attribute_dict(
            attribute_id=keyed_attribute_id,
            key_ref=ref_id,
            name=keyed_attribute_name,
            ordering="ascending",
            visible=True,
        )
        project_dict["attributes"].setdefault("keyed-attribute", [])
        project_dict["attributes"]["keyed-attribute"].append(new_keyed_attribute)

        # create the hierarchy level, to be used in creating the hierarchy and dimension below this loop
        level_id = str(uuid.uuid4())
        new_level = templates.create_hierarchy_level_dict(
            level_id=level_id,
            keyed_attribute_id=keyed_attribute_id,
            level_type=level_type.timestep,
            visible=True,
        )
        levels[level] = new_level

        # key-ref element under the "logical" json element.
        key_ref_dict = templates.create_attribute_key_ref_dict(
            key_id=ref_id, complete=True, columns=keys, unique=False
        )

        dataset["logical"].setdefault("key-ref", [])
        dataset["logical"]["key-ref"].append(key_ref_dict)
        # attribute-ref element under the "logical" element
        attribute_ref_dict = templates.create_attribute_ref_dict(
            columns=[level], attribute_id=keyed_attribute_id
        )
        dataset["logical"].setdefault("attribute-ref", [])
        dataset["logical"]["attribute-ref"].append(attribute_ref_dict)

    hierarchy_id = str(uuid.uuid4())
    new_hierarchy = templates.create_hierarchy_dict(
        hierarchy_id=hierarchy_id,
        hierarchy_name=f"date_hierarchy",
        levels=list(levels.values()),
        caption="date_hierarchy",
        description="",
        folder="",
        visible=True,
    )

    dimension_id = str(uuid.uuid4())
    new_dimension = templates.create_dimension_dict(
        hierarchy_dict=new_hierarchy,
        dim_id=dimension_id,
        name="date_dimension",
        time_dimension=True,
        visible=True,
        participating_datasets=[dataset_id],
    )

    # add the new dimension to the data_model
    project_dict.setdefault("dimensions", {})
    project_dict["dimensions"].setdefault("dimension", [])
    project_dict["dimensions"]["dimension"].append(new_dimension)

    # create the secondary attributes after the hierarchy
    feature_utils._create_secondary_attribute(
        cube_id,
        project_dict,
        dataset,
        new_feature_name="month_name",
        column_name=month_name,
        hierarchy_name="date_hierarchy",
        level_name="month",
    )
    feature_utils._create_secondary_attribute(
        cube_id,
        project_dict,
        dataset,
        new_feature_name="day_name",
        column_name=day_name,
        hierarchy_name="date_hierarchy",
        level_name="date",
    )

    return date.lower()
