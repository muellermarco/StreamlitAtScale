import logging
import re
import uuid
from typing import Union, List, Dict

from atscale.base.enums import FeatureFormattingType, Hierarchy, Level, Aggs
from atscale.base.enums import MappedColumnFieldTerminator, MappedColumnKeyTerminator
from atscale.base.enums import MappedColumnDataTypes, FeatureType
from atscale.base.templates import create_attribute_ref_dict, create_calculated_member_dict
from atscale.base.templates import create_calculated_member_ref_dict, create_keyed_attribute_dict
from atscale.base.templates import create_attribute_key_dict, create_attribute_dict
from atscale.base.templates import create_attribute_key_ref_dict, create_column_dict
from atscale.base.templates import create_map_column_dict, create_measure_dict
from atscale.data_model import data_model_helpers
from atscale.errors import atscale_errors
from atscale.parsers import project_parser, data_model_parser
from atscale.utils import model_utils, project_utils
from atscale.utils.dmv_utils import get_dmv_data
from atscale.utils.input_utils import prompt_yes_no


def _create_secondary_attribute(
    cube_id,
    project_dict: Dict,
    data_set: dict,
    new_feature_name: str,
    column_name: str,
    hierarchy_name: str,
    level_name: str,
    description: str = None,
    caption: str = None,
    folder: str = None,
    visible: bool = True,
):
    """Creates a new secondary attribute on an existing hierarchy and level. Edits in place.

    Args:
        data_model (DataModel): The DataModel the hierarchy is expected to belong to.
        project_dict (Dict): the dictionary representation of the project
        data_set (Dict): The dict of the dataset containing the column that the feature will use.
        new_feature_name (str): What the attribute will be called.
        column_name (str): The column that the feature will use.
        hierarchy_name (str): What hierarchy to add the attribute to.
        level_name (str): What level of the hierarchy to add the attribute to.
        description (str, optional): The description for the attribute. Defaults to None.
        caption (str, optional): The caption for the attribute. Defaults to None.
        folder (str, optional): The folder for the attribute. Defaults to None.
        visible (bool, optional): Whether or not the feature will be visible to BI tools. Defaults to True.
    """

    if caption is None:
        caption = new_feature_name

    # we do it this way so we can use pass by reference to edit the base dict
    # cube_id = data_model.cube_id
    cube = project_parser.get_cube(project_dict=project_dict, id=cube_id)

    attribute_id = str(uuid.uuid4())
    ref_id = str(uuid.uuid4())

    degen = True
    if "attributes" in project_dict and "keyed-attribute" in project_dict["attributes"]:
        for attr in project_dict["attributes"]["keyed-attribute"]:
            if attr["name"] == level_name:
                level_id = attr["id"]
                degen = False
                break
    if "attributes" in cube and "keyed-attribute" in cube["attributes"]:
        for attr in cube["attributes"]["keyed-attribute"]:
            if attr["name"] == level_name:
                level_id = attr["id"]
                break

    new_attribute = create_attribute_dict(attribute_id=attribute_id)

    if degen:
        if "dimensions" in cube and "dimension" in cube.get("dimensions"):
            for dimension in cube["dimensions"]["dimension"]:
                for hier in dimension.get("hierarchy", []):
                    if "name" in hier and hier["name"] == hierarchy_name:
                        for l in hier.get("level", {"primary-attribute": None}):
                            if l["primary-attribute"] == level_id:
                                l.setdefault("keyed-attribute-ref", [])
                                l["keyed-attribute-ref"].append(new_attribute)

    else:
        if "dimensions" in project_dict and "dimension" in project_dict.get("dimensions"):
            for dimension in project_dict["dimensions"]["dimension"]:
                for hier in dimension.get("hierarchy", []):
                    if "name" in hier and hier["name"] == hierarchy_name:
                        for l in hier.get("level", {"primary-attribute": None}):
                            if l["primary-attribute"] == level_id:
                                l.setdefault("keyed-attribute-ref", [])
                                l["keyed-attribute-ref"].append(new_attribute)

    new_ref = create_attribute_ref_dict(
        columns=[column_name], complete=True, attribute_id=attribute_id
    )

    new_keyed_attribute = create_keyed_attribute_dict(
        attribute_id=attribute_id,
        key_ref=ref_id,
        name=new_feature_name,
        visible=visible,
        caption=caption,
        description=description,
        folder=folder,
    )

    new_attribute_key = create_attribute_key_dict(
        key_id=ref_id, columns=1, visible=visible
    )  # in project

    new_key_ref = create_attribute_key_ref_dict(
        key_id=ref_id, columns=[column_name], complete=True, unique=False
    )  # in project

    data_set.setdefault("logical", {})
    data_set["logical"].setdefault("attribute-ref", [])
    data_set["logical"]["attribute-ref"].append(new_ref)

    project_dict.setdefault("attributes", {})
    project_dict["attributes"].setdefault("keyed-attribute", [])
    project_dict["attributes"]["keyed-attribute"].append(new_keyed_attribute)

    project_dict["attributes"].setdefault("attribute-key", [])
    project_dict["attributes"]["attribute-key"].append(new_attribute_key)

    data_set["logical"].setdefault("key-ref", [])
    data_set["logical"]["key-ref"].append(new_key_ref)

    return project_dict


def _update_categorical_feature(
    project_dict: Dict,
    data_model_name: str,
    feature_name: str,
    description: str = None,
    caption: str = None,
    folder: str = None,
) -> bool:
    """Updates the metadata for an existing secondary attribute.

    Args:
        project_dict (Dict) the dictionary representation of the project
        data_model_name (str): The name of the data model to update.
        feature_name (str): The name of the feature to update.
        description (str, optional): The description for the feature. Defaults to None to leave unchanged.
        caption (str, optional): The caption for the feature. Defaults to None to leave unchanged.
        folder (str, optional): The folder to put the feature in. Defaults to None to leave unchanged.

    Returns:
        bool: returns True if changes were made, otherwise False.
    """
    if caption == "":
        caption = feature_name

    cube = [x for x in project_dict["cubes"]["cube"] if x["name"] == data_model_name][0]

    attributes = project_dict.get("attributes", {}).get("keyed-attribute", []) + cube.get(
        "attributes", {}
    ).get("keyed-attribute", [])
    attribute_sub_list = [x for x in attributes if x["name"] == feature_name]

    attribute = attribute_sub_list[0]
    any_updates = False
    if description is not None:
        attribute["properties"]["description"] = description
        any_updates = True
    if caption is not None:
        attribute["properties"]["caption"] = caption
        any_updates = True
    if folder is not None:
        attribute["properties"]["folder"] = folder
        any_updates = True

    return any_updates


def _create_filter_attribute(
    data_model,
    project_dict,
    new_feature_name: str,
    hierarchy_name: str,
    level_name: str,
    filter_values: List[str],
    caption: str = None,
    description: str = None,
    folder: str = None,
    visible: str = True,
):
    """Creates a new boolean secondary attribute to filter on a given subset of the level's values.

    Args:
        data_model (DataModel): The AtScale Data Model to run this operation on.
        project_dict (Dict): the dictionary representation of the project
        new_feature_name (str): The name of the new feature.
        hierarchy_name (str): The hierarchy the level belongs to.
        level_name (str): The name of the level to apply the filter to.
        filter_values (List[str]): The list of values to filter on.
        caption (str): The caption for the feature. Defaults to None.
        description (str): The description for the feature. Defaults to None.
        folder (str): The folder to put the feature in. Defaults to None.
        visible (bool): Whether the created attribute will be visible to BI tools. Defaults to True.
    """
    column_id = ""
    project_dict.setdefault("attributes", {})
    project_dict["attributes"].setdefault("keyed-attribute", [])
    project_ka_list = project_dict.get("attributes", {}).get("keyed_attribute", [])
    cube_ka_list = (
        model_utils._get_model_dict(data_model, project_dict)[0]
        .get("attributes", {})
        .get("keyed-attribute", [])
    )
    for keyed_attribute in project_ka_list + cube_ka_list:
        if keyed_attribute["name"] == level_name:
            column_id = keyed_attribute["id"]
            break
    found = False

    project_dsets = project_parser.get_datasets(project_dict=project_dict)
    cube_dsets = data_model_parser._get_dataset_refs(
        cube_dict=model_utils._get_model_dict(data_model, project_dict)[0]
    )

    for dataset in project_dsets + cube_dsets:
        for attribute in dataset.get("logical", {}).get("attribute-ref", []):
            if attribute["id"] == column_id:
                string_values = [f"'{value}'" for value in filter_values]
                expression = f"{attribute['column'][0]} in ({', '.join(string_values)})"
                calculated_column_name = new_feature_name + "_atscale_calc_"
                project_dataset = project_parser.get_dataset(
                    project_dict=project_dict, dataset_id=dataset["id"]
                )
                # need to make sure calculated column name isn't taken, otherwise two conflicting columns will exist
                # in other words, engine doesn't validate uniqueness of column names on publish or update
                counter = 1
                existing_columns = model_utils._get_columns(
                    project_dict=project_dict, dataset_name=project_dataset["name"]
                ).keys()
                while (calculated_column_name + str(counter)) in existing_columns:
                    counter += 1

                calculated_column_name = calculated_column_name + str(counter)
                dset_name = project_dataset["name"]
                project_utils.add_calculated_column_to_project_dataset(
                    atconn=data_model.project._atconn,
                    data_set=project_dataset,
                    column_name=calculated_column_name,
                    expression=expression,
                )

                data_set = project_parser.get_dataset(
                    project_dict=project_dict, dataset_name=dset_name
                )

                _create_secondary_attribute(
                    data_model.cube_id,
                    project_dict,
                    data_set=data_set,
                    new_feature_name=new_feature_name,
                    column_name=calculated_column_name,
                    hierarchy_name=hierarchy_name,
                    level_name=level_name,
                    description=description,
                    caption=caption,
                    folder=folder,
                    visible=visible,
                )
                found = True
                break
        if found:
            break


def _create_mapped_columns(
    dataset: Dict,
    column_name: str,
    mapped_names: List[str],
    data_types: List[MappedColumnDataTypes],
    key_terminator: MappedColumnKeyTerminator,
    field_terminator: MappedColumnFieldTerminator,
    map_key_type: MappedColumnDataTypes,
    map_value_type: MappedColumnDataTypes,
    first_char_delimited: bool = False,
):
    """Creates a mapped column.  Maps a column that is a key value structure into one or more new columns with the
    name of the given key(s). Types for the source keys and columns, and new columns are required. Valid types include
    'Int', 'Long', 'Boolean', 'String', 'Float', 'Double', 'Decimal', 'DateTime', and 'Date'. Changes are by reference

    Args:
        dataset (Dict): The dictionary representation of the dataset we're editing
        column_name (str): The name of the column.
        mapped_names (list str): The names of the mapped columns.
        data_types (list MappedColumnDataTypes): The types of the mapped columns.
        key_terminator (MappedColumnKeyTerminator): The key terminator. Valid values are ':', '=', and '^'
        field_terminator (MappedColumnFieldTerminator): The field terminator. Valid values are ',', ';', and '|'
        map_key_type (MappedColumnDataTypes): The mapping key type for all the keys in the origin column.
        map_value_type (MappedColumnDataTypes): The mapping value type for all values in the origin column.
        first_char_delimited (bool): Whether the first character is delimited. Defaults to False.

    Raises:
        atscale_errors.UserError: If the given dataset or column does not exist in the data model
    """

    dataset["physical"].setdefault("columns", [])
    dataset["physical"].setdefault("map-column", [])

    data_types_names = [x.name for x in data_types]
    cols = project_utils.create_dataset_columns_from_atscale_table_columns(
        list(zip(mapped_names, data_types_names))
    )
    new_map = create_map_column_dict(
        columns=cols,
        field_terminator=field_terminator,
        key_terminator=key_terminator,
        first_char_delim=first_char_delimited,
        map_key_type=map_key_type,
        map_value_type=map_value_type,
        column_name=column_name,
    )

    dataset["physical"]["map-column"].append(new_map)


def _add_column_mapping(
    dataset: Dict,
    column_name: str,
    mapped_name: str,
    data_type: MappedColumnDataTypes,
):
    """Adds a new mapping to an existing column mapping

    Args:
        dataset (Dict): The dictionary representation of the dataset we're editing
        column_name (str): The column the mapping belongs to.
        mapped_name (MappedColumnDataTypes): The name for the new mapped column.
        data_type (str): The data type of the new mapped column.
    """
    # since all of the error handing has been handled outside of this, we can just get right to the operation
    dataset["physical"].setdefault("map-column", [])
    mapping_cols = [c for c in dataset["physical"]["map-column"] if c["name"] == column_name]

    col = create_column_dict(name=mapped_name, data_type=data_type.value)
    col_map = mapping_cols[0]
    col_map["columns"]["columns"].append(col)


def _delete_measures(
    data_model,
    measure_list: List[str],
    json_dict: Dict,
    delete_children=None,
):
    """Same as delete_measure, but changes aren't pushed to AtScale. Only made on the given project_json.

    Args:
        data_model (DataModel): the atscale datamodel to work off of
        measure_list (List[str]): the query names of the measures to be deleted
        json_dict (Dict): the project_json to be edited
        delete_children (bool, optional): Defaults to None, if set to True or False, no prompt will be given in the case of
            any nested deletes occuring as a result of deleting the given measure_name. Instead, these measures will also be deleted when
            delete_children is True, alternatively, if False, the method will be aborted with no changes to the data model
    """

    measure_found: Dict[str, bool] = {measure: False for measure in measure_list}

    cube = project_parser.get_cube(project_dict=json_dict, id=data_model.cube_id)
    cube.setdefault("attributes", {})
    cube["attributes"].setdefault("attribute", [])
    cube_attributes = cube["attributes"]["attribute"]  # normal measures

    # need to avoid deleting calculated member definitions if they are used in a different cube
    calc_member_in_other_cubes = {}
    for c in project_parser.get_cubes(project_dict=json_dict):
        if c["id"] != data_model.cube_id:
            for cm_ref in data_model_parser._get_calculated_member_refs(cube_dict=cube):
                calc_member_in_other_cubes[cm_ref["id"]] = True

    name_to_id: Dict[str, str] = {}
    keep_id: Dict[str, bool] = {}

    for attribute in cube_attributes:
        name = attribute["name"]
        keep_id[attribute["id"]] = True
        name_to_id[name] = attribute["id"]
        if name in measure_found:
            if measure_found[name]:
                # Shouldn't happen
                raise ValueError(
                    f"There are multiple measures with the given name, '{name}', your project XML may be malformed."
                )
            else:
                measure_found[name] = True

    dependants_of: Dict[str, List[str]] = {}

    # assumes any cube calculated-member's id is in top level ref list (from project shared calculated members)
    calculated_members = project_parser._get_calculated_members(json_dict)
    cube_calculated_member_ref = data_model_parser._get_calculated_member_refs(cube_dict=cube)
    cube_calculated_member_ref_ids = [x["id"] for x in cube_calculated_member_ref]
    for attribute in calculated_members:
        name = attribute["name"]
        if attribute["id"] in cube_calculated_member_ref_ids:
            name_to_id[name] = attribute["id"]
            keep_id[attribute["id"]] = True
            _set_dependencies(calculated_measure=attribute, dependants_of=dependants_of)
            if name in measure_found:
                measure_found[name] = True

    # make sure all measures to delete were found
    missing_measures = [m for m in measure_list if not measure_found[m]]
    if missing_measures:
        raise atscale_errors.UserError(
            f"The following measures were not found in the data model: {missing_measures}. Make sure the measure names"
            " in the measure list parameter are the correctly spelled query name of a measure."
        )

    # retroactively set measures down family tree of measure_list to False for refiltering new lists
    for name in measure_list:
        keep_id[name_to_id[name]] = False
        new_dependants: List[str] = []
        if name in dependants_of:
            children = dependants_of[name]
            for child in children:
                if keep_id[name_to_id[child]]:
                    new_dependants.append(child)
        if new_dependants:
            if delete_children is None:
                should_delete = prompt_yes_no(
                    f"The following measures are dependent on {name}: "
                    f"{new_dependants} \nEnter yes to delete all of them or no to keep them"
                    f" and abort the deletion of all measures"
                )
            else:
                should_delete = delete_children
            if not should_delete:
                raise atscale_errors.DependentMeasureException(
                    f"Aborted deletions due to dependent measures"
                )
            else:
                measure_list += new_dependants

    # reparse lists to remove dependancies to delete
    attributes = [feat for feat in cube_attributes if keep_id[feat["id"]]]
    cube["attributes"]["attribute"] = attributes

    calculated_refs = [ref for ref in cube_calculated_member_ref if keep_id[ref["id"]]]
    cube["calculated-members"]["calculated-member-ref"] = calculated_refs

    new_calculated_members = []
    for measure in calculated_members:
        if keep_id.get(measure["id"], True) or calc_member_in_other_cubes.get(measure["id"]):
            new_calculated_members.append(measure)
    json_dict["calculated-members"]["calculated-member"] = new_calculated_members

    # parse datasets for removed measures attached
    datasets = data_model_parser._get_dataset_refs(cube_dict=cube)
    for ds in datasets:
        new_features = []
        features = ds["logical"].get("attribute-ref")
        if features is None:
            break
        for feat in features:
            if (feat["id"] not in keep_id) or keep_id[feat["id"]]:
                new_features.append(feat)
        ds["logical"]["attribute-ref"] = new_features

    # do we have to delete the measure from the perspective and parent cube


def _set_dependencies(
    calculated_measure: Dict,
    dependants_of: Dict[str, List[str]],
):
    """A helper for delete_measures_local to identify dependencies of the provided calculated measure

    Args:
        calculated_measure (Dict): the measure we are looking for dependencies of
        dependants_of (Dict[str, List[str]]): known {parent: [dependency]} relationship
    """
    parents: List[str] = re.findall(
        pattern=r"\[Measures]\.\[[a-zA-Z0-9\_\- ]*]", string=calculated_measure["expression"]
    )
    seen: Dict[str, bool] = {}
    for parent in parents:
        parent = parent[12:-1]  # remove [Measures].[
        if seen.get(parent):
            continue
        seen[parent] = True
        name = calculated_measure["name"]
        if parent in dependants_of:
            if name not in dependants_of[parent]:
                dependants_of[parent].append(name)
        else:
            dependants_of[parent] = [name]


def _check_draft_hierarchy(
    project_dict: dict,
    data_model_name: str,
    hierarchy_name: str,
    level_name: str,
    expect_base_input: bool = False,
    raise_error: bool = True,
    additional_error_message: str = None,
):
    """Queries the provided DataModel for the provided hierarchy name and level name to ensure both exist.

    Args:
        project_dict (dict): the metadata of the project to extract
        data_model_name (str): the name of the data_model of interest
        hierarchy_name (str): the hierarchy name to check for
        level_name (str): the level name to check for
        expect_base_input (bool, optional): if base names should be expected. Defaults to False
        raise_error (bool, optional): if the function should throw errors if it detects invalid levels/hierarchies. Defaults to True
        additional_error_message (str, optional): An additional message to add to the end of the error if desired. Defaults to None

    Returns:
        bool: True if level in hierarchy, else False
    """
    all_features = data_model_helpers._get_draft_features(
        project_dict=project_dict,
        data_model_name=data_model_name,
        feature_type=FeatureType.CATEGORICAL,
    )

    error_found = ""

    found_level_in_base = False
    found_level_in_published = False
    found_hierarchy_in_base = False
    found_hierarchy_in_published = False
    found_hierarchy_outside = False

    # first try to grab the level from the dict
    mapping_dict = all_features.get(level_name, {})
    if mapping_dict:
        found_level_in_published = True
        if mapping_dict.get("base_name", level_name) == level_name:
            found_level_in_base = True
    # if it isn't there we see if we got a base name for a roleplayed feature
    else:
        for key_val, item_val in all_features.items():
            if item_val.get("base_name") == level_name:
                mapping_dict = item_val
                found_level_in_base = True
                break

    # check if the hierarchy is in the base hierarchies
    if hierarchy_name in mapping_dict.get("base_hierarchy", hierarchy_name):
        # if we found the hierarchy and level where we expect we can return
        if expect_base_input and found_level_in_base:
            return True
        found_hierarchy_in_base = True
    # check if the hierarchy is in the non base hierarchies
    if hierarchy_name in mapping_dict.get("hierarchy", []):
        # if we found the hierarchy and level where we expect we can return
        if not expect_base_input and found_level_in_published:
            return True
        found_hierarchy_in_published = True

    # if we couldn't find the hierarchy in either of the level's lists see if it exists somewhere else
    if not found_hierarchy_in_published and not found_hierarchy_in_base:
        for key_val, item_val in all_features.items():
            if hierarchy_name in item_val.get("hierarchy", []) + item_val.get("base_hierarchy", []):
                found_hierarchy_outside = True
                break

    # if we get here something was wrong so go through the different error states
    if not found_level_in_base and not found_level_in_published:
        error_found = f"Invalid level name: {level_name}, not found in the data_model."

    if (
        not found_hierarchy_in_published
        and not found_hierarchy_in_base
        and not found_hierarchy_outside
    ):
        error_found = f"Invalid hierarchy name: {hierarchy_name}, not found in the data_model."

    if (found_level_in_base or found_level_in_published) and found_hierarchy_outside:
        error_found = f"Invalid hierarchy or level name: {level_name}, not found in hierarchy {hierarchy_name}."

    if expect_base_input:
        if found_level_in_published and not found_level_in_base:
            if found_hierarchy_in_published and not found_hierarchy_in_base:
                error_found = f"Invalid hierarchy and level name: Roleplayed level {level_name} and hierarchy {hierarchy_name} passed but function requires base names."
            else:
                error_found = f"Invalid level name: Roleplayed level {level_name} and base hierarchy {hierarchy_name} passed but function requires base names."
        else:
            if found_hierarchy_in_published and not found_hierarchy_in_base:
                error_found = f"Invalid hierarchy name: Roleplayed hierarchy {hierarchy_name} and base level {level_name} passed but function requires base names."
    else:
        if found_level_in_base and not found_level_in_published:
            if found_hierarchy_in_base and not found_hierarchy_in_published:
                error_found = f"Invalid hierarchy and level name: Base level {level_name} and hierarchy {hierarchy_name} passed but function requires roleplayed names."
            else:
                error_found = f"Invalid level name: Base level {level_name} and roleplayed hierarchy {hierarchy_name} passed but function requires roleplayed names."
        else:
            if found_hierarchy_in_base and not found_hierarchy_in_published:
                error_found = f"Invalid hierarchy name: Base hierarchy {hierarchy_name} and roleplayed level {level_name} passed but function requires roleplayed names."
    if additional_error_message:
        error_found = f"{error_found}\n{additional_error_message}"
    if raise_error:
        raise atscale_errors.UserError(error_found)
    return False


def _check_hierarchy(
    data_model,
    hierarchy_name: str,
    level_name: str,
):
    """Queries the provided DataModel for the provided hierarchy name and level name to ensure both exist.

    Args:
        data_model (DataModel): the atscale DataModel to query
        hierarchy_name (str): the hierarchy name to check for
        level_name (str): the level name to check for

    Returns:
        Tuple(dict, dict): a tuple of the hierarchy dict and the level dict of interest
    """
    hierarchy_dict = get_dmv_data(
        model=data_model,
        fields=[h for h in Hierarchy],
        id_field=Hierarchy.name,
        filter_by={Hierarchy.name: [hierarchy_name]},
    )

    hierarchy = hierarchy_dict.get(hierarchy_name)
    if hierarchy is None:
        raise atscale_errors.UserError(f"Hierarchy: {hierarchy_name} does not exist in the model")

    level_dict = None
    if level_name:
        level_dict = get_dmv_data(
            model=data_model,
            fields=[l for l in Level],
            filter_by={Level.hierarchy: [hierarchy_name]},
            id_field=Level.name,
        )
        level = level_dict.get(level_name)
        if level is None:
            level_dict_error_handle = get_dmv_data(
                model=data_model, fields=[Level.name, Level.hierarchy], id_field=Level.name
            )
            level_error_handle = level_dict_error_handle.get(level_name, {})
            if level_error_handle.get(Level.hierarchy.name) != hierarchy_name:
                raise atscale_errors.UserError(
                    f"Level: {level_name} does not exist in Hierarchy: {hierarchy_name}"
                )
            raise atscale_errors.UserError(f"Level: {level_name} does not exist in the model")

    return hierarchy_dict, level_dict


def _check_time_hierarchy(
    data_model,
    hierarchy_name: str,
    level_name: str = None,
):
    """Checks that the given hierarchy is a valid time hierarchy and (if given) that the level is in the hierarchy.

    Args:
        data_model (DataModel): The data_model the hierarchy is expected to belong to.
        hierarchy_name (str): The name of the hierarchy to assert is a time hierarchy.
        level_name (str, optional): An optional name of a level to assert is in the given time_hierarchy. Defaults to None

    Returns:
        Tuple(dict, dict): A tuple of the hierarchy dict and the level dict of interest
    """
    hierarchy_dict, level_dict = _check_hierarchy(
        data_model=data_model, hierarchy_name=hierarchy_name, level_name=level_name
    )

    if hierarchy_dict[hierarchy_name][Hierarchy.type.name] != "Time":
        raise atscale_errors.UserError(f"Hierarchy: {hierarchy_name} is not a time hierarchy")

    return hierarchy_dict, level_dict


def _create_calculated_feature(
    project_dict: dict,
    cube_id: str,
    name,
    expression,
    description=None,
    caption=None,
    folder=None,
    format_string: Union[FeatureFormattingType, str] = None,
    visible=True,
):
    """Creates a calculated feature in the provided project_json

    Args:
        project_dict (Dict) the dictionary representation of the project
        cube_id (str): the id of the cube to add the calculated feature to
        name (str): The name of the feature to create.
        expression (str): The expression for the feature.
        description (str): The description for the feature. Defaults to None to leave unchanged.
        caption (str): The caption for the feature. Defaults to None to leave unchanged.
        folder (str): The folder to put the feature in. Defaults to None to leave unchanged.
        format_string (Union[FeatureFormattingType, str]): The format string for the feature. Defaults to None to leave unchanged.
        visible (bool): Whether the updated feature should be visible. Defaults to None to leave unchanged.
    """
    if isinstance(format_string, FeatureFormattingType):
        formatting = {"named-format": format_string.value}
    elif format_string is None:
        formatting = None
    else:
        formatting = {"format-string": format_string}  # an actual format string like %DD-%m

    if caption is None:
        caption = name

    uid = str(uuid.uuid4())

    new_calc_measure = create_calculated_member_dict(
        id=uid,
        member_name=name,
        expression=expression,
        caption=caption,
        visible=visible,
        description=description,
        formatting=formatting,
        folder=folder,
    )

    calculated_members = project_parser._get_calculated_members(project_dict)
    calculated_members.append(new_calc_measure)

    cube = project_parser.get_cube(project_dict=project_dict, id=cube_id)

    new_ref = create_calculated_member_ref_dict(id=uid)
    calculated_members_refs = data_model_parser._get_calculated_member_refs(cube)
    calculated_members_refs.append(new_ref)


def _update_calculated_feature(
    project_dict: Dict,
    feature_name: str,
    expression: str = None,
    description: str = None,
    caption: str = None,
    folder: str = None,
    format_string: Union[FeatureFormattingType, str] = None,
    visible: bool = None,
):
    """Update the metadata for a calculated feature.

    Args:
        project_dict (Dict) the dictionary representation of the project
        feature_name (str): The name of the feature to update.
        expression (str): The expression for the feature. Defaults to None to leave unchanged.
        description (str): The description for the feature. Defaults to None to leave unchanged.
        caption (str): The caption for the feature. Defaults to None to leave unchanged.
        folder (str): The folder to put the feature in. Defaults to None to leave unchanged.
        format_string (Union[FeatureFormattingType, str]): The format string for the feature. Defaults to None to leave unchanged.
        visible (bool): Whether the updated feature should be visible. Defaults to None to leave unchanged.
    """

    if isinstance(format_string, FeatureFormattingType):
        formatting = {"named-format": format_string.value}
    else:
        formatting = {"format-string": format_string}  # an actual format string like %DD-%m or None

    if caption == "":
        caption = feature_name

    measure = [
        x
        for x in project_dict["calculated-members"]["calculated-member"]
        if x["name"] == feature_name
    ][0]

    measure.setdefault("properties", {})
    if expression is not None:
        measure["expression"] = expression
    if description is not None:
        measure["properties"]["description"] = description
    if caption is not None:
        measure["properties"]["caption"] = caption
    if folder is not None:
        measure["properties"]["folder"] = folder
    if visible is not None:
        measure["properties"]["visible"] = visible
    if format_string is not None:
        if format_string == "":
            measure["properties"].pop("formatting", not_found=None)
        else:
            measure["properties"]["formatting"] = formatting


def _create_aggregate_feature(
    project_dict: dict,
    cube_id: str,
    dataset_id: str,
    column_name: str,
    new_feature_name: str,
    aggregation_type: Aggs,
    description: str = None,
    caption: str = None,
    folder: str = None,
    format_string: Union[FeatureFormattingType, str] = None,
    visible: bool = True,
):
    """Creates an aggregate feature in the provided project_json

    Args:
        project_dict (Dict) the dictionary representation of the project
        cube_id (str): the id of the cube to add the calculated feature to
        dataset_id (str): the id of the dataset to find the column in
        column_name (str): the name of the column to build the agg off of
        new_feature_name (str): The new_feature_name of the feature to create.
        aggregation_type (Aggs): the type of aggregation for the created feature
        description (str): The description for the feature. Defaults to None to leave unchanged.
        caption (str): The caption for the feature. Defaults to None to leave unchanged.
        folder (str): The folder to put the feature in. Defaults to None to leave unchanged.
        format_string (Union[FeatureFormattingType, str]): The format string for the feature. Defaults to None to leave unchanged.
        visible (bool): Whether the updated feature should be visible. Defaults to None to leave unchanged.
    """

    if isinstance(format_string, FeatureFormattingType):
        formatting = {"named-format": format_string.value}
    elif format_string is None:
        formatting = None
    else:
        formatting = {"format-string": format_string}  # an actual format string like %DD-%m

    if caption is None:
        caption = new_feature_name

    uid = str(uuid.uuid4())

    cube = project_parser.get_cube(project_dict=project_dict, id=cube_id)
    cube_dataset = data_model_parser.get_data_set_ref(data_model_dict=cube, dataset_id=dataset_id)
    cube_dataset.setdefault("logical", {})
    cube_dataset["logical"].setdefault("key-ref", [])
    cube_dataset["logical"].setdefault("attribute-ref", [])
    key_ref_id = None

    if aggregation_type.requires_key_ref():
        key_ref_id = str(uuid.uuid4())
        # create attribute key in cube
        attribute_key_dict = create_attribute_key_dict(
            key_id=key_ref_id, columns=1, visible=visible
        )
        cube["attributes"].setdefault("attribute-key", [])
        cube["attributes"]["attribute-key"].append(attribute_key_dict)
        # create key ref in dataset ref
        key_ref_for_dataset = create_attribute_key_ref_dict(
            key_id=key_ref_id, columns=[column_name], complete=True, unique=False
        )
        cube_dataset["logical"]["key-ref"].append(key_ref_for_dataset)

    new_measure = create_measure_dict(
        measure_id=uid,
        measure_name=new_feature_name,
        agg_type=aggregation_type,
        caption=caption,
        visible=visible,
        description=description,
        formatting=formatting,
        folder=folder,
        key_ref=key_ref_id,
    )

    cube.setdefault("attributes", {})
    cube["attributes"].setdefault("attribute", [])
    cube["attributes"]["attribute"].append(new_measure)

    new_ref = create_attribute_ref_dict(columns=[column_name], attribute_id=uid, complete=True)
    cube_dataset["logical"]["attribute-ref"].append(new_ref)


def _update_aggregate_feature(
    project_dict: Dict,
    cube_id: str,
    feature_name: str,
    description: str = None,
    caption: str = None,
    folder: str = None,
    format_string: Union[FeatureFormattingType, str] = None,
    visible: bool = None,
):
    """Update the metadata for an aggregate feature.

    Args:
        project_dict (Dict) the dictionary representation of the project
        cube_id (str): the id of the cube.
        feature_name (str): The name of the feature to update.
        description (str): The description for the feature. Defaults to None to leave unchanged.
        caption (str): The caption for the feature. Defaults to None to leave unchanged.
        folder (str): The folder to put the feature in. Defaults to None to leave unchanged.
        format_string (Union[FeatureFormattingType, str]): The format string for the feature. Defaults to None to leave unchanged.
        visible (bool, optional): Whether or not the feature will be visible to BI tools. Defaults to None to leave unchanged.
    """

    if isinstance(format_string, FeatureFormattingType):
        formatting = {"named-format": format_string.value}
    else:
        formatting = {"format-string": format_string}

    if caption == "":
        caption = feature_name

    cube = project_parser.get_cube(project_dict=project_dict, id=cube_id)

    measure = [x for x in cube["attributes"]["attribute"] if x["name"] == feature_name][0]
    measure.setdefault("properties", {})

    if description is not None:
        measure["properties"]["description"] = description
    if caption is not None:
        measure["properties"]["caption"] = caption
    if folder is not None:
        measure["properties"]["folder"] = folder
    if visible is not None:
        measure["properties"]["visible"] = visible
    if format_string is not None:
        if format_string == "":
            measure["properties"].pop("formatting", not_found=None)
        else:
            measure["properties"]["formatting"] = formatting


def _create_rolling_agg(
    project_dict: Dict,
    cube_id: str,
    time_dimension: str,
    agg_type,
    new_feature_name: str,
    numeric_feature_name: str,
    time_length: int,
    hierarchy_name: str,
    level_name: str,
    description: str = None,
    caption: str = None,
    folder: str = None,
    format_string: Union[FeatureFormattingType, str] = None,
    visible: bool = None,
):
    """Creates a rolling aggregation feature of the procided type.

    Args:
        project_dict (Dict) the dictionary representation of the project
        cube_id (str): the id of the cube.
        time_dimension (str): the time dimension of the given hierarchy
        agg_type (MDXAggs): The type of aggregation to do for the rolling calc.
        new_feature_name (str): What the created feature will be called
        numeric_feature_name (str): The numeric feature to use for the calculation
        time_length (int): The length of time the feature should be calculated over
        hierarchy_name (str): The time hierarchy used in the calculation
        level_name (str): The level within the time hierarchy
        description (str, optional): The description for the feature. Defaults to None.
        caption (str, optional): The caption for the feature. Defaults to None.
        folder (str, optional): The folder to put the feature in. Defaults to None.
        format_string (Union[FeatureFormattingType, str], optional): The format string for the feature. Defaults to None.
        visible (bool, optional): Whether the feature will be visible to BI tools. Defaults to True.
    """
    expression = (
        agg_type.value + f"("
        f"ParallelPeriod([{time_dimension}].[{hierarchy_name}].[{level_name}]"
        f", {time_length - 1}, [{time_dimension}].[{hierarchy_name}].CurrentMember)"
        f":[{time_dimension}].[{hierarchy_name}].CurrentMember, [Measures].[{numeric_feature_name}])"
    )

    _create_calculated_feature(
        project_dict,
        cube_id=cube_id,
        name=new_feature_name,
        expression=expression,
        description=description,
        caption=caption,
        folder=folder,
        format_string=format_string,
        visible=visible,
    )
    return f'Successfully created measure \'{new_feature_name}\' {f"in folder {folder}" if folder else ""}'


def _create_lag_feature(
    project_dict: Dict,
    cube_id: str,
    time_dimension: str,
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
):
    """Creates a lagged feature based on the numeric feature and time hierarchy passed in.

    Args:
        project_dict (Dict): the dictionary representation of the project of interest
        cube_id (str): the unique idenitifier for this cube
        time_dimension (str): the query name of the time dimension we lag over
        new_feature_name (str): The name of the feature to create.
        numeric_feature_name (str): The numeric feature to lag.
        hierarchy_name (str): The time hierarchy to use for the lag.
        level_name (str): The level of the hierarchy to use for the lag.
        time_length (int): The length of the lag.
        description (str, optional): A description for the feature. Defaults to None.
        caption (str, optional): A caption for the feature. Defaults to None.
        folder (str, optional): The folder to put the feature in. Defaults to None.
        format_string (Union[FeatureFormattingType, str], optional): A format sting for the feature. Defaults to None.
        visible (bool, optional): Whether the feature should be visible. Defaults to True.
    """

    expression = (
        f"(ParallelPeriod([{time_dimension}].[{hierarchy_name}].[{level_name}], {time_length}"
        f", [{time_dimension}].[{hierarchy_name}].CurrentMember), [Measures].[{numeric_feature_name}])"
    )

    _create_calculated_feature(
        project_dict,
        cube_id=cube_id,
        name=new_feature_name,
        expression=expression,
        description=description,
        caption=caption,
        folder=folder,
        format_string=format_string,
        visible=visible,
    )


def _create_time_differencing_feature(
    project_dict: Dict,
    cube_id: str,
    time_dimension: str,
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
):
    """Creates a time over time subtraction calculation. For example, create_time_differencing on the feature 'revenue',
    time level 'date', and a length of 2 will create a feature calculating the revenue today subtracted by the revenue
    two days ago

    Args:
        project_dict (Dict): the dictionary representation of the project of interest
        cube_id (str): the unique idenitifier for this cube
        time_dimension (str): the query name of the time dimension we lag over
        new_feature_name (str): What the feature will be called.
        numeric_feature_name (str): The numeric feature to use for the calculation.
        hierarchy_name (str): The time hierarchy used in the calculation.
        level_name (str): The level within the time hierarchy
        time_length (int): The length of the lag in units of the given level of the given time_hierarchy.
        description (str): The description for the feature. Defaults to None.
        caption (str): The caption for the feature. Defaults to None.
        folder (str): The folder to put the feature in. Defaults to None.
        format_string (Union[FeatureFormattingType, str], optional): A format sting for the feature. Defaults to None.
        visible (bool, optional): Whether the feature should be visible. Defaults to True.
    """
    expression = (
        f"CASE WHEN IsEmpty((ParallelPeriod([{time_dimension}].[{hierarchy_name}].[{level_name}], {time_length}"
        f", [{time_dimension}].[{hierarchy_name}].CurrentMember), [Measures].[{numeric_feature_name}])) "
        f"THEN 0 ELSE ([Measures].[{numeric_feature_name}]"
        f"-(ParallelPeriod([{time_dimension}].[{hierarchy_name}].[{level_name}], {time_length}"
        f", [{time_dimension}].[{hierarchy_name}].CurrentMember), [Measures].[{numeric_feature_name}])) END"
    )

    _create_calculated_feature(
        project_dict=project_dict,
        cube_id=cube_id,
        name=new_feature_name,
        expression=expression,
        description=description,
        caption=caption,
        folder=folder,
        format_string=format_string,
        visible=visible,
    )


def _create_percentage_feature(
    project_dict: Dict,
    cube_id: str,
    new_feature_name: str,
    numeric_feature_name: str,
    dimension_name: str,
    hierarchy_name: str,
    level_name: str,
    description=None,
    caption=None,
    folder=None,
    format_string=None,
    visible=True,
):
    """Creates a features calculating the percentage of the given numeric_feature's value compared to the
    given level in a hierarchy

    Args:
        project_dict (Dict): the dictionary representation of the project of interest
        cube_id (str): the unique idenitifier for this cube
        new_feature_name (str): What the feature will be called.
        numeric_feature_name (str): The numeric feature to use for the calculation.
        dimension_name (str): the hierarchy dimension name to use
        hierarchy_name (str): The time hierarchy used in the calculation.
        level_name (str): The level within the time hierarchy
        description (str): The description for the feature. Defaults to None.
        caption (str): The caption for the feature. Defaults to None.
        folder (str): The folder to put the feature in. Defaults to None.
        format_string (Union[FeatureFormattingType, str], optional): A format sting for the feature. Defaults to None.
        visible (bool, optional): Whether the feature should be visible. Defaults to True.
    """
    expression = (
        f"IIF( (Ancestor([{dimension_name}].[{hierarchy_name}].currentMember"
        f", [{dimension_name}].[{hierarchy_name}].[{level_name}]), "
        f"[Measures].[{numeric_feature_name}]) = 0, NULL, "
        f"[Measures].[{numeric_feature_name}]"
        f" / (Ancestor([{dimension_name}].[{hierarchy_name}].currentMember"
        f", [{dimension_name}].[{hierarchy_name}].[{level_name}]), [Measures].[{numeric_feature_name}]))"
    )
    _create_calculated_feature(
        project_dict=project_dict,
        cube_id=cube_id,
        name=new_feature_name,
        expression=expression,
        description=description,
        caption=caption,
        folder=folder,
        format_string=format_string,
        visible=visible,
    )


def _create_period_to_date_feature(
    project_dict: Dict,
    cube_id: str,
    new_feature_name: str,
    numeric_feature_name: str,
    hierarchy_name: str,
    level_name: str,
    base_name: str,
    time_dimension: str,
    description: str = None,
    folder: str = None,
    format_string: Union[FeatureFormattingType, str] = None,
    visible: bool = True,
):
    """Creates a period-to-date calculation in place in the provided project_dict

    Args:
        project_dict (Dict): the dictionary representation of the project of interest
        cube_id (str): the unique idenitifier for this cube
        new_feature_name (str): What the feature will be called.
        numeric_feature_name (str): The numeric feature to use for the calculation.
        hierarchy_name (str): The time hierarchy used in the calculation.
        level_name (str): The level within the time hierarchy
        base_name (str): the name of the base level to agg over, for the description
        time_dimension (str): the time dimension to agg over
        description (str): The description for the feature. Defaults to None.
        caption (str): The caption for the feature. Defaults to None.
        folder (str): The folder to put the feature in. Defaults to None.
        format_string (Union[FeatureFormattingType, str], optional): A format sting for the feature. Defaults to None.
        visible (bool, optional): Whether the feature should be visible. Defaults to True.
    """
    true_description = (
        f"A sum of {numeric_feature_name} from all {base_name} entries in the past "
        f'{level_name}. \n {description if description else ""}'
    )
    expression = (
        f"CASE WHEN IsEmpty([Measures].[{numeric_feature_name}]) THEN NULL ELSE "
        f"Sum(PeriodsToDate([{time_dimension}].[{hierarchy_name}].[{level_name}], "
        f"[{time_dimension}].[{hierarchy_name}].CurrentMember), [Measures].[{numeric_feature_name}]) END"
    )
    _create_calculated_feature(
        project_dict=project_dict,
        cube_id=cube_id,
        name=new_feature_name,
        expression=expression,
        description=true_description,
        caption=None,
        folder=folder,
        format_string=format_string,
        visible=visible,
    )


def _get_cov_str(
    dimension: str,
    hierarchy_name: str,
    numeric_feature_1_name: str,
    numeric_feature_2_name: str,
    leaf_level: str,
    use_sample: bool,
) -> str:
    """Creates the MDX query for a covariance feature.

    Args:
        dimension (str): The dimension used in the calculation
        hierarchy_name (str): The query name of the hierarchy used in the calculation
        numeric_feature_1_name (str): The query name of the first feature in the calculation
        numeric_feature_2_name (str): The query name of the second feature in the calculation
        leaf_level (str): The lowest level of the given hierarchy
        use_sample (bool): Whether the calculation is a sample calculation.

    Returns:
        str: The appropriate MDX expression.
    """
    ddof = 1
    if not use_sample:
        ddof -= 1  # I.e., ddof = 0 if a population calculation

    count_str = (
        f"Sum("
        f"Descendants("
        f"[{dimension}].[{hierarchy_name}].CurrentMember,"
        f"[{dimension}].[{hierarchy_name}].[{leaf_level}]"
        f"),"
        f"(CASE WHEN IsEmpty([Measures].{numeric_feature_1_name}) OR "
        f"IsEmpty([Measures].{numeric_feature_2_name}) THEN 0 "
        f"ELSE 1 END)"
        f")"
    )

    sum_str_1 = (
        f"Sum("
        f"Descendants("
        f"[{dimension}].[{hierarchy_name}].CurrentMember,"
        f"[{dimension}].[{hierarchy_name}].[{leaf_level}]"
        f")"
        f"[Measures].{numeric_feature_1_name})"
    )

    sum_str_2 = (
        f"Sum("
        f"Descendants("
        f"[{dimension}].[{hierarchy_name}].CurrentMember,"
        f"[{dimension}].[{hierarchy_name}].[{leaf_level}]"
        f")"
        f"[Measures].{numeric_feature_2_name})"
    )

    avg_str_1 = (
        f"Avg("
        f"Descendants("
        f"[{dimension}].[{hierarchy_name}].CurrentMember,"
        f"[{dimension}].[{hierarchy_name}].[{leaf_level}]"
        f")"
        f"[Measures].{numeric_feature_1_name})"
    )

    avg_str_2 = (
        f"Avg("
        f"Descendants("
        f"[{dimension}].[{hierarchy_name}].CurrentMember,"
        f"[{dimension}].[{hierarchy_name}].[{leaf_level}]"
        f")"
        f"[Measures].{numeric_feature_2_name})"
    )

    col_prod_sum_str = (
        f"Sum("
        f"Descendants("
        f"[{dimension}].[{hierarchy_name}].CurrentMember,"
        f"[{dimension}].[{hierarchy_name}].[{leaf_level}]"
        f")"
        f"[Measures].[{numeric_feature_1_name}] * [Measures].[{numeric_feature_2_name}])"
    )

    col_ey_prod_sum_str = f"({avg_str_2}) * ({sum_str_1})"

    col_ex_prod_sum_str = f"({avg_str_1}) * ({sum_str_2})"

    ex_ey_prod_sum_str = f"({avg_str_1}) * ({avg_str_2}) * ({count_str})"

    cov_str = (
        f"(1 / ({count_str} - {ddof})) * ("
        f"({col_prod_sum_str}) - "
        f"({col_ey_prod_sum_str}) - "
        f"({col_ex_prod_sum_str}) + "
        f"({ex_ey_prod_sum_str})"
        f")"
    )

    return cov_str


def _get_corr_str(
    dimension: str,
    hierarchy_name: str,
    numeric_feature_1_name: str,
    numeric_feature_2_name: str,
    leaf_level: str,
) -> str:
    """Creates the MDX query for a correlation feature.

    Args:
        dimension (str): The dimension used in the calculation
        hierarchy_name (str): The query name of the hierarchy used in the calculation
        numeric_feature_1_name (str): The query name of the first feature in the calculation
        numeric_feature_2_name (str): The query name of the second feature in the calculation
        leaf_level (str): The lowest level of the given hierarchy

    Returns:
        str: The appropriate MDX expression.
    """
    # NOTE: We fix the behavior to sample std/cov since the choice doesn't matter for corrcoef
    std_str_1 = (
        f"Stdev("
        f"Descendants("
        f"[{dimension}].[{hierarchy_name}].CurrentMember,"
        f"[{dimension}].[{hierarchy_name}].[{leaf_level}]"
        f")"
        f"[Measures].{numeric_feature_1_name})"
    )

    std_str_2 = (
        f"Stdev("
        f"Descendants("
        f"[{dimension}].[{hierarchy_name}].CurrentMember,"
        f"[{dimension}].[{hierarchy_name}].[{leaf_level}]"
        f")"
        f"[Measures].{numeric_feature_2_name})"
    )

    cov_str = _get_cov_str(
        dimension=dimension,
        hierarchy_name=hierarchy_name,
        numeric_feature_1_name=numeric_feature_1_name,
        numeric_feature_2_name=numeric_feature_2_name,
        leaf_level=leaf_level,
        use_sample=True,
    )

    return (
        f"CASE WHEN ({std_str_1}) = 0 OR ({std_str_2}) = 0 THEN NULL "
        f"ELSE ({cov_str}) / (({std_str_1}) * ({std_str_2})) "
        f"END"
    )
