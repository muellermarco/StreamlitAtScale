import logging
from typing import Dict, List

from atscale.errors import atscale_errors

logger = logging.getLogger(__name__)


def _get_dataset_refs(
    cube_dict: Dict,
) -> List[Dict]:
    """
    Retrieves the list of datasets in the cube. Each dataset will be a dict  with information about columns and attached measures.
    Args:
        cube_dict : Dictionary argument that passes in the cube.
    Returns:
        List[Dict] : List of Dictionaries of datasets in the cube.
    """
    if cube_dict is None:
        return []
    ds_dict = cube_dict.get("data-sets", {})
    return ds_dict.get("data-set-ref", [])


def get_data_set_ref(
    data_model_dict: Dict,
    dataset_id: str,
) -> Dict:
    all_dataset_refs = [
        x for x in _get_dataset_refs(cube_dict=data_model_dict) if x["id"] == dataset_id
    ]
    if len(all_dataset_refs) < 1:
        raise atscale_errors.ObjectNotFoundError(f"No dataset with id {dataset_id} was found")
    return all_dataset_refs[0]


def _get_calculated_member_refs(
    cube_dict: Dict,
) -> List[Dict]:
    """Grabs the calculated members out of a cube dict.

    Args:
        cube_dict (Dict): a dict describing a calculated members

    Returns:
        List[Dict]: list of dictionaries describing the calculated member references
    """
    if cube_dict is None:
        return []
    return cube_dict.setdefault("calculated-members", {}).setdefault("calculated-member-ref", [])


def attributes_derived_from_ds(
    cube: Dict,
    dataset: Dict,
):
    """find attributes in the cube that are created based on a column in the given dataset THAT IS IN THE CUBE"""
    derived_features = []
    derived_attribute_id_to_name: Dict[str, str] = {}
    for att in cube.get("attributes", {}).get("attribute", {}):
        derived_attribute_id_to_name[att["id"]] = att["name"]
    for att in dataset["logical"].get("attribute-ref", []):
        if att["id"] in derived_attribute_id_to_name:
            derived_features.append(derived_attribute_id_to_name[att["id"]])
    return derived_features
