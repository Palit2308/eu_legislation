from bs4 import BeautifulSoup
import pandas as pd
import re


# ------------------------------------------------------------
# helpers
# ------------------------------------------------------------
def clean_text(text: str) -> str:
    if text is None:
        return ""
    text = str(text).replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()


def split_members(member_text: str) -> list[str]:
    """
    Split a comma-separated member string into individual names.
    """
    member_text = clean_text(member_text)
    if not member_text:
        return []
    return [m.strip() for m in member_text.split(",") if m.strip()]


def map_vote_symbol_to_type(symbol: str) -> str | None:
    """
    Map roll-call symbol to requested vote type labels.
    """
    symbol = clean_text(symbol)
    return {
        "+": "pos",
        "-": "neg",
        "0": "abs",
    }.get(symbol)


def normalize_group(group: str) -> str:
    """
    Standardize group names across older/newer EP labels.
    """
    key = clean_text(group).upper()

    replacements = {
        "GUE-NGL": "GUE/NGL",
        "GUE/NGL": "GUE/NGL",
        "VERTS/ALE": "Verts/ALE",
        "THE LEFT": "THE LEFT",
        "THELEFT": "THE LEFT",
        "RENEW": "Renew",
        "RENEW EUROPE": "Renew",
    }

    return replacements.get(key, clean_text(group))


def get_cell_paragraphs(cell, keep_blanks: bool = False) -> list[str]:
    """
    Return paragraph texts from a cell, preserving order.

    If there are no <p> tags, fall back to the cell text itself.
    """
    paragraphs = cell.find_all("p")

    if paragraphs:
        vals = [clean_text(p.get_text(" ", strip=True)) for p in paragraphs]
    else:
        vals = [clean_text(cell.get_text(" ", strip=True))]

    if keep_blanks:
        return vals
    return [v for v in vals if v]


def extract_group_member_pairs_from_cells(group_cell, member_cell) -> list[tuple[str, str]]:
    """
    Parse a pair of cells into [(group, member_blob), ...].

    Handles both:
    1) simple row-wise layout:
       one group and one member blob per row
    2) packed block layout:
       several groups in one cell and several member blobs in the other cell,
       with possible blank group paragraphs indicating continuation lines.
    """
    group_lines_all = get_cell_paragraphs(group_cell, keep_blanks=True)
    member_lines_all = get_cell_paragraphs(member_cell, keep_blanks=True)

    group_lines_nonblank = [g for g in group_lines_all if clean_text(g)]
    member_lines_nonblank = [m for m in member_lines_all if clean_text(m)]

    # completely empty row/block
    if not group_lines_nonblank and not member_lines_nonblank:
        return []

    # --------------------------------------------------------
    # Case 1: normal row layout
    # --------------------------------------------------------
    if len(group_lines_nonblank) <= 1 and len(member_lines_nonblank) <= 1:
        group = normalize_group(group_lines_nonblank[0]) if group_lines_nonblank else ""
        member_blob = member_lines_nonblank[0] if member_lines_nonblank else ""

        if group and member_blob:
            return [(group, member_blob)]
        return []

    # --------------------------------------------------------
    # Case 2: packed multi-paragraph layout
    # --------------------------------------------------------
    pairs = []
    current_group = None
    current_member_parts = []

    max_len = max(len(group_lines_all), len(member_lines_all))

    for i in range(max_len):
        g = clean_text(group_lines_all[i]) if i < len(group_lines_all) else ""
        m = clean_text(member_lines_all[i]) if i < len(member_lines_all) else ""

        if g:
            # flush previous group
            if current_group and current_member_parts:
                pairs.append(
                    (normalize_group(current_group), clean_text(" ".join(current_member_parts)))
                )

            current_group = g
            current_member_parts = [m] if m else []
        else:
            # continuation line for previous group
            if current_group and m:
                current_member_parts.append(m)

    # flush last group
    if current_group and current_member_parts:
        pairs.append(
            (normalize_group(current_group), clean_text(" ".join(current_member_parts)))
        )

    return pairs


def parse_rollcall_html(
    rollcall_html: str,
    procedure: str,
    committee: str,
    designation: str
) -> list[dict]:
    """
    Parse one rollcall_string into member-level long rows.

    Output columns:
    procedure, committee, designation, vote_type, group, member
    """
    if pd.isna(rollcall_html) or not clean_text(rollcall_html):
        return []

    soup = BeautifulSoup(rollcall_html, "html.parser")
    tables = soup.find_all("table")
    out_rows = []

    for table in tables:
        trs = table.find_all("tr")
        if len(trs) < 2:
            continue

        # --------------------------------------------
        # header row: total + vote symbol
        # --------------------------------------------
        header_cells = trs[0].find_all("td")
        if len(header_cells) < 2:
            continue

        vote_symbol = clean_text(header_cells[1].get_text(" ", strip=True))
        vote_type = map_vote_symbol_to_type(vote_symbol)

        if vote_type is None:
            continue

        # --------------------------------------------
        # remaining rows: parse all of them
        # --------------------------------------------
        for tr in trs[1:]:
            cells = tr.find_all("td")
            if len(cells) < 2:
                continue

            # ignore possible trailing blank third column
            group_cell = cells[0]
            member_cell = cells[1]

            pairs = extract_group_member_pairs_from_cells(group_cell, member_cell)

            for group, member_blob in pairs:
                members = split_members(member_blob)

                for member in members:
                    out_rows.append({
                        "procedure": procedure,
                        "committee": committee,
                        "designation": designation,
                        "vote_type": vote_type,
                        "group": group,
                        "member": member,
                    })

    return out_rows


def expand_committee_roll_call(df: pd.DataFrame) -> pd.DataFrame:
    """
    Expand committee roll-call HTML into long member-level rows.

    Expected input columns:
    procedure, committee, designation, rollcall_string
    """
    all_rows = []

    for _, row in df.iterrows():
        procedure = row["procedure"]
        committee = row["committee"]
        designation = row["designation"]
        rollcall_html = row.get("rollcall_string", "")

        parsed_rows = parse_rollcall_html(
            rollcall_html=rollcall_html,
            procedure=procedure,
            committee=committee,
            designation=designation
        )
        all_rows.extend(parsed_rows)

    df_rollcalls_long = pd.DataFrame(
        all_rows,
        columns=[
            "procedure",
            "committee",
            "designation",
            "vote_type",
            "group",
            "member",
        ]
    )

    # ------------------------------------------------------------
    # merge duplicated lead committees within the same procedure
    # e.g. IMCO + JURI  ->  IMCO/JURI
    # ------------------------------------------------------------
    lead_combo_map = (
        df.loc[df["designation"].eq("lead")]
          .groupby("procedure")["committee"]
          .agg(lambda s: sorted(pd.unique(s)))
    )

    lead_combo_map = lead_combo_map[lead_combo_map.apply(len) > 1]
    lead_combo_map = {proc: "/".join(committees) for proc, committees in lead_combo_map.items()}

    mask = (
        df_rollcalls_long["designation"].eq("lead")
        & df_rollcalls_long["procedure"].isin(lead_combo_map)
    )

    df_rollcalls_long.loc[mask, "committee"] = (
        df_rollcalls_long.loc[mask, "procedure"].map(lead_combo_map)
    )

    df_rollcalls_long = df_rollcalls_long.drop_duplicates().reset_index(drop=True)

    return df_rollcalls_long





# from bs4 import BeautifulSoup
# import pandas as pd
# import re


# # ------------------------------------------------------------
# # helpers
# # ------------------------------------------------------------
# def clean_text(text: str) -> str:
#     if text is None:
#         return ""
#     return re.sub(r"\s+", " ", str(text)).strip()


# def split_members(member_text: str) -> list[str]:
#     """
#     Split a comma-separated member string into individual names.
#     """
#     member_text = clean_text(member_text)
#     if not member_text:
#         return []
#     return [m.strip() for m in member_text.split(",") if m.strip()]


# def map_vote_symbol_to_type(symbol: str) -> str | None:
#     """
#     Map roll-call symbol to requested vote type labels.
#     """
#     symbol = clean_text(symbol)
#     return {
#         "+": "pos",
#         "-": "neg",
#         "0": "abs",
#     }.get(symbol)


# def normalize_group(group: str) -> str:
#     group = clean_text(group)
#     replacements = {
#         "GUE-NGL": "GUE/NGL",
#     }
#     return replacements.get(group, group)


# # def parse_rollcall_html(
# #     rollcall_html: str,
# #     procedure: str,
# #     committee: str,
# #     designation: str
# # ) -> list[dict]:
# #     """
# #     Parse one rollcall_string into member-level long rows.

# #     Output columns:
# #     procedure, committee, designation, vote_type, group, member
# #     """
# #     if pd.isna(rollcall_html) or not clean_text(rollcall_html):
# #         return []

# #     soup = BeautifulSoup(rollcall_html, "html.parser")
# #     tables = soup.find_all("table")
# #     out_rows = []

# #     for table in tables:
# #         trs = table.find_all("tr")
# #         if len(trs) < 2:
# #             continue

# #         # first row: total count + vote symbol
# #         header_cells = trs[0].find_all("td")
# #         if len(header_cells) < 2:
# #             continue

# #         vote_symbol = clean_text(header_cells[1].get_text(" ", strip=True))
# #         vote_type = map_vote_symbol_to_type(vote_symbol)

# #         if vote_type is None:
# #             continue

# #         # all remaining rows are possible group/member rows
# #         for tr in trs[1:]:
# #             cells = tr.find_all("td")
# #             if len(cells) < 2:
# #                 continue

# #             group = normalize_group(cells[0].get_text(" ", strip=True))
# #             member_blob = clean_text(cells[1].get_text(" ", strip=True))

# #             # skip blank spacer rows
# #             if not group and not member_blob:
# #                 continue

# #             # if one side is blank, skip for now
# #             # (better to skip than invent wrong rows)
# #             if not group or not member_blob:
# #                 continue

# #             members = split_members(member_blob)

# #             for member in members:
# #                 out_rows.append({
# #                     "procedure": procedure,
# #                     "committee": committee,
# #                     "designation": designation,
# #                     "vote_type": vote_type,
# #                     "group": group,
# #                     "member": member,
# #                 })

# #     return out_rows

# def parse_rollcall_html(
#     rollcall_html: str,
#     procedure: str,
#     committee: str,
#     designation: str
# ) -> list[dict]:
#     """
#     Parse one rollcall_string into member-level long rows.

#     Output columns:
#     procedure, committee, designation, vote_type, group, member
#     """
#     if pd.isna(rollcall_html) or not clean_text(rollcall_html):
#         return []

#     soup = BeautifulSoup(rollcall_html, "html.parser")
#     tables = soup.find_all("table")
#     out_rows = []

#     for table in tables:
#         trs = table.find_all("tr")
#         if len(trs) < 2:
#             continue

#         # first row: total count + vote symbol
#         header_cells = trs[0].find_all("td")
#         if len(header_cells) < 2:
#             continue

#         vote_symbol = clean_text(header_cells[1].get_text(" ", strip=True))
#         vote_type = map_vote_symbol_to_type(vote_symbol)

#         if vote_type is None:
#             continue

#         # second row: groups and member blobs
#         data_cells = trs[1].find_all("td")
#         if len(data_cells) < 2:
#             continue

#         group_ps = [clean_text(p.get_text(" ", strip=True)) for p in data_cells[0].find_all("p")]
#         member_ps = [clean_text(p.get_text(" ", strip=True)) for p in data_cells[1].find_all("p")]

#         # remove empty paragraphs
#         group_ps = [g for g in group_ps if g]
#         member_ps = [m for m in member_ps if m]

#         # Usually these align 1-to-1 after removing blanks
#         n = min(len(group_ps), len(member_ps))

#         for group, member_blob in zip(group_ps[:n], member_ps[:n]):
#             members = split_members(member_blob)

#             for member in members:
#                 out_rows.append({
#                     "procedure": procedure,
#                     "committee": committee,
#                     "designation": designation,
#                     "vote_type": vote_type,
#                     "group": group,
#                     "member": member,
#                 })

#     return out_rows


# def expand_committee_roll_call(df: pd.DataFrame) -> pd.DataFrame:
#     """
#     Expand committee roll-call HTML into long member-level rows.

#     Expected input columns:
#     procedure, committee, designation, rollcall_string
#     """
#     all_rows = []

#     for _, row in df.iterrows():
#         procedure = row["procedure"]
#         committee = row["committee"]
#         designation = row["designation"]
#         rollcall_html = row.get("rollcall_string", "")

#         parsed_rows = parse_rollcall_html(
#             rollcall_html=rollcall_html,
#             procedure=procedure,
#             committee=committee,
#             designation=designation
#         )
#         all_rows.extend(parsed_rows)

#     df_rollcalls_long = pd.DataFrame(
#         all_rows,
#         columns=[
#             "procedure",
#             "committee",
#             "designation",
#             "vote_type",
#             "group",
#             "member",
#         ]
#     )

#     # ------------------------------------------------------------
#     # merge duplicated lead committees within the same procedure
#     # e.g. IMCO + JURI  ->  IMCO/JURI
#     # ------------------------------------------------------------
#     lead_combo_map = (
#         df.loc[df["designation"].eq("lead")]
#           .groupby("procedure")["committee"]
#           .agg(lambda s: sorted(pd.unique(s)))
#     )

#     # keep only procedures with more than one lead committee
#     lead_combo_map = lead_combo_map[lead_combo_map.apply(len) > 1]

#     # convert list like ["IMCO", "JURI"] -> "IMCO/JURI"
#     lead_combo_map = {proc: "/".join(committees) for proc, committees in lead_combo_map.items()}

#     # relabel lead committee rows in the long dataframe
#     mask = (
#         df_rollcalls_long["designation"].eq("lead")
#         & df_rollcalls_long["procedure"].isin(lead_combo_map)
#     )

#     df_rollcalls_long.loc[mask, "committee"] = (
#         df_rollcalls_long.loc[mask, "procedure"].map(lead_combo_map)
#     )

#     # remove exact duplicates just in case
#     df_rollcalls_long = df_rollcalls_long.drop_duplicates().reset_index(drop=True)

#     return df_rollcalls_long