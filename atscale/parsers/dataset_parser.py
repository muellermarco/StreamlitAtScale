from typing import Optional, List, Union


class Column:
    """A nicer representation for project dataset columns in the atscale project json,
    self.column is the raw dict, all fields are mutable but can not be reassigned unless they
    have a defined setter"""

    def __init__(self, column_dict):
        self.column = column_dict

    def is_calculated(self) -> bool:
        """Whether or not the column is calculated, has sqls field"""
        return "sqls" in self.column

    @property
    def name(self) -> str:
        """Getter for the columns name"""
        return self.column.get("name")

    @property
    def query(self) -> Optional[str]:
        """Getter for the column's query if it is calculated, otherwise returns None"""
        return self.column.get("sqls")

    @property
    def dtype(self) -> str:
        """Getter for the column's data type, as of 04-26-2023 this returns a string as we don't
        have the options for column dtypes semantically defined in our code base yet."""
        return self.column["type"]["data-type"]


class Dataset:
    """A nicer representation for dataset dicts,
    self.dset is the raw dict, all fields are mutable but can not be reassigned unless they have a
    defined setter"""

    def __init__(self, dataset_dict: dict):
        self.dset = dataset_dict

    @property
    def name(self) -> str:
        """Returns the name field of the dataset"""
        return self.dset["name"]

    @property
    def columns(self) -> List[Column]:
        """Returns a list of columns from the dataset represented as Column objects"""
        return [Column(c) for c in self.dset["physical"]["columns"]]

    @columns.setter
    def columns(self, new_columns: List[Union[Column, dict]]):
        """Sets the columns of the dataset to the new_columns list,
        new_columns can be a list of Column objects or dicts or a mix.
        The input list will not be mutated"""
        raw_columns = [None for _ in new_columns]
        for i, col in enumerate(new_columns):
            if isinstance(col, Column):
                raw_columns[i] = col.column  # pull out the actual dict
            else:
                raw_columns[i] = col
        self.dset["physical"]["columns"] = raw_columns

    @property
    def table(self) -> Optional[str]:
        """Returns the table name if the dataset is a not QDS, otherwise returns None"""
        if "tables" in self.dset["physical"]:
            return self.dset["physical"]["tables"][0]
        else:
            return None

    def is_qds(self) -> bool:
        """Whether this dataset is a QDS"""
        return self.table is None

    @property
    def connection_id(self) -> str:
        """Returns the connection id (also known as warehouse_id) of the dataset"""
        return self.dset["physical"]["connection"]["id"]
