from html import unescape
from inspect import getfullargspec
from atscale.utils.validation_utils import validate_by_type_hints
from aenum import Enum, NoAlias
from atscale.errors import atscale_errors


class DMVColumnBaseClass(Enum):
    """The base class for our various dmv query enums. Defines consistent functionality."""

    def requires_translation(self):
        if self in self.internal_func_dict():
            return True
        return False

    def to_regex(self):
        return f"<{self.value}>(.*?)</{self.value}>"

    def translate(
        self,
        val,
    ):
        """Translates the parsed output from a DMV response into a user interpretable format. If a field has a specific
        translation, Hierarcy.dimension: [dimension_name] -> dimension_name for example, it must be declared in the
        respective class's internal_func_dict() method. If no specific function is declared there, the value will be
        converted from html string encoding changes that may have occured since its original input. For example,
        &quot gets converted to " and \\' gets converted to \'"""
        func_dict = self.internal_func_dict()
        if self in func_dict:
            func = func_dict[self]
            return func(val)
        else:
            return (
                unescape(val).encode("utf-8").decode("unicode_escape")
            )  # unescape &quote; encode so we can decode \\


class Dimension(DMVColumnBaseClass):
    """An enum to represent the metadata of a dimension object for use in dmv queries.
    description: the description field
    name: the name field
    type: the type field
    visible: the visible field
    """

    description = "DESCRIPTION"
    name = "DIMENSION_NAME"
    visible = "DIMENSION_IS_VISIBLE"
    type = "DIMENSION_TYPE"

    @property
    def schema(self):
        return "$system.MDSCHEMA_DIMENSIONS"

    @property
    def where(self):
        return " WHERE [DIMENSION_NAME] &lt;&gt; 'Measures' AND [CUBE_NAME] = @CubeName"

    def internal_func_dict(self):
        def hierarchy_type_func(type_number: str):
            inspection = getfullargspec(hierarchy_type_func)
            validate_by_type_hints(inspection=inspection, func_params=locals())

            if type_number == "1":
                return "Time"
            elif type_number == "3":
                return "Standard"
            else:
                return None

        return {self.__class__.type: (lambda x: hierarchy_type_func(x))}


class Hierarchy(DMVColumnBaseClass):
    """An enum to represent the metadata of a hierarchy object for use in dmv queries.
    description: the description field
    name: the name field
    caption: the caption field
    visible: the visible field
    type: the type field
    folder: the folder field
    dimension: the dimension field
    secondary_attribute: the secondary_attribute field
    """

    description = "DESCRIPTION"
    name = "HIERARCHY_NAME"
    caption = "HIERARCHY_CAPTION"
    visible = "HIERARCHY_IS_VISIBLE"
    type = "DIMENSION_TYPE"
    folder = "HIERARCHY_DISPLAY_FOLDER"
    dimension = "DIMENSION_UNIQUE_NAME"
    secondary_attribute = "HIERARCHY_ORIGIN"

    @property
    def schema(self):
        return "$system.MDSCHEMA_HIERARCHIES"

    @property
    def where(self):
        return " WHERE [HIERARCHY_NAME] &lt;&gt; 'Measures' AND [CUBE_NAME] = @CubeName"

    def internal_func_dict(self):
        def hierarchy_type_func(type_number: str):
            inspection = getfullargspec(hierarchy_type_func)
            validate_by_type_hints(inspection=inspection, func_params=locals())

            if type_number == "1":
                return "Time"
            elif type_number == "3":
                return "Standard"
            else:
                return None

        return {
            self.__class__.type: (lambda x: hierarchy_type_func(x)),
            self.__class__.dimension: (lambda x: x[1:-1]),
            self.__class__.secondary_attribute: (lambda x: False if x == "1" else True),
        }


class Measure(DMVColumnBaseClass):
    """An enum to represent the metadata of a measure object for use in dmv queries.
    name: the name field
    description: the description field
    caption: the caption field
    visible: the visible field
    type: the type field
    folder: the folder field
    expression: the expression field
    """

    name = "MEASURE_NAME"
    description = "DESCRIPTION"
    caption = "MEASURE_CAPTION"
    visible = "MEASURE_IS_VISIBLE"
    type = "MEASURE_AGGREGATOR"
    folder = "MEASURE_DISPLAY_FOLDER"
    expression = "EXPRESSION"
    data_type = "DATA_TYPE"

    @property
    def schema(self):
        return "$system.MDSCHEMA_MEASURES"

    @property
    def where(self):
        return " WHERE [CUBE_NAME] = @CubeName"  # need to specify only fields for our cube for all query types

    def internal_func_dict(self):
        return {
            self.__class__.type: (
                lambda x: "Calculated" if x == "9" else Aggs.from_dmv_number(int(x)).visual_rep
            ),
            self.__class__.data_type: (lambda x: DBDataType(int(x)).name),
        }


class Level(DMVColumnBaseClass):
    """An enum to represent the metadata of a level object for use in dmv queries.
    description: the description field
    name: the name field
    caption: the caption field
    visible: the visible field
    type: the type field
    dimension: the dimension field
    hierarchy: the hierarchy field
    level_number: the level_number field
    """

    _settings_ = NoAlias  # necessary for different fields with the same value but different func

    description = "DESCRIPTION"
    name = "LEVEL_NAME"
    caption = "LEVEL_CAPTION"
    visible = "LEVEL_IS_VISIBLE"
    type = "LEVEL_TYPE"
    dimension = "HIERARCHY_UNIQUE_NAME"
    hierarchy = "HIERARCHY_UNIQUE_NAME"
    level_number = "LEVEL_NUMBER"
    data_type = "LEVEL_DBTYPE"
    secondary_attribute = "IS_PRIMARY"

    @property
    def schema(self):
        return "$system.mdschema_levels"

    @property
    def where(self):
        return (
            " WHERE [CUBE_NAME] = @CubeName and [LEVEL_NAME] &lt;&gt; '(All)' and [DIMENSION_UNIQUE_NAME] "
            "&lt;&gt; '[Measures]'"
        )

    def internal_func_dict(self):
        return {
            self.__class__.level_number: (lambda x: int(x)),
            self.__class__.hierarchy: (lambda x: x.split("].[")[1][:-1]),
            self.__class__.dimension: (lambda x: x.split("].[")[0][1:]),
            self.__class__.type: (lambda x: TimeSteps(int(x)).name),
            self.__class__.data_type: (lambda x: DBDataType(int(x)).name),
            self.__class__.secondary_attribute: (lambda x: x == "false"),
        }


class DBDataType(Enum):
    def __str__(self):
        return self.name

    def __repr__(self):
        return f"{self.__class__.__name__}.{self.name}"

    EMPTY = 0  # Indicates that no value was specified.
    INT1 = 16  # Indicates a one-byte signed integer.
    INT2 = 2  # Indicates a two-byte signed integer.
    INT4 = 3  # Indicates a four-byte signed integer.
    INT8 = 20  # Indicates an eight-byte signed integer.
    INT_UNSIGNED1 = 17  # Indicates a one-byte unsigned integer.
    INT_UNSIGNED2 = 18  # Indicates a two-byte unsigned integer.
    INT_UNSIGNED4 = 19  # Indicates a four-byte unsigned integer.
    INT_UNSIGNED8 = 21  # Indicates an eight-byte unsigned integer.
    FLOAT32 = 4  # Indicates a single-precision floating-point value.
    FLOAT64 = 5  # Indicates a double-precision floating-point value.
    CURRENCY = 6  # Indicates a currency value. Currency is a fixed-point number with four digits to the right of the decimal point and is stored in an eight-byte signed integer scaled by 10,000.
    DATE_DOUBLE = 7  # Indicates a date value. Date values are stored as Double, the whole part of which is the number of days since December 30, 1899, and the fractional part of which is the fraction of a day.
    BSTR = 8  # A pointer to a BSTR, which is a null-terminated character string in which the string length is stored with the string.
    IDISPATCH = 9  # Indicates a pointer to an IDispatch interface on an OLE object.
    ERROR_CODE = 10  # Indicates a 32-bit error code.
    BOOL = 11  # Indicates a Boolean value.
    VARIANT = 12  # Indicates an Automation variant.
    IUNKNOWN = 13  # Indicates a pointer to an IUnknown interface on an OLE object.
    DECIMAL = 14  # Indicates an exact numeric value with a fixed precision and scale. The scale is between 0 and 28.
    GUID = 72  # Indicates a GUID.
    BYTES = 128  # Indicates a binary value.
    STRING = 129  # Indicates a string value.
    WSTR = 130  # Indicates a null-terminated Unicode character string.
    NUMERIC = 131  # Indicates an exact numeric value with a fixed precision and scale. The scale is between 0 and 38.
    UDT = 132  # Indicates a user-defined variable.
    DATE = 133  # Indicates a date value (yyyymmdd).
    TIME = 134  # Indicates a time value (hhmmss).
    DATETIME = 135  # Indicates a date-time stamp (yyyymmddhhmmss plus a fraction in billionths).
    HCHAPTER = 136  # Indicates a four-byte chapter value used to identify rows in a child rowset.


class TimeSteps(Enum):
    """Translates the time levels into usable step sizes."""

    def __new__(
        cls,
        value,
        steps,
    ):
        obj = object.__new__(cls)
        obj._value_ = value
        obj.steps = steps
        return obj

    Regular = 0, [0]
    TimeYears = 20, [1, 2]
    TimeHalfYears = 36, [1, 2]
    TimeTrimester = 4722, [1, 3]
    TimeQuarters = 68, [1, 4]
    TimeMonths = 132, [1, 3, 6, 12]
    TimeWeeks = 260, [1, 4]
    TimeDays = 516, [1, 7, 28]
    TimeHours = 772, [1, 12, 24]
    TimeMinutes = 1028, [1, 60]
    TimeSeconds = 2052, [1, 60]
    TimeUndefined = 4100, [0]

    def get_steps(self):
        if self.name == "Regular" or self.name == "TimeUndefined":
            return None
        else:
            return self.steps


class TimeLevels(Enum):
    """Breaks down the various time levels supported in both atscale and ansi sql"""

    def __new__(cls, value, timestep, sql_name):
        obj = object.__new__(cls)
        obj._value_ = value
        obj.index = value
        obj.timestep = timestep
        obj.sql_name = sql_name
        return obj

    # Only handling AtScale time levels that are also in ANSI SQL and are date_trunc
    # compatible right now; trying to be as generic as possible.
    Year = 0, TimeSteps.TimeYears, "year"
    Quarter = 1, TimeSteps.TimeQuarters, "quarter"
    Month = 2, TimeSteps.TimeMonths, "month"
    Week = 3, TimeSteps.TimeWeeks, "week"  # this one acts weird with date_trunc, so using date_part
    Day = 4, TimeSteps.TimeDays, "day"
    Hour = 5, TimeSteps.TimeHours, "hour"
    Minute = 6, TimeSteps.TimeMinutes, "minute"
    Second = 7, TimeSteps.TimeSeconds, "second"

    def get_sql_expression(
        self,
        col,
        platform_type,
    ):
        if (
            self.sql_name == "day"
            or self.sql_name == "hour"
            or self.sql_name == "minute"
            or self.sql_name == "second"
        ):
            if platform_type == PlatformType.IRIS:
                return f"DATE({col})"
            elif platform_type == PlatformType.SYNAPSE or platform_type == PlatformType.MSSQL:
                return f"DATETRUNC({self.sql_name}, {col})"
            elif platform_type == PlatformType.DATABRICKS:
                return f'date_trunc("{self.sql_name}", {col})'
            elif platform_type == PlatformType.GBQ:
                return f"date_trunc( {col}, {self.sql_name})"
            else:
                return f"date_trunc({self.sql_name}, {col})"
        else:
            if (
                platform_type == PlatformType.IRIS
                or platform_type == PlatformType.SYNAPSE
                or platform_type == PlatformType.MSSQL
            ):
                return f"DATEPART({self.sql_name}, {col})"
            elif platform_type == PlatformType.DATABRICKS:
                return f'date_part("{self.sql_name}", {col})'
            elif platform_type == PlatformType.GBQ:
                return f"EXTRACT({self.sql_name} from {col})"
            else:
                return f"date_part({self.sql_name}, {col})"


class Aggs(Enum):
    """Holds constant string representations for the supported aggregation methods of numerical aggregate features
    SUM: Addition
    AVG: Average
    MAX: Maximum
    MIN: Mininum
    DISTINCT_COUNT: Distinct-Count (count of unique values)
    DISTINCT_COUNT_ESTIMATE: An estimate of the distinct count to save compute
    NON_DISTINCT_COUNT: Count of all values
    STDDEV_SAMP: standard deviation of the sample
    STDDEV_POP: population standard deviation
    VAR_SAMP: sample variance
    VAR_POP: population variance
    """

    def __new__(cls, key_name, visual_rep):
        obj = object.__new__(cls)
        obj._value_ = key_name
        obj._customer_representation = visual_rep
        return obj

    SUM = "SUM", "Sum"
    AVG = "AVG", "Average"
    MAX = "MAX", "Max"
    MIN = "MIN", "Min"
    DISTINCT_COUNT = "DC", "Distinct Count"
    DISTINCT_COUNT_ESTIMATE = "DCE", "Distinct Count Estimate"
    NON_DISTINCT_COUNT = "NDC", "Non Distinct Count"
    STDDEV_SAMP = "STDDEV_SAMP", "Sample Standard Deviation"
    STDDEV_POP = "STDDEV_POP", "Population Standard Deviation"
    VAR_SAMP = "VAR_SAMP", "Sample Variance"
    VAR_POP = "VAR_POP", "Population Variance"

    @property
    def visual_rep(self):
        return self._customer_representation

    @classmethod
    def from_properties(cls, property_dict):
        if property_dict is None:
            return ""
        type_section = property_dict.get("type", {})
        if "measure" in type_section:
            return cls[type_section["measure"]["default-aggregation"]]
        elif "count-distinct" in type_section:
            if type_section["count-distinct"]["approximate"]:
                return cls.DISTINCT_COUNT_ESTIMATE
            else:
                return cls.DISTINCT_COUNT
        elif "count-nonnull":
            return cls.NON_DISTINCT_COUNT

    @classmethod
    def from_dmv_number(cls, number):
        num_to_value = {
            1: cls.SUM,
            5: cls.AVG,
            4: cls.MAX,
            3: cls.MIN,
            8: cls.DISTINCT_COUNT,
            1000: cls.DISTINCT_COUNT_ESTIMATE,  # dmv bug, comes back as 8
            2: cls.NON_DISTINCT_COUNT,
            7: cls.STDDEV_SAMP,
            333: cls.STDDEV_POP,  # dmv bug, comes back as 0
            0: cls.VAR_POP,
            6: cls.VAR_SAMP,
        }
        obj = num_to_value[number]
        return obj

    def requires_key_ref(self):
        return self in [
            self.__class__.DISTINCT_COUNT,
            self.__class__.DISTINCT_COUNT_ESTIMATE,
            self.__class__.NON_DISTINCT_COUNT,
        ]

    def get_dict_expression(
        self,
        key_ref,
    ):
        if self.requires_key_ref() and key_ref is None:
            raise atscale_errors.UserError(
                f"A key-ref id must be made and passed into this function in order to make a valid "
                f"{self.name} measure dict."
            )
        if self.name == "DISTINCT_COUNT":
            return {"count-distinct": {"key-ref": {"id": key_ref}, "approximate": False}}
        elif self.name == "DISTINCT_COUNT_ESTIMATE":
            return {"count-distinct": {"key-ref": {"id": key_ref}, "approximate": True}}
        elif self.name == "NON_DISTINCT_COUNT":
            return {"count-nonnull": {"key-ref": {"id": key_ref}, "approximate": False}}
        else:
            return {"measure": {"default-aggregation": self.value}}


class MDXAggs(Enum):
    """Holds constant string representations for the supported MDX aggregation methods
    SUM: Addition
    STANDARD_DEVIATION: standard deviation of the sample
    MEAN: Average
    MAX: Maximum
    MIN: Mininum
    """

    SUM = "Sum"
    STANDARD_DEVIATION = "Stdev"
    MEAN = "Avg"
    MAX = "Max"
    MIN = "Min"


class PandasTableExistsActionType(Enum):
    """Potential actions to take if a table already exists when trying to write a dataframe to that database table.
    APPEND: Append the rows to the end of the existing table
    REPLACE: Completely replace the existing table
    FAIL: raise an error
    """

    APPEND = "append"
    REPLACE = "replace"
    FAIL = "fail"


class PysparkTableExistsActionType(Enum):
    """Potential actions to take if a table already exists when trying to write a pyspark dataframe to that database table.
    APPEND: Append content of the pyspark dataframe to existing data or table
    OVERWRITE: Overwrite existing data with the content of pyspak dataframe
    IGNORE: Ignore current write operation if data/ table already exists without any error
    ERROR: Throw an exception if data or table already exists
    """

    APPEND = "append"
    OVERWRITE = "overwrite"
    IGNORE = "ignore"
    ERROR = "error"


class PlatformType(Enum):
    """PlatformTypes describe a type of supported data warehouse"""

    SNOWFLAKE = "snowflake"
    REDSHIFT = "redshift"
    GBQ = "bigquery"
    DATABRICKS = "databrickssql"
    IRIS = "iris"
    SYNAPSE = "azuresqldw"
    MSSQL = "mssql"
    POSTGRES = "postgresql"


class FeatureFormattingType(Enum):
    """How the value of a feature gets formatted before output"""

    GENERAL_NUMBER = "General Number"
    STANDARD = "Standard"
    SCIENTIFIC = "Scientific"
    FIXED = "Fixed"
    PERCENT = "Percent"


class FeatureType(Enum):
    """Used for specifying all features or only numerics or only categorical"""

    def __new__(
        cls,
        value,
        name_val,
    ):
        obj = object.__new__(cls)
        obj._value_ = value
        obj.name_val = name_val
        return obj

    ALL = (0, "All")
    NUMERIC = (1, "Numeric")
    CATEGORICAL = (2, "Categorical")


class RequestType(Enum):
    """Used for specifying type of http request"""

    GET = "GET"
    PATCH = "PATCH"
    POST = "POST"
    PUT = "PUT"
    DELETE = "DELETE"


class MappedColumnFieldTerminator(Enum):
    """Used for specifying mapped column field delimiters"""

    comma = ","
    semicolon = ";"
    pipe = "|"


class MappedColumnKeyTerminator(Enum):
    """Used for specifying mapped column key delimiters"""

    equals = "="
    colon = ":"
    caret = "^"


class MappedColumnDataTypes(Enum):
    """Used for specifying data type of mapped column"""

    Int = "Int"
    Long = ("Long",)
    Boolean = "Boolean"
    String = "String"
    Float = "Float"
    Double = "Double"
    Decimal = "Decimal"
    Datetime = "DateTime"
    Date = "Date"


class ScikitLearnModelType(Enum):
    """Used for specifying type of model being written to AtScale"""

    LINEARREGRESSION = "LinearRegression"
    LOGISTICREGRESSION = "LogisticRegression"


class CheckFeaturesErrMsg(Enum):
    """Used for specifying the sort of error message to be displayed via _check_features"""

    ALL = "Feature"
    CATEGORICAL = "Categorical feature"
    NUMERIC = "Numeric feature"
    HIERARCHY = "Hierarchy"

    def get_errmsg(self, is_published=False) -> str:
        """Renders a _check_features error message according to the feature list we're checking
           against + the publish status of the features we're checking against

        Args:
            is_published (bool, optional): Whether the features we're checking against are published. Defaults to False.

        Returns:
            str: The error message string.
        """
        if is_published:
            return (
                f"{self.value}(s): "
                + "{}"  # fstring broken up such that bracket is preserved for downstream formatting
                + f" not in data model. Make sure each {self.value.lower()} has been published and is correctly spelled."
            )
        else:
            return (
                f"The requested {self.value.lower()}(s) was/were not found: " + "{}"
            )  # fstring broken up such that bracket is preserved for downstream formatting
