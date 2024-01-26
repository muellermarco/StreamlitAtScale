"""Module for handling SQL and AtScale Date and Time objects"""

from atscale.db.sql_connection import SQLConnection
from atscale.base.enums import TimeLevels


def determine_time_levels(
    dbconn: SQLConnection,
    table_name: str,
    column: str,
    start_level: TimeLevels = TimeLevels.Year,
    end_level: TimeLevels = TimeLevels.Second,
):
    """Determines the time levels applicable for a given database table column. Can specify the starting time level to create.

    Args:
        dbconn (SQLConnection): the connection to query the table with
        table_name (str): the table to query
        column (str): the specific column to analyze
        start_level (TimeLevels, optional): The top level of the hierarchy to start with. Defaults to TimeLevels.Year.
        end_level (TimeLevels, optional): The lowest level of the hierarchy to end with. Defaults to TimeLevels.Second.

    Returns:
        List[TimeLevels]: the time levels that could be created from the given column
    """
    top = None
    bottom = None
    num = len(TimeLevels) - 1

    # this should only iterate over the startlevel on down
    levels_to_iterate = [
        level
        for level in TimeLevels
        if level.index >= start_level.index and level.index <= end_level.index
    ]
    last_distinct = None
    for level in levels_to_iterate:  # this starts at years and works down
        expression = level.get_sql_expression(column, dbconn.platform_type)
        db_table_loc = dbconn._create_table_path(table_name)
        query = f"SELECT count(distinct({expression})) FROM {db_table_loc}"
        df = dbconn.submit_query(query)
        # Grab the one value from the df which is the count of distinct values at this aggregation level.
        distinct = df.iat[0, 0]
        if distinct > 1:
            if not top:  # if top is None, meaning we haven't found it yet
                # Then this is the first level where there is more than one unique value, which means the level
                # above this one is the top. The top will have only one unique value, and aggregate everything.
                # if we're at top, we can't go any higher so will just set that as top
                if level == levels_to_iterate[0]:
                    top = levels_to_iterate[0]
                else:
                    # otherwise, top is the level above the current level in this loop
                    top = [l for l in TimeLevels if l.index == (level.index - 1)][0]
                if (
                    top.index == num
                ):  # if top is the penultimate item in the enum (currently minutes), then add the last one (currently seconds), which should be level in this loop (right after setting top in the last one)
                    bottom = level
                    break
            elif distinct == last_distinct:
                # If two consecutive values have the same distinct value (using date_trunc), then the last value we looked at was the bottom
                bottom = [l for l in TimeLevels if l.index == level.index - 1][0]
                break
        last_distinct = distinct
    # the above does not always find the bottom
    if not bottom:
        bottom = end_level

    # We should now have the top and bottom levels.
    # There should be  better way of doing this, but trying to go fast and being a bit sloppy
    levels = [level for level in TimeLevels if top.index <= level.index <= bottom.index]
    return levels
