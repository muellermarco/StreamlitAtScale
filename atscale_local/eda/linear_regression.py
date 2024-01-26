from atscale.utils.eda_utils import (
    _eda_check,
    _generate_base_table_name,
    _construct_and_submit_base_table_query,
    _execute_with_name_collision_handling,
)
from atscale.db.connections.snowflake import Snowflake
from atscale.data_model.data_model import DataModel
from atscale.errors import atscale_errors
from atscale.utils import validation_utils
from inspect import getfullargspec
from typing import List, Tuple, Dict
from atscale.base.enums import PlatformType, PandasTableExistsActionType
from inspect import getfullargspec
from atscale.utils.validation_utils import validate_by_type_hints
import logging


logger = logging.getLogger(__name__)


def linear_regression(
    dbconn: Snowflake,
    data_model: DataModel,
    predictors: List[str],
    prediction_target: str,
    granularity_levels: List[str],
    if_exists: PandasTableExistsActionType = PandasTableExistsActionType.FAIL,
    write_database: str = None,
    write_schema: str = None,
) -> Dict:
    """Performs linear regression on the predictors and prediction_target specified. Will make a series of
    temp tables in the source db to facilitate this calc. This is only supported for Snowflake at this time.

    Args:
        dbconn (Snowflake): The database connection that linear_regression will interact with
        data_model (DataModel): The data model corresponding to the features provided
        predictors (List[str]): The query names of the numeric features corresponding to the regression inputs
        prediction_target (str): The query name of the numeric feature that will be predicted via linear_regression
        granularity_levels (List[str]): The query names of the categorical features corresponding to the level of
                                        granularity desired in numeric_features
        if_exists (PandasTableExistsActionType, optional): The default action the function takes when creating
                                                           process tables that already exist. Does not accept APPEND. Defaults to FAIL.
        write_database (str): The database that linear regression will write tables to. Defaults to the database associated with the
                              given dbconn.
        write_schema (str): The schema that linear regression will write tables to. Defaults to the schema associated with the
                              given dbconn.

    Raises:
        UserError:User can't select APPEND as an ActionType.
        EDAException: User must pass at least one feature to predictors, prediction_target

    Returns:
        Dict: A Dict containing the regression coefficients
    """
    if dbconn is not None:
        if dbconn.platform_type != PlatformType.SNOWFLAKE:
            raise atscale_errors.UnsupportedOperationException(
                f"This function is only supported for Snowflake at this time."
            )

    inspection = getfullargspec(linear_regression)
    validate_by_type_hints(inspection=inspection, func_params=locals())

    if not write_database:
        write_database = dbconn._database

    if not write_schema:
        write_schema = dbconn._schema

    _eda_check(
        data_model=data_model,
        numeric_features=predictors + [prediction_target],
        granularity_levels=granularity_levels,
        if_exists=if_exists,
    )

    if len(predictors) < 1:
        raise atscale_errors.EDAException(
            "Make sure at least one valid feature is passed via predictors"
        )

    base_table_name = _generate_base_table_name()
    three_part_name = f"{write_database}.{write_schema}.{base_table_name}"

    _construct_and_submit_base_table_query(
        dbconn=dbconn,
        data_model=data_model,
        base_table_name=three_part_name,
        numeric_features=predictors + [prediction_target],
        granularity_levels=granularity_levels,
        if_exists=if_exists,
    )

    # Generate queries to run linear regression, display results, and drop all generated tables
    # Query statements split to allow for linear dependence check
    (
        query_statements_a,
        query_statements_b,
        drop_statements_a,
        drop_statements_b,
        display_statement,
    ) = _get_linear_regression_sql(
        three_part_name=three_part_name,
        predictors=predictors,
        prediction_target=prediction_target,
        dbconn=dbconn,
    )

    _execute_with_name_collision_handling(
        dbconn=dbconn,
        query_list=query_statements_a,
        drop_list=drop_statements_a,
        base_table_name=three_part_name,
        if_exists=if_exists,
    )

    # Check for linear dependency among columns
    has_linearly_dependent_columns = (
        dbconn.submit_query(f"SELECT lin_dep_count FROM {three_part_name}_dependency_check; ")[
            "lin_dep_count"
        ][0]
        > 0
    )
    if has_linearly_dependent_columns:
        raise atscale_errors.EDAException(
            f"Make sure features passed to predictors are not linearly dependent"
        )

    _execute_with_name_collision_handling(
        dbconn=dbconn,
        query_list=query_statements_b,
        drop_list=drop_statements_b,
        base_table_name=three_part_name,
        if_exists=if_exists,
    )

    # Get results
    coeff_dataframe = dbconn.submit_query(display_statement)

    # Drop everything written to DB
    dbconn.execute_statements(statement_list=drop_statements_a)
    dbconn.execute_statements(statement_list=drop_statements_b)

    # Delete base table
    dbconn.submit_query(f"DROP TABLE {three_part_name}; ")

    # Return dictionary containing coefficients
    coeff_dict = {}
    for i in coeff_dataframe.index:
        coeff_dict[coeff_dataframe["coefficient"][i]] = coeff_dataframe["value"][i]

    return coeff_dict


def _get_linear_regression_sql(
    three_part_name: str,
    predictors: List[str],
    prediction_target: str,
    dbconn: Snowflake,
) -> Tuple:
    """Generates SQL queries that perform linear regression on the data contained in the specified table.
       This implementation solves for the regression coefficients and constant via a least-squares approach,
       which itself involves QR decomposition to render the matrix to be inverted as a product of two easily
       invertible matrices (i.e., an orthogonal matrix and an upper triangular matrix).

    Args:
        three_part_name (str): The table containing the data to be analyzed
        predictors (List[str]): The query names of the numeric features corresponding to the regression inputs
        prediction_target (str): The query name of the numeric feature that will be predicted via linear_regression
        dbconn (Snowflake): The database connection that linear_regression will interact with

    Returns:
        Tuple[List[str], List[str], str]: A list containing: 1.) A list of queries to initialize and
                                          run linear regression, 2.) A list of queries to
                                          delete all tables constructed by the first list,
                                          and 3.) a query to display the regression coefficients
    """
    predictor_plus_constant_dim = len(predictors) + 1

    # Initialize lists/dict that will eventually contain all necessary queries
    query_statements_a = []
    query_statements_b = []
    drop_statements_a = [
        f"DROP TABLE IF EXISTS {three_part_name}_dependency_check; ",
        f"DROP TABLE IF EXISTS {three_part_name}_predictor_transpose_times_predictor; ",
        f"DROP TABLE IF EXISTS {three_part_name}_predictor_observation_matrix; ",
    ]
    drop_statements_b = [
        f"DROP TABLE IF EXISTS {three_part_name}_coeff; ",
        f"DROP TABLE IF EXISTS {three_part_name}_intermed; ",
        f"DROP TABLE IF EXISTS {three_part_name}_q_transpose; ",
        f"DROP TABLE IF EXISTS {three_part_name}_r_inverse; ",
        f"DROP TABLE IF EXISTS {three_part_name}_predictor_transpose_times_observation; ",
        f"DROP TABLE IF EXISTS {three_part_name}_v; ",
        f"DROP TABLE IF EXISTS {three_part_name}_r; ",
        f"DROP TABLE IF EXISTS {three_part_name}_q; ",
    ]
    display_statement = ""

    predictors = [dbconn._column_quote() + x + dbconn._column_quote() for x in predictors]
    prediction_target = dbconn._column_quote() + prediction_target + dbconn._column_quote()

    # Construct a table representing the predictor/target data together with a column to accomodate
    # the constant term
    predictor_observation_matrix_string = (
        f"CREATE TABLE {three_part_name}_predictor_observation_matrix AS SELECT "
    )
    for col in predictors:
        predictor_observation_matrix_string += f"{three_part_name}.{col} AS {col}, "
    predictor_observation_matrix_string += (
        "1.0 AS constant, "
        + f"{three_part_name}.{prediction_target} AS {prediction_target} "
        + f"FROM {three_part_name}; "
    )
    query_statements_a.append(predictor_observation_matrix_string)

    # Construct a table representing the predictor matrix transpose times the predictor matrix;
    predictor_transpose_times_predictor_string = (
        f"CREATE TABLE {three_part_name}_predictor_transpose_times_predictor AS "
    )
    col_list = predictors + ["constant"]
    for i in range(1, (predictor_plus_constant_dim**2) + 1):
        r = (i - 1) // predictor_plus_constant_dim + 1
        c = i - (r - 1) * predictor_plus_constant_dim
        predictor_transpose_times_predictor_string += (
            f"SELECT {i} AS id, {r} AS r, {c} AS c, "
            + f"SUM({col_list[r - 1]} * {col_list[c - 1]}) AS vals FROM {three_part_name}_predictor_observation_matrix "
            + f"UNION ALL "
        )
    predictor_transpose_times_predictor_string = (
        predictor_transpose_times_predictor_string[:-11] + "; "
    )
    query_statements_a.append(predictor_transpose_times_predictor_string)

    # Check for linearly dependent tables
    dependency_check_string = f"CREATE TABLE {three_part_name}_dependency_check AS (SELECT COUNT(sd) AS lin_dep_count FROM ("
    for i in range(1, predictor_plus_constant_dim + 1):
        for j in range(i + 1, predictor_plus_constant_dim + 1):
            dependency_check_string += (
                f"SELECT STDDEV(vals_{i} / vals_{j}) AS sd FROM ("
                + f"(SELECT r AS r_{i}, vals AS vals_{i} FROM {three_part_name}_predictor_transpose_times_predictor WHERE c = {i}) AS cl_{i} JOIN "
                + f"(SELECT r AS r_{j}, vals AS vals_{j} FROM {three_part_name}_predictor_transpose_times_predictor WHERE c = {j}) AS cl_{j} ON "
                + f"cl_{i}.r_{i} = cl_{j}.r_{j}) UNION ALL "
            )
    dependency_check_string = dependency_check_string[:-11] + f") WHERE sd = 0); "
    query_statements_a.append(dependency_check_string)

    # Inversion of matrix constructed above
    ## QR Decomposition of this matrix; makes for easier inversion
    query_statements_b.append(
        f"CREATE TABLE {three_part_name}_q AS (SELECT {three_part_name}_predictor_transpose_times_predictor.id, "
        + f"{three_part_name}_predictor_transpose_times_predictor.r, "
        + f"{three_part_name}_predictor_transpose_times_predictor.c, "
        + f"({three_part_name}_predictor_transpose_times_predictor.vals * 0.0) AS vals "
        + f"FROM {three_part_name}_predictor_transpose_times_predictor); "
    )
    query_statements_b.append(
        f"CREATE TABLE {three_part_name}_r AS (SELECT {three_part_name}_predictor_transpose_times_predictor.id, "
        + f"{three_part_name}_predictor_transpose_times_predictor.r, "
        + f"{three_part_name}_predictor_transpose_times_predictor.c, "
        + f"({three_part_name}_predictor_transpose_times_predictor.vals * 0.0) AS vals "
        + f"FROM {three_part_name}_predictor_transpose_times_predictor); "
    )
    query_statements_b.append(
        f"CREATE TABLE {three_part_name}_v AS (SELECT * FROM {three_part_name}_predictor_transpose_times_predictor); "
    )

    ### Update the i-th column of Q to be the normalized i-th column of V. Set R[i, i] (the i-th value along R's diagonal)
    ### to be the norm of the i-th column of V.
    for i in range(1, predictor_plus_constant_dim + 1):
        query_statements_b.append(
            f"UPDATE {three_part_name}_q SET vals = q{i}.vals FROM "
            + f"(SELECT r, c, vals / (SELECT SQRT(SUM(POWER(vals, 2))) FROM {three_part_name}_v WHERE {three_part_name}_v.c = {i}) AS vals FROM "
            + f"{three_part_name}_v WHERE {three_part_name}_v.c = {i}) AS q{i} WHERE {three_part_name}_q.c = {i} AND q{i}.c = {i} AND {three_part_name}_q.r = q{i}.r; "
        )
        query_statements_b.append(
            f"UPDATE {three_part_name}_r SET vals = (SELECT SQRT(SUM(POWER(vals, 2))) FROM {three_part_name}_v "
            + f"WHERE {three_part_name}_v.c = {i}) WHERE {three_part_name}_r.r = {i} AND {three_part_name}_r.c = {i}; "
        )

        ### Calculate the dot product of the i-th column of Q and the j-th column of V, set R[i, j] to this dot product,
        ### then subtract this dot product times the i-th column of Q from the j-th column of V
        for j in range(i + 1, predictor_plus_constant_dim + 1):
            query_statements_b.append(
                f"UPDATE {three_part_name}_r SET vals = (SELECT SUM(q{i}.vals * v{j}.vals) FROM "
                + f"(SELECT r, vals FROM {three_part_name}_q WHERE c = {i}) AS q{i} "
                + f"JOIN (SELECT r, vals FROM {three_part_name}_v WHERE c = {j}) AS v{j} ON q{i}.r = v{j}.r) "
                + f"WHERE {three_part_name}_r.r = {i} AND {three_part_name}_r.c = {j}; "
            )

            query_statements_b.append(
                f"UPDATE {three_part_name}_v SET vals = v_minus.vals FROM "
                + f"(SELECT v{j}.r, v{j}.c, (v{j}.vals - dot_times_q{i}.vals) AS vals FROM "
                + f"(SELECT r, c, vals FROM {three_part_name}_v WHERE c = {j}) AS v{j} JOIN "
                + f"(SELECT {three_part_name}_q.r, (SELECT SUM(q{i}.vals * v{j}.vals) AS vals FROM "
                + f"(SELECT r, vals FROM {three_part_name}_q WHERE c = {i}) AS q{i} JOIN "
                + f"(SELECT r, vals FROM {three_part_name}_v WHERE c = {j}) AS v{j} ON q{i}.r = v{j}.r) "
                + f"* {three_part_name}_q.vals AS vals FROM {three_part_name}_q WHERE {three_part_name}_q.c = {i}) AS "
                + f"dot_times_q{i} ON v{j}.r = dot_times_q{i}.r) AS v_minus WHERE "
                + f"{three_part_name}_v.c = {j} AND {three_part_name}_v.r = v_minus.r; "
            )

    # Construct a table representing the predictor matrix transpose times the observation vector
    predictor_transpose_times_observation_string = (
        f"CREATE TABLE {three_part_name}_predictor_transpose_times_observation AS "
    )
    for i in range(1, predictor_plus_constant_dim):
        predictor_transpose_times_observation_string += (
            f"SELECT {i} AS id, SUM({predictors[i - 1]} * {prediction_target}) "
            + f"AS vals FROM {three_part_name}_predictor_observation_matrix UNION ALL "
        )
    predictor_transpose_times_observation_string += (
        f"SELECT {predictor_plus_constant_dim} AS id, SUM(constant * {prediction_target}) "
        + f"AS vals FROM {three_part_name}_predictor_observation_matrix; "
    )
    query_statements_b.append(predictor_transpose_times_observation_string)

    # Invert r matrix from QR decomposition
    ## Initialize r's inverse as an identity matrix
    r_inverse_init_string = f"CREATE TABLE {three_part_name}_r_inverse AS "
    for i in range(1, (predictor_plus_constant_dim**2) + 1):
        r = (i - 1) // predictor_plus_constant_dim + 1
        c = i - (r - 1) * predictor_plus_constant_dim
        if r == c:
            # wrong data type (same below)
            r_inverse_init_string += (
                f"SELECT {i} AS id, {r} AS r, {c} AS c, 1.0{dbconn._lin_reg_str()}"
            )
        else:
            r_inverse_init_string += (
                f"SELECT {i} AS id, {r} AS r, {c} AS c, 0.0{dbconn._lin_reg_str()}"
            )
    r_inverse_init_string = r_inverse_init_string[:-11] + "; "
    query_statements_b.append(r_inverse_init_string)

    ## Matrix inversion
    for i in range(predictor_plus_constant_dim, 0, -1):
        r_inverse_string = (
            f"UPDATE {three_part_name}_r_inverse SET vals = row_update.vals FROM "
            + f"(SELECT row_divided.id, row_divided.vals FROM "
            + f"(SELECT {three_part_name}_r_inverse.id AS id, {three_part_name}_r_inverse.r AS r, "
            + f"({three_part_name}_r_inverse.vals / (SELECT vals FROM {three_part_name}_r WHERE {three_part_name}_r.r = {i} AND {three_part_name}_r.c = {i})) AS vals "
            + f"FROM {three_part_name}_r_inverse) AS row_divided WHERE row_divided.r = {i}) AS row_update WHERE {three_part_name}_r_inverse.id = row_update.id; "
        )
        query_statements_b.append(r_inverse_string)

        if i > 1:
            r_inverse_string = (
                f"UPDATE {three_part_name}_r_inverse SET vals = row_update.vals FROM ("
            )
            for j in range(1, i):
                r_inverse_string += (
                    "SELECT id, (vals - sub_vals) AS vals FROM ("
                    + f"SELECT id, {three_part_name}_r_inverse.vals AS vals, sub_matrix.vals AS sub_vals "
                    + f"FROM {three_part_name}_r_inverse JOIN (SELECT r, c, ((SELECT vals "
                    + f"FROM {three_part_name}_r WHERE r = {j} AND c = {i}) * vals) AS vals FROM {three_part_name}_r_inverse WHERE r = {i}) AS sub_matrix "
                    + f"ON {three_part_name}_r_inverse.c = sub_matrix.c WHERE {three_part_name}_r_inverse.r = {j}) AS inv UNION ALL "
                )
            r_inverse_string = (
                r_inverse_string[:-11]
                + f") AS row_update WHERE {three_part_name}_r_inverse.id = row_update.id; "
            )
            query_statements_b.append(r_inverse_string)

    # Transpose q
    q_transpose_string = f"CREATE TABLE {three_part_name}_q_transpose AS "
    for i in range(1, (predictor_plus_constant_dim**2) + 1):
        r = (i - 1) // predictor_plus_constant_dim + 1
        c = i - (r - 1) * predictor_plus_constant_dim
        q_transpose_string += (
            f"SELECT {i} AS id, {r} AS r, {c} AS c, "
            + f"(SELECT vals FROM {three_part_name}_q WHERE r = {c} AND c = {r}) AS vals UNION ALL "
        )
    q_transpose_string = q_transpose_string[:-11] + "; "
    query_statements_b.append(q_transpose_string)

    # Multiply q^T by predictor_transpose_times_observation
    intermed_string = f"CREATE TABLE {three_part_name}_intermed AS "
    for i in range(1, predictor_plus_constant_dim + 1):
        intermed_string += (
            f"SELECT {i} AS id, SUM(col_prods.vals) AS vals FROM "
            + f"(SELECT id, r, c, (vector_vals * matrix_vals) AS vals FROM "
            + f"(SELECT {three_part_name}_q_transpose.id AS id, {three_part_name}_q_transpose.r AS r, {three_part_name}_q_transpose.c AS c, "
            + f"{three_part_name}_predictor_transpose_times_observation.vals AS vector_vals, {three_part_name}_q_transpose.vals AS matrix_vals "
            + f"FROM {three_part_name}_q_transpose JOIN {three_part_name}_predictor_transpose_times_observation ON "
            + f"{three_part_name}_q_transpose.c = {three_part_name}_predictor_transpose_times_observation.id) AS vec ORDER BY id) AS col_prods WHERE col_prods.r = {i} UNION ALL "
        )
    intermed_string = intermed_string[:-11] + "; "
    query_statements_b.append(intermed_string)

    # Multiply result of above by r inverse
    coeff_string = f"CREATE TABLE {three_part_name}_coeff AS "
    for i in range(1, predictor_plus_constant_dim + 1):
        coeff_string += (
            f"SELECT {i} AS id, SUM(col_prods.vals) AS vals FROM "
            + f"(SELECT id, r, c, (vector_vals * matrix_vals) AS vals FROM "
            + f"(SELECT {three_part_name}_r_inverse.id AS id, {three_part_name}_r_inverse.r AS r, {three_part_name}_r_inverse.c AS c, "
            + f"{three_part_name}_intermed.vals AS vector_vals, {three_part_name}_r_inverse.vals AS matrix_vals "
            + f"FROM {three_part_name}_r_inverse JOIN {three_part_name}_intermed ON "
            + f"{three_part_name}_r_inverse.c = {three_part_name}_intermed.id) AS vec ORDER BY id) AS col_prods WHERE col_prods.r = {i} UNION ALL "
        )
    coeff_string = coeff_string[:-11] + "; "
    query_statements_b.append(coeff_string)

    # Display statement
    for i in range(predictor_plus_constant_dim - 1):
        display_statement += (
            f"SELECT '{predictors[i]}' AS coefficient, "
            + f"(SELECT vals FROM {three_part_name}_coeff WHERE id = {i + 1}) AS value UNION ALL "
        )
    display_statement += (
        f"SELECT '<constant>' AS coefficient, "
        + f"(SELECT vals FROM {three_part_name}_coeff WHERE id = {predictor_plus_constant_dim}) AS value; "
    )

    return (
        query_statements_a,
        query_statements_b,
        drop_statements_a,
        drop_statements_b,
        display_statement,
    )
