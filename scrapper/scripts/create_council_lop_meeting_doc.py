from pathlib import Path
import sys
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(PROJECT_ROOT))

from functions.create_council_lop_meeting_doc import (
    get_council_config_df,
    create_council_lop_df1,
    create_df1,
    add_lop_links,
    create_df_lop,
)


def main():
    council_config_df = get_council_config_df()

    council_meta = pd.read_csv(PROJECT_ROOT / "bld" / "council_votes.csv")

    council_lop_df1 = create_council_lop_df1(council_meta, council_config_df)

    df1 = create_df1(council_lop_df1)

    df1 = add_lop_links(df1)

    df_lop = create_df_lop(df1)

    df_lop.to_csv(PROJECT_ROOT / "bld" / "council_lop_out_docs.csv", index=False)


if __name__ == "__main__":
    main()