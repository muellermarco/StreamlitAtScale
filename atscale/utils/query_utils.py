import datetime
import inspect
import json
import re
import logging
from typing import Dict, List, Tuple
from inspect import getfullargspec
from atscale.utils.validation_utils import validate_by_type_hints
from atscale.errors import atscale_errors
from atscale.base import config
from atscale.parsers import project_parser
from atscale.data_model import data_model_helpers
from atscale.utils import model_utils
from atscale.utils import validation_utils
from atscale.base.enums import RequestType, FeatureType, CheckFeaturesErrMsg
from atscale.base import endpoints

logger = logging.getLogger(__name__)


def _generate_atscale_query(
    data_model,
    feature_list: List[str],
    filter_equals: Dict[str, str] = None,
    filter_greater: Dict[str, str] = None,
    filter_less: Dict[str, str] = None,
    filter_greater_or_equal: Dict[str, str] = None,
    filter_less_or_equal: Dict[str, str] = None,
    filter_not_equal: Dict[str, str] = None,
    filter_in: Dict[str, List[str]] = None,
    filter_between: Dict[str, Tuple[str, str]] = None,
    filter_like: Dict[str, str] = None,
    filter_rlike: Dict[str, str] = None,
    filter_null: List[str] = None,
    filter_not_null: List[str] = None,
    order_by: List[Tuple[str, str]] = None,
    limit: int = None,
    comment: str = None,
    use_aggs: bool = True,
    gen_aggs: bool = True,
    raise_multikey_warning: bool = True,
) -> str:
    """Generates an AtScale query to get the given features.

    Args:
        data_model (DataModel): The AtScale DataModel that the generated query interacts with.
        feature_list (List[str]): The list query names for the features to query.
        filter_equals (Dict[str:str], optional): Filters results based on the feature equaling the value. Defaults
             to None
        filter_greater (Dict[str:str], optional): Filters results based on the feature being greater than the value.
             Defaults to None
        filter_less (Dict[str:str], optional): Filters results based on the feature being less than the value.
            Defaults to None
        filter_greater_or_equal (Dict[str:str], optional): Filters results based on the feature being greater or
            equaling the value. Defaults to None
        filter_less_or_equal (Dict[str:str], optional): Filters results based on the feature being less or equaling
            the value. Defaults to None
        filter_not_equal (Dict[str:str], optional): Filters results based on the feature not equaling the value.
            Defaults to None
        filter_in (Dict[str:List(str)], optional): Filters results based on the feature being contained in the values.
            Takes in a list of str as the dictionary values. Defaults to None
        filter_between (Dict[str:(str,str)], optional): Filters results based on the feature being between the values.
             Defaults to None
        filter_like (Dict[str:str], optional): Filters results based on the feature being like the clause. Defaults
            to None
        filter_rlike (Dict[str:str], optional): Filters results based on the feature being matched by the regular
            expression. Defaults to None
        filter_null (Dict[str:str], optional): Filters results to show null values of the specified features.
            Defaults to None
        filter_not_null (Dict[str:str], optional): Filters results to exclude null values of the specified
            features. Defaults to None
        order_by (List[Tuple[str, str]]): The sort order for the query. Accepts a list of tuples of the
                feature query name and ordering respectively: [('feature_name_1', 'DESC'), ('feature_2', 'ASC') ...].
                Defaults to None for AtScale Engine default sorting.
        limit (int, optional): Limit the number of results. Defaults to None for no limit.
        comment (str, optional): A comment string to build into the query. Defaults to None for no comment.
        raise_multikey_warning (str, optional): Whether to warn if a query contains attributes that have multiple key columns. Defaults to True.

    Returns:
        str: An AtScale query string
    """
    inspection = inspect.getfullargspec(_generate_atscale_query)
    validation_utils.validate_by_type_hints(inspection=inspection, func_params=locals())

    filter_equals = {} if filter_equals is None else filter_equals
    filter_greater = {} if filter_greater is None else filter_greater
    filter_less = {} if filter_less is None else filter_less
    filter_greater_or_equal = {} if filter_greater_or_equal is None else filter_greater_or_equal
    filter_less_or_equal = {} if filter_less_or_equal is None else filter_less_or_equal
    filter_not_equal = {} if filter_not_equal is None else filter_not_equal
    filter_in = {} if filter_in is None else filter_in
    filter_between = {} if filter_between is None else filter_between
    filter_like = {} if filter_like is None else filter_like
    filter_rlike = {} if filter_rlike is None else filter_rlike
    filter_null = [] if filter_null is None else filter_null
    filter_not_null = [] if filter_not_null is None else filter_not_null
    order_by = [] if order_by is None else order_by

    # separate ordering features into a list to verify existence in the model while also turning tuples into 'feat DESC'
    ordering_strings = []
    ordering_features = []

    error_items = []
    for maybe_tuple in order_by:
        if not (
            isinstance(maybe_tuple, tuple)
            and len(maybe_tuple) == 2
            and isinstance(maybe_tuple[0], str)
            and isinstance(maybe_tuple[1], str)
            and maybe_tuple[1].upper() in ["ASC", "DESC"]
        ):
            error_items.append(maybe_tuple)
        else:
            ordering_strings.append(f"`{maybe_tuple[0]}` {maybe_tuple[1].upper()}")
            ordering_features.append(maybe_tuple[0])

    if error_items:
        raise atscale_errors.UserError(
            f"All items in the order_by parameter must be a tuple of a "
            f'feature name then "ASC" or "DESC". The following do not '
            f"comply: {error_items}"
        )

    all_features = data_model.get_features()
    list_all = set(
        all_features
    )  # turns it into a set of the keys and has constant time lookup on average

    model_utils._check_features(
        features=feature_list,
        check_list=list_all,
        errmsg=CheckFeaturesErrMsg.ALL.get_errmsg(is_published=True),
    )

    deduped_feature_list = []  # need to remove duplicates before sending to engine
    feature_set = set()
    repeats = []
    for f in feature_list:
        if f not in feature_set:
            deduped_feature_list.append(f)
            feature_set.add(f)
        else:
            repeats.append(f)

    if repeats:
        logger.info(
            f"The following feature names appear more than once in the feature_list parameter: {set(repeats)}. "
            f"Any repeat occurrences have been omitted."
        )
    feature_list = deduped_feature_list

    # check to make sure no columns of a multi-key are excluded
    if raise_multikey_warning:
        project_dict = data_model.project._get_dict()

        # get the subset of all columns that are non-measures and then see if any of the features overlap
        categoricals = data_model_helpers._get_draft_features(
            project_dict=project_dict,
            data_model_name=data_model.name,
            feature_list=feature_list,
            feature_type=FeatureType.CATEGORICAL,
        )
        features_to_validate = {
            key: value.get("base_name", key) for key, value in categoricals.items()
        }

        if features_to_validate:
            features_needed = project_parser._get_feature_keys(
                project_dict=project_dict,
                cube_id=data_model.cube_id,
                join_features=list(features_to_validate.values()),
            )

            for feature_name, base_name in features_to_validate.items():
                key_columns = features_needed[base_name]["key_cols"]
                if len(key_columns) > 1:
                    logger.warning(
                        f"Feature: {feature_name} has a compound key, "
                        f"features representing all key columns {key_columns} should "
                        f"be included to avoid ambiguous results"
                    )

    # check elements of the filters
    list_params = [
        filter_equals,
        filter_greater,
        filter_less,
        filter_greater_or_equal,
        filter_less_or_equal,
        filter_not_equal,
        filter_in,
        filter_between,
        filter_like,
        filter_rlike,
        filter_null,
        filter_not_null,
    ]
    for param in list_params + [ordering_features]:
        model_utils._check_features(
            features=param,
            check_list=list_all,
            errmsg=CheckFeaturesErrMsg.ALL.get_errmsg(is_published=True),
        )

    if ordering_strings:
        order_string = f' ORDER BY {", ".join(ordering_strings)}'
    else:
        categorical_columns = [
            f"`{name}`"
            for name in feature_list
            if all_features[name]["feature_type"].upper() == FeatureType.CATEGORICAL.name
        ]
        order_string = f' ORDER BY {", ".join(categorical_columns)}' if categorical_columns else ""

    all_columns_string = " " + ", ".join(f"`{x}`" for x in feature_list)

    if any(list_params):
        filter_string = " WHERE ("
        for key, value in filter_equals.items():
            if filter_string != " WHERE (":
                filter_string += " and "
            if not isinstance(value, (int, float, bool)):
                if value in list_all:
                    filter_string += f"(`{key}` = `{value}`)"
                else:
                    filter_string += f"(`{key}` = '{value}')"
            else:
                filter_string += f"(`{key}` = {value})"
        for key, value in filter_greater.items():
            if filter_string != " WHERE (":
                filter_string += " and "
            if not isinstance(value, (int, float, bool)):
                if value in list_all:
                    filter_string += f"(`{key}` > `{value}`)"
                else:
                    filter_string += f"(`{key}` > '{value}')"
            else:
                filter_string += f"(`{key}` > {value})"
        for key, value in filter_less.items():
            if filter_string != " WHERE (":
                filter_string += " and "
            if not isinstance(value, (int, float, bool)):
                if value in list_all:
                    filter_string += f"(`{key}` < `{value}`)"
                else:
                    filter_string += f"(`{key}` < '{value}')"
            else:
                filter_string += f"(`{key}` < {value})"
        for key, value in filter_greater_or_equal.items():
            if filter_string != " WHERE (":
                filter_string += " and "
            if not isinstance(value, (int, float, bool)):
                if value in list_all:
                    filter_string += f"(`{key}` >= `{value}`)"
                else:
                    filter_string += f"(`{key}` >= '{value}')"
            else:
                filter_string += f"(`{key}` >= {value})"
        for key, value in filter_less_or_equal.items():
            if filter_string != " WHERE (":
                filter_string += " and "
            if not isinstance(value, (int, float, bool)):
                if value in list_all:
                    filter_string += f"(`{key}` <= `{value}`)"
                else:
                    filter_string += f"(`{key}` <= '{value}')"
            else:
                filter_string += f"(`{key}` <= {value})"
        for key, value in filter_not_equal.items():
            if filter_string != " WHERE (":
                filter_string += " and "
            if not isinstance(value, (int, float, bool)):
                if value in list_all:
                    filter_string += f"(`{key}` <> `{value}`)"
                else:
                    filter_string += f"(`{key}` <> '{value}')"
            else:
                filter_string += f"(`{key}` <> {value})"
        for key, value in filter_like.items():
            if filter_string != " WHERE (":
                filter_string += " and "
            filter_string += f"(`{key}` LIKE '{value}')"
        for key, value in filter_rlike.items():
            if filter_string != " WHERE (":
                filter_string += " and "
            filter_string += f"(`{key}` RLIKE '{value}')"
        for key, value in filter_in.items():
            str_values = [str(x) for x in value]
            if filter_string != " WHERE (":
                filter_string += " and "
            if not isinstance(value[0], (int, float, bool)):
                filter_string += f"(`{key}` IN ('"
                filter_string += "', '".join(str_values)
                filter_string += "'))"
            else:
                filter_string += f"(`{key}` IN ("
                filter_string += ", ".join(str_values)
                filter_string += "))"
        for key, value in filter_between.items():
            if filter_string != " WHERE (":
                filter_string += " and "
            if not isinstance(value[0], (int, float, bool)):
                if value[0] in list_all:
                    filter_string += f"(`{key}` BETWEEN `{value[0]}` and "
                else:
                    filter_string += f"(`{key}` BETWEEN '{value[0]}' and "
            else:
                filter_string += f"(`{key}` BETWEEN {value[0]} and "
            if not isinstance(value[1], (int, float, bool)):
                if value[1] in list_all:
                    filter_string += f"`{value[1]}`)"
                else:
                    filter_string += f"'{value[1]}')"
            else:
                filter_string += f"{value[1]})"
        for key in filter_null:
            if filter_string != " WHERE (":
                filter_string += " and "
            filter_string += f"(`{key}` IS NULL)"
        for key in filter_not_null:
            if filter_string != " WHERE (":
                filter_string += " and "
            filter_string += f"(`{key}` IS NOT NULL)"
        filter_string += ")"
    else:
        filter_string = ""

    if limit is None:
        limit_string = ""
    else:
        limit_string = f" LIMIT {limit}"

    if comment is None:
        comment_string = ""
    else:
        comment_string = f" /* {comment} */"

    version_comment = f"/* AtScale AI-Link Library Version: {config.Config().version} */ "

    if use_aggs:
        use_aggs_comment = ""
    else:
        use_aggs_comment = " /* use_aggs(false) */"
    if gen_aggs:
        gen_aggs_comment = ""
    else:
        gen_aggs_comment = " /* generate_aggs(false) */"

    query = (
        f"{version_comment}SELECT{use_aggs_comment}{gen_aggs_comment}{all_columns_string}"
        f" FROM `{data_model.project.published_project_name}`.`{data_model.name}`"
        f"{filter_string}{order_string}{limit_string}{comment_string}"
    )
    return query


def _generate_db_query(
    data_model,
    atscale_query: str,
    use_aggs: bool = True,
    gen_aggs: bool = True,
    timeout: int = 10,
) -> str:
    """Submits an AtScale query to the query planner and grabs the outbound query to the database which is returned.

    Args:
        data_model (DataModel): an atscale DataModel object
        atscale_query (str): an SQL query that references the atscale semantic layer (rather than the backing data warehouse)
        use_aggs (bool, optional): Whether to allow the query to use aggs. Defaults to True.
        gen_aggs (bool, optional): Whether to allow the query to generate aggs. Defaults to True.
        timeout (int, optional): The number of minutes to wait for a response before timing out. Defaults to 10.

    Returns:
        str: the query that atscale would send to the backing data warehouse given the atscale_query sent to atscale
    """

    inspection = getfullargspec(_generate_db_query)
    validate_by_type_hints(inspection=inspection, func_params=locals())

    # we'll keep track of any comment so it can be added to the outbound query that is returned
    comment_match = re.findall(r"/\*.+?\*/", atscale_query)

    # we use a time stamp around the time we submit the query, to then query atscale to
    # try and get back the query it actually submitted to the backing data warehouse
    now = datetime.datetime.utcnow()  # current date and time
    now = now - datetime.timedelta(minutes=5)

    date_time = now.strftime("%Y-%m-%dT%H:%M:%S.000Z")

    # Post the rest query through atscale. No return value, we have to dig through logs to see what it was later
    atconn = data_model.project._atconn
    published_project_name = data_model.project.published_project_name

    atconn._post_atscale_query(
        query=atscale_query,
        project_name=published_project_name,
        use_aggs=use_aggs,
        gen_aggs=gen_aggs,
        fake_results=True,
        timeout=timeout,
    )

    url = endpoints._endpoint_query_view(
        atconn=atconn, suffix=f"&querySource=user&queryStarted=5m&queryDateTimeStart={date_time}"
    )

    response = atconn._submit_request(request_type=RequestType.GET, url=url)
    json_data = json.loads(response.content)["response"]
    db_query = ""

    for query_info in json_data["data"]:
        if db_query != "":
            break
        if query_info["query_text"] == atscale_query:
            if query_info.get("succeeded", False) == False:
                raise atscale_errors.AtScaleServerError(query_info["failure_message"])
            for event in query_info["timeline_events"]:
                if event["type"] == "SubqueriesWall":
                    # check if it was truncated
                    if event["children"][0]["query_text_truncated"]:
                        url = endpoints._endpoint_design_private_org(
                            atconn=atconn,
                            suffix=f'/fullquerytext/queryId/{query_info["query_id"]}'
                            f'?subquery={event["children"][0]["query_id"]}',
                        )
                        response = atconn._submit_request(request_type=RequestType.GET, url=url)
                        db_query = response.text
                    else:
                        db_query = event["children"][0]["query_text"]
                    if comment_match:  # add any comment to the outbound query
                        for comment in comment_match:
                            db_query = comment + " " + db_query
                    break
    return db_query
