import streamlit as st
import pandas as pd
import logging
import re
from io import BytesIO

def split_id_name(value):
    if pd.isna(value):
        return (None, None)
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
    claims_df = pd.read_excel(claims_file)
    payments_df = pd.read_excel(payments_file)

    claims_df["Referring Doctor Practice"] = claims_df["Referring Doctor Practice"].str.strip()
    payments_df["Referring Provider Practice"] = payments_df["Referring Provider Practice"].str.strip()

    # Aggregate
    claims_summary = claims_df.groupby("Referring Doctor Practice").agg(
        Number_of_Claims=("Charges Amount", "count"),
        Total_Claim_Value=("Charges Amount", "sum")
    ).reset_index()

    payments_summary = payments_df.groupby("Referring Provider Practice").agg(
        Number_of_Payments=("Insurance Payments", "count"),
        Total_Payment_Value=("Insurance Payments", "sum")
    ).reset_index()

    final_summary = pd.merge(
        claims_summary, payments_summary,
        left_on="Referring Doctor Practice", right_on="Referring Provider Practice", how="outer"
    )

    final_summary["Practice"] = final_summary["Referring Doctor Practice"].combine_first(final_summary["Referring Provider Practice"])
    final_summary[["Practice_ID", "Practice_Name"]] = final_summary["Practice"].apply(split_id_name).apply(pd.Series)

    final_summary["Practice_ID"] = final_summary["Practice_ID"].str.strip()
    final_summary["Practice_Name"] = final_summary["Practice_Name"].str.strip()
    final_summary["Practice_ID"] = pd.to_numeric(final_summary["Practice_ID"], errors="coerce").fillna(0)

    final_summary = final_summary.dropna(subset=["Practice_ID"])
    final_summary = final_summary.drop(columns=["Practice", "Referring Provider Practice", "Referring Doctor Practice"])

    cols = final_summary.columns.tolist()
    new_order = ["Practice_ID", "Practice_Name"] + [c for c in cols if c not in ["Practice_ID", "Practice_Name"]]
    final_summary = final_summary[new_order]

    for col in final_summary.columns:
        if col not in ["Practice_Name"]:
            final_summary[col] = pd.to_numeric(final_summary[col], errors="coerce").fillna(0)

    # Show tables
    st.subheader("Summary by Practise ID")
    st.dataframe(final_summary)
    st.dataframe(claims_summary)
    st.dataframe(payments_summary)

    # --- Excel download with formatting + charts ---
    output = BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        final_summary.to_excel(writer, index=False, sheet_name="Summary")
        workbook = writer.book
        worksheet = writer.sheets["Summary"]

        # Header formatting
        header_format = workbook.add_format({"bold": True, "bg_color": "#D7E4BC", "border": 1})
        for col_num, value in enumerate(final_summary.columns.values):
            worksheet.write(0, col_num, value, header_format)

        # Column formatting
        num_format = workbook.add_format({"num_format": "#,##0", "border": 1})
        text_format = workbook.add_format({"border": 1})
        for i, col in enumerate(final_summary.columns):
            if col in ["Practice_ID", "Number_of_Claims", "Total_Claim_Value", "Number_of_Payments", "Total_Payment_Value"]:
                worksheet.set_column(i, i, 18, num_format)
            else:
                worksheet.set_column(i, i, 25, text_format)

        # Bar chart: Top 10 by Total_Payment_Value
        chart1 = workbook.add_chart({"type": "column"})
        top10 = final_summary.nlargest(10, "Total_Payment_Value")
        row_start = 1
        row_end = len(top10)
        chart1.add_series({
            "name": "Top 10 Payments",
            "categories": ["Summary", row_start, 1, row_end, 1],
            "values": ["Summary", row_start, final_summary.columns.get_loc("Total_Payment_Value"), row_end, final_summary.columns.get_loc("Total_Payment_Value")],
        })
        chart1.set_title({"name": "Top 10 Practices by Payment Value"})
        chart1.set_x_axis({"name": "Practice"})
        chart1.set_y_axis({"name": "Payment Value"})
        worksheet.insert_chart("H2", chart1, {"x_scale": 1.5, "y_scale": 1.5})

        # Pie chart: Claim Value Distribution
        chart2 = workbook.add_chart({"type": "pie"})
        chart2.add_series({
            "name": "Claim Value Distribution",
            "categories": ["Summary", 1, 1, len(final_summary), 1],
            "values": ["Summary", 1, final_summary.columns.get_loc("Total_Claim_Value"), len(final_summary), final_summary.columns.get_loc("Total_Claim_Value")],
        })
        chart2.set_title({"name": "Claim Value Distribution"})
        worksheet.insert_chart("H20", chart2, {"x_scale": 1.3, "y_scale": 1.3})

    st.download_button(
        label="Download Summary Excel with Charts",
        data=output.getvalue(),
        file_name="summary_with_charts.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
