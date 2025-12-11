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
    
# --- Logging Setup ---
logger = logging.getLogger("claims_payments_app")
logger.setLevel(logging.DEBUG)

if not logger.handlers:  # only add handler once
    fh = logging.FileHandler("app_debug.log", mode="w")
    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    fh.setFormatter(formatter)
    logger.addHandler(fh)

logger.info("✅ App started")

st.title("Claims & Payments Summary Demo")

# --- File Uploads ---
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

    numeric_cols = [col for col in final_summary.columns if col not in ["Practice_Name", "Practice_ID"]]
    for col in numeric_cols:
        final_summary[col] = pd.to_numeric(final_summary[col], errors="coerce").fillna(0)
    
    final_summary["Practice_ID"] = pd.to_numeric(final_summary["Practice_ID"], errors="coerce").fillna(0).astype(int)

    cols = final_summary.columns.tolist()
    new_order = ["Practice_ID", "Practice_Name"] + [c for c in cols if c not in ["Practice_ID", "Practice_Name"]]
    final_summary = final_summary[new_order]
    
    # Calculate Payment Rate
    final_summary["Payment_Rate"] = (
        final_summary["Total_Payment_Value"]
        / final_summary["Total_Claim_Value"].replace(0, pd.NA)
    ).fillna(0) 

    # --- STREAMLIT DASHBOARD LAYOUT ---
    
    st.header("Practice Performance Dashboard")
    
    # --- 0. Overall Summary Metrics (NEW) ---
    st.header("🌎 Overall Claims and Payments Summary")

    total_claim_value = final_summary["Total_Claim_Value"].sum()
    total_payment_value = final_summary["Total_Payment_Value"].sum()
    overall_rate = total_payment_value / total_claim_value if total_claim_value else 0

    col1, col2, col3 = st.columns(3)

    col1.metric("Total Claim Value", f"${total_claim_value:,.2f}")
    col2.metric("Total Payment Value", f"${total_payment_value:,.2f}")
    col3.metric("Overall Payment Rate", f"{overall_rate*100:,.2f}%")

    overall_df = pd.DataFrame({
        'Metric': ['Total Claim Value', 'Total Payment Value'],
        'Value': [total_claim_value, total_payment_value]
    })

    st.bar_chart(
        overall_df, 
        x='Metric', 
        y='Value', 
        color='Metric', # Add color for clarity
        use_container_width=True
    )
    st.markdown("---")
    
    # 1. Filters (Sidebar)
    st.sidebar.header("Filter & Sort Options")
    
    sort_options = {
        "Total Claim Value": "Total_Claim_Value", 
        "Total Payment Value": "Total_Payment_Value", 
        "Payment Rate": "Payment_Rate",
        "Number of Claims": "Number_of_Claims"
    }
    
    sort_label = st.sidebar.selectbox(
        "Sort Practices By:",
        list(sort_options.keys()),
        index=0
    )
    sort_by = sort_options[sort_label]
    
    # Filter the data based on sorting
    sorted_summary = final_summary.sort_values(sort_by, ascending=False)
    
    # Top N Control
    top_n = st.sidebar.slider(
        "Show Top N Practices (based on sorting)", 
        min_value=5, max_value=len(final_summary), value=10
    )
    
    summary_for_viz = sorted_summary.head(top_n)

    # Practice Specific Filter
    all_practice_names = sorted_summary["Practice_Name"].unique().tolist()
    practice_filter = st.sidebar.multiselect(
        "Or, Select Specific Practices (Overrides Top N):",
        options=all_practice_names,
        default=[]
    )
    
    if practice_filter:
        summary_for_viz = sorted_summary[sorted_summary["Practice_Name"].isin(practice_filter)]

    
    # 2. Main Visualizations
    
    if summary_for_viz.empty:
        st.warning("No data found for the selected filters.")
    else:
        # --- Visualization 1: Claims vs. Payments Value Comparison (FIXED SORTING) ---
        st.subheader("🏥 Claims vs. Payments Value Comparison by Practice")
        st.caption(f"Showing {len(summary_for_viz)} practices, sorted by: **{sort_label}**")
        
        melted_summary = summary_for_viz.melt(
            id_vars=["Practice_Name"],
            value_vars=["Total_Claim_Value", "Total_Payment_Value"],
            var_name="Metric Type",
            value_name="Amount"
        )

        # Get the desired sort order for the X-axis
        x_sort_order = summary_for_viz.sort_values(sort_by, ascending=False)["Practice_Name"].tolist()

        # Use Altair for explicit sorting control
        chart = alt.Chart(melted_summary).mark_bar().encode(
            x=alt.X('Practice_Name', sort=x_sort_order, title="Practice Name"), 
            y=alt.Y('Amount', title="Value ($)"),
            color='Metric Type',
            tooltip=['Practice_Name', 'Metric Type', alt.Tooltip('Amount', format='$,.2f')],
        ).properties(
            # title="Claims vs. Payments Value by Practice"
        ).interactive() 

        st.altair_chart(chart, use_container_width=True)
        
        st.markdown("---")
        
        # --- Visualization 2: Payment Rate by Practice ---
        st.subheader("📈 Payment Rate by Practice")
        
        rate_df = summary_for_viz # Already sorted by the control

        # Use a standard bar chart since sorting isn't critical here, or use Altair for consistency
        st.bar_chart(
            data=rate_df,
            x="Practice_Name",
            y="Payment_Rate",
            use_container_width=True
        )

        # 3. Summary Table
        st.header("Summary Data Table")
        
        display_cols = ["Practice_ID", "Practice_Name", "Total_Claim_Value", "Total_Payment_Value", "Payment_Rate", "Number_of_Claims", "Number_of_Payments"]
        st.dataframe(final_summary[display_cols].sort_values(sort_by, ascending=False))
        
        # 4. Download option
        csv = final_summary.to_csv(index=False).encode("utf-8")
        st.download_button("Download Full Summary CSV", csv, "summary.csv", "text/csv")