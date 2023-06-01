import pandas as pd
from typing import List, Dict, Optional
from docassemble.base.util import log

__all__ = ["get_LIST_codes"]


def get_LIST_codes(
    file_path: str, custom_order: Optional[List[str]] = None
) -> List[Optional[Dict[str, str]]]:
    """
    Reads a CSV file and creates a list of dictionaries structured in a YAML-like format.

    The CSV file must have 'Code' and 'Title' columns. Group names are defined by entries with
    a 'Code' ending with '-00-00-00-00'. Each entry that has additional non-zero digits is listed
    under a group that shares the same initial 2-letter prefix.

    Args:
        file_path (str): The path to the CSV file to read.

    Returns:
        List[Optional[Dict[str, str]]]: The list of dictionaries representing the CSV data.
            Each dictionary has the format {"label": title, "key": code, "group": group_name}.

    """
    if custom_order is None:
        # Default ordering by relevance
        custom_order = ["HO", "FA", "MO", "BE", "EM", "HE", "CO"]

    def get_order(prefix: str) -> int:
        if custom_order is None:
            return 999999999999
        return (
            custom_order.index(prefix) if prefix in custom_order else len(custom_order)
        )

    # Load the CSV into a pandas DataFrame
    df = pd.read_csv(file_path)

    # Extract the two-letter prefix and '-00-00-00-00' suffix
    df["Prefix"] = df["Code"].str.slice(0, 2)
    df["Suffix"] = df["Code"].str.slice(
        2,
    )

    # Create a group mapping dictionary
    group_dict = (
        df.loc[df["Suffix"] == "-00-00-00-00", ["Prefix", "Title"]]
        .set_index("Prefix")["Title"]
        .to_dict()
    )

    # Define a function to create the desired dictionary for each row
    def create_dict(row: pd.Series) -> Optional[Dict[str, str]]:
        if row["Suffix"] != "-00-00-00-00":
            return {
                "label": row["Title"],
                "value": row["Code"],
                "group": group_dict.get(row["Prefix"], "MISC"),
            }
        else:
            return None  # We'll drop these None rows later

    # Apply the function to all rows
    df["YAML"] = df.apply(create_dict, axis=1)

    # Extract the group and label from each dictionary and add them as columns in the dataframe
    df = df.join(df["YAML"].apply(pd.Series)[["group", "label"]])

    df = df.dropna(subset=["YAML"])

    # Add a column that represents the custom order of prefixes
    df["Order"] = df["Prefix"].apply(get_order)

    # Sort the dataframe first by the custom order, then alphabetically by group and finally by label
    df = df.sort_values(by=["Order", "group", "label"])

    return df["YAML"].tolist()
