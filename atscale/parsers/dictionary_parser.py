from typing import List, Dict, Callable


def create_empty_branches(
    json_reference: dict,
):
    pass


def path_exists(
    dict_item_this,
    dict_item_other,
    path: List[str],
):
    for key in path:
        if key in dict_item_this and key in dict_item_other:
            dict_item_this = dict_item_this[key]
            dict_item_other = dict_item_other[key]
        else:
            return False
    return True


def parse_dict_list(
    dict_list: list,
    key,
    value,
) -> dict:
    """Return the first dict in dict_list where dict.get(key)==value.
    This method does not search beyond the top level of the dict (since
    some values like 'id' recur multiple times)

    Args:
        dict_list (list): a list of python dictionaries
        key (_type_): the key to search for at the top level of the dict (i.e. this does not recurse)
        value (_type_): if key is found, the value it should have to return that dict

    Returns:
        dict: the dict in the dict_list where dict.get(key)==value
    """
    if dict_list is None:
        return None
    for d in dict_list:
        if d.get(key) == value:
            return d
    return None


def _find_by_id_or_name(
    item_list: List[dict],
    item_id: str = None,
    item_name: str = None,
    id_key: str = "id",
    name_key: str = "name",
):
    """Takes a list of dicts and either an id or name and returns the first item in the list that matches
    the given parameter"""
    if item_id is not None:
        key = id_key
        val = item_id
    elif item_name is not None:
        key = name_key
        val = item_name
    else:
        raise Exception("Either an id or name must be passed in order to identify the item")
    for item in item_list:
        if item[key] == val:
            return item
    else:
        return {}


def filter_dict(
    to_filter: dict,
    key_filters: List[Callable] = None,
    val_filters: List[Callable] = None,
):
    key_filters = [] if key_filters is None else key_filters
    val_filters = [] if val_filters is None else val_filters
    ret_dict = {}
    for key, value in to_filter.items():
        for filter in key_filters:
            if not filter(key):
                break
        else:
            for filter in val_filters:
                if not filter(value):
                    break
            else:
                ret_dict[key] = value
    return ret_dict


def filter_list_of_dicts(
    dict_list: List[dict],
    by: Dict[str, set],
):
    remaining = []
    for d in dict_list:
        pass_through = True
        for key, filter in by.items():
            if d.get(key) not in filter:
                pass_through = False
                break
        if pass_through:
            remaining.append(d)
    return remaining
