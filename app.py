import streamlit as st
import pandas as pd
import logging
import re

def split_id_name(value):
    if pd.isna(value):
        return (None, None)
    # Split on dash with optional spaces around it
    parts = re.split(r"\s*-\s*", str(value), maxsplit=1)
    if len(parts) == 2:
        return parts[0].strip(), parts[1].strip()
    else:
        return parts[0].strip(), None
    
logger = logging.getLogger("claims_payments_app")
logger.setLevel(logging.DEBUG)

if not logger.handlers:  # only add handler once
    fh = logging.FileHandler("app_debug.log", mode="w")
    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    fh.setFormatter(formatter)
    logger.addHandler(fh)

logger.info("✅ App started")


st.title("Claims & Payments Summary Demo")

# Upload files
claims_file = st.file_uploader("Upload Claims Excel", type=["xlsx"])
payments_file = st.file_uploader("Upload Payments Excel", type=["xlsx"])

if claims_file and payments_file:
    # Read Excel files
    claims_df = pd.read_excel(claims_file)
    payments_df = pd.read_excel(payments_file)

    logger.debug(f"Claims columns: {claims_df.columns.tolist()}")
    logger.debug(f"Payments columns: {payments_df.columns.tolist()}")

    logger.debug(f"Claims file loaded with {len(claims_df)} rows")
    logger.debug(f"Payments file loaded with {len(payments_df)} rows")
    
    claims_df["Referring Doctor Practice"] = claims_df["Referring Doctor Practice"].str.strip()
    payments_df["Referring Provider Practice"] = payments_df["Referring Provider Practice"].str.strip()

    # Aggregate payments
    claims_summary = claims_df.groupby("Referring Doctor Practice").agg(
        Number_of_Payments=("Charges Amount", "count"),
        Total_Payment_Value=("Charges Amount", "sum")
    ).reset_index()

    # Aggregate claims
    payments_summary = payments_df.groupby("Referring Provider Practice").agg(
        Number_of_Claims=("Insurance Payments", "count"),
        Total_Claim_Value=("Insurance Payments", "sum")
    ).reset_index()

    logger.debug(f"Claims summary has {len(claims_summary)} rows")
    logger.debug(f"Payments summary has {len(payments_summary)} rows")

    # Merge summaries
    final_summary = pd.merge(claims_summary, payments_summary, left_on="Referring Doctor Practice", right_on="Referring Provider Practice", how="outer")
    
    logger.debug(f"Final summary has {len(final_summary)} rows")

    final_summary["Practice"] = (
        final_summary["Referring Doctor Practice"].combine_first(final_summary["Referring Provider Practice"])
    )
    
    # Split on "-" and strip whitespace
    final_summary[["Practice_ID", "Practice_Name"]] = final_summary["Practice"].apply(split_id_name).apply(pd.Series)
    claims_summary[["Practice_ID", "Practice_Name"]] = claims_summary["Referring Doctor Practice"].apply(split_id_name).apply(pd.Series)
    payments_summary[["Practice_ID", "Practice_Name"]] = payments_summary["Referring Provider Practice"].apply(split_id_name).apply(pd.Series)


    # Clean up whitespace
    final_summary["Practice_ID"] = final_summary["Practice_ID"].str.strip()
    final_summary["Practice_Name"] = final_summary["Practice_Name"].str.strip()

    claims_summary["Practice_ID"] = claims_summary["Practice_ID"].str.strip()
    claims_summary["Practice_Name"] = claims_summary["Practice_Name"].str.strip()
    claims_summary["Practice_ID"] = pd.to_numeric(claims_summary["Practice_ID"], errors="coerce").fillna(0)

    payments_summary["Practice_ID"] = payments_summary["Practice_ID"].str.strip()
    payments_summary["Practice_Name"] = payments_summary["Practice_Name"].str.strip()
    payments_summary["Practice_ID"] = pd.to_numeric(payments_summary["Practice_ID"], errors="coerce").fillna(0)

    final_summary = final_summary.dropna(subset=["Practice_ID"])

    final_summary = final_summary.drop(
        columns=["Practice", "Referring Provider Practice", "Referring Doctor Practice"]
    )

    # Get all current columns
    cols = final_summary.columns.tolist()

    # Put ID and Name first, then the rest
    new_order = ["Practice_ID", "Practice_Name"] + [c for c in cols if c not in ["Practice_ID", "Practice_Name"]]

    # Reorder DataFrame
    final_summary = final_summary[new_order]

    # Convert all other columns except Practice_Name
    for col in final_summary.columns:
        if col not in ["Practice_Name"]:
            final_summary[col] = pd.to_numeric(final_summary[col], errors="coerce").fillna(0)


    # Show table
    st.subheader("Summary by Practise ID")
    st.dataframe(final_summary)
    st.dataframe(claims_summary)
    st.dataframe(payments_summary)

    # Download option
    csv = final_summary.to_csv(index=False).encode("utf-8")
    st.download_button("Download Summary CSV", csv, "summary.csv", "text/csv")

