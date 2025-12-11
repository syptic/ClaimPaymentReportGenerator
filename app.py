import streamlit as st
import pandas as pd
import re
import io
import altair as alt
from io import BytesIO
import xlsxwriter # Ensure this library is available for the Excel logic

# --- 1. Helper Function: Text File Parsing ---
def parse_lab_log(uploaded_file):
    """Parses the fixed-width/regex formatted lab text file."""
    if uploaded_file is None:
        return pd.DataFrame(columns=["Practice_ID", "Practice_Name", "Samples"])
    
    # Read and decode
    # Using io.StringIO for reading text file content from uploaded object
    stringio = io.StringIO(uploaded_file.getvalue().decode("utf-8"))
    lines = stringio.readlines()

    # Regex: Capture ID, Name (skip EMR/whitespace), and Total Samples
    pattern = r'^\s*(?P<Practice_ID>\d+)\s*-(?P<Practice_Name>.*?)(?:\s{2,}.*)?\s+(?P<Samples>\d+)\s*$'

    # Filter valid lines (starting with whitespace and digits)
    data_lines = [line for line in lines if re.match(r'^\s*\d+', line)]

    if not data_lines:
        return pd.DataFrame(columns=["Practice_ID", "Practice_Name", "Samples"])

    # Extract
    df = pd.Series(data_lines).str.extract(pattern)

    # Type Conversion
    df["Practice_ID"] = pd.to_numeric(df["Practice_ID"])
    df["Samples"] = pd.to_numeric(df["Samples"])
    df["Practice_Name"] = df["Practice_Name"].str.strip()

    return df

# --- 2. Helper Function: Generate Summary Table ---
def generate_summary(claims_sub, payments_sub, samples_df, sample_col_name):
    """
    Aggregates claims, payments, and samples into a single summary table.
    """
    # Group Claims
    c_agg = claims_sub.groupby("Practice_ID").agg(
        Number_of_Claims=("Charges Amount", "count"),
        Total_Claim_Value=("Charges Amount", "sum"),
        Practice_Name=("Practice_Name", "first"),
    ).reset_index()

    # Group Payments
    p_agg = payments_sub.groupby("Practice_ID").agg(
        Number_of_Payments=("Amount", "count"),
        Total_Payment_Value=("Amount", "sum"),
        Practice_Name=("Practice_Name", "first"),
    ).reset_index()

    # Group Samples (to ensure unique IDs before merge)
    s_agg = samples_df.groupby("Practice_ID").agg(
        Samples=("Samples", "sum"),
        Practice_Name=("Practice_Name", "first")
    ).reset_index()
    s_agg = s_agg.rename(columns={"Samples": sample_col_name})

    # Merge Claims + Payments
    merged = pd.merge(c_agg, p_agg, on="Practice_ID", how="outer", suffixes=("_c", "_p"))
    
    # Combine Names
    merged["Practice_Name"] = merged["Practice_Name_c"].combine_first(merged["Practice_Name_p"])
    merged = merged.drop(columns=["Practice_Name_c", "Practice_Name_p"])

    # Merge with Samples
    final = pd.merge(merged, s_agg, on="Practice_ID", how="outer", suffixes=("", "_s"))
    
    # Combine Name again (in case practice exists in Samples but not in Claims/Payments)
    final["Practice_Name"] = final["Practice_Name"].combine_first(final["Practice_Name_s"])
    final = final.drop(columns=["Practice_Name_s"])

    # Fill NaNs
    num_cols = ["Number_of_Claims", "Total_Claim_Value", 
                "Number_of_Payments", "Total_Payment_Value", sample_col_name]
    
    # Ensure columns exist
    for col in num_cols:
        if col not in final.columns:
            final[col] = 0
            
    final[num_cols] = final[num_cols].fillna(0)

    # Calculate Payment Rate
    final["Payment_Rate"] = (
        final["Total_Payment_Value"] / final["Total_Claim_Value"].replace(0, pd.NA)
    ).fillna(0)

    # Reorder
    final = final[["Practice_ID", "Practice_Name", sample_col_name, 
                   "Number_of_Claims", "Total_Claim_Value", 
                   "Number_of_Payments", "Total_Payment_Value", "Payment_Rate"]]
    
    return final

# --- 3. Helper Function: Split id and name for Practice ---
# From File 1 / File 2
def split_id_name(value):
    if pd.isna(value):
        return (None, None)
    # Split on dash with optional spaces around it
    parts = re.split(r"\s*-\s*", str(value), maxsplit=1)
    if len(parts) == 2:
        return parts[0].strip(), parts[1].strip()
    else:
        return parts[0].strip(), None

# --- 4. Helper Function: Generate Excel with Formatting and Charts (Adapted from File 1) ---
def to_excel_with_viz(df: pd.DataFrame, sheet_name: str, payment_col: str, claim_col: str):
    """Generates an Excel file with specific formatting and charts using xlsxwriter."""
    output = BytesIO()
    
    # Convert Payment Rate to percentage format before writing to excel
    excel_df = df.copy()
    excel_df["Payment_Rate"] = excel_df["Payment_Rate"] * 100 
    
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        excel_df.to_excel(writer, index=False, sheet_name=sheet_name)
        workbook = writer.book
        worksheet = writer.sheets[sheet_name]

        # Define Formats
        header_format = workbook.add_format({"bold": True, "bg_color": "#D7E4BC", "border": 1})
        
        # Currency format with 2 decimal places
        currency_format = workbook.add_format({"num_format": "$#,##0.00", "border": 1})
        # Number format (for counts/samples/ID)
        num_format = workbook.add_format({"num_format": "#,##0", "border": 1})
        # Percentage format
        percent_format = workbook.add_format({"num_format": "0.00\%", "border": 1})
        # Text format
        text_format = workbook.add_format({"border": 1})

        # Apply Header Formatting
        for col_num, value in enumerate(excel_df.columns.values):
            worksheet.write(0, col_num, value, header_format)

        # Apply Column Formatting and Set Widths
        for i, col in enumerate(excel_df.columns):
            if col == "Practice_Name":
                 worksheet.set_column(i, i, 30, text_format)
            elif col == "Practice_ID":
                worksheet.set_column(i, i, 15, num_format)
            elif "Value" in col: # Total_Claim_Value, Total_Payment_Value
                worksheet.set_column(i, i, 20, currency_format)
            elif "Number_of" in col or "Samples" in col:
                worksheet.set_column(i, i, 18, num_format)
            elif col == "Payment_Rate":
                worksheet.set_column(i, i, 15, percent_format)
            else:
                 worksheet.set_column(i, i, 15, text_format)

        # --- Bar chart: Top 10 by Total_Payment_Value ---
        chart1 = workbook.add_chart({"type": "column"})
        
        # Sort and get top 10 for the chart data source
        top10_df = excel_df.sort_values(payment_col, ascending=False).head(10)
        row_start = 1
        row_end = len(top10_df)
        
        # Find column indices dynamically
        practice_name_col = excel_df.columns.get_loc("Practice_Name")
        payment_value_col = excel_df.columns.get_loc(payment_col)
        
        if len(top10_df) > 0:
             chart1.add_series({
                "name": f"Top 10 {sheet_name} Payments",
                # Categories are Practice Names (Col B)
                "categories": [sheet_name, row_start, practice_name_col, row_end, practice_name_col],
                # Values are Payment Values (Col G for UDS/Covid)
                "values": [sheet_name, row_start, payment_value_col, row_end, payment_value_col],
                # Data labels for clarity
                "data_labels": {"value": True, "num_format": "$#,##0"}
            })
             chart1.set_title({"name": f"Top 10 Practices by {sheet_name} Payment Value"})
             chart1.set_x_axis({"name": "Practice"})
             chart1.set_y_axis({"name": "Payment Value ($)"})
             worksheet.insert_chart("J2", chart1, {"x_scale": 1.5, "y_scale": 1.5})

        # --- Pie chart: Claim Value Distribution (Overall) ---
        chart2 = workbook.add_chart({"type": "pie"})
        
        claim_value_col = excel_df.columns.get_loc(claim_col)
        
        if len(excel_df) > 0:
            chart2.add_series({
                "name": f"{sheet_name} Claim Value Distribution",
                # Categories are Practice Names (Col B)
                "categories": [sheet_name, 1, practice_name_col, len(excel_df), practice_name_col],
                # Values are Claim Values (Col E for UDS/Covid)
                "values": [sheet_name, 1, claim_value_col, len(excel_df), claim_value_col],
                "points": [
                    {"fill": {"color": "#FFC000"}},  # Yellow
                    {"fill": {"color": "#4472C4"}},  # Blue
                    {"fill": {"color": "#70AD47"}},  # Green
                    # ... add more colors if needed
                ],
                "data_labels": {"percentage": True, "leader_lines": True},
            })
            chart2.set_title({"name": f"{sheet_name} Claim Value Distribution"})
            worksheet.insert_chart("J35", chart2, {"x_scale": 1.3, "y_scale": 1.3})

    return output.getvalue()


# --- 5. Main App Logic ---
st.title("🔬 Laboratory Financial & Sample Summary App")

st.sidebar.header("Data Upload")

claims_file = st.sidebar.file_uploader("Upload Claims Excel", type=["xlsx", "xls"])
payments_file = st.sidebar.file_uploader("Upload Payments Excel", type=["xlsx", "xls"])
uds_samples = st.sidebar.file_uploader("Upload UDS Samples (txt)", type=["txt"])
covid_samples = st.sidebar.file_uploader("Upload Covid Samples (txt)", type=["txt"])

if claims_file and payments_file and uds_samples and covid_samples:
    
    st.info("Reading and processing files...")

    # A. Read Files
    try:
        claims_df = pd.read_excel(claims_file)
        payments_df = pd.read_excel(payments_file)
        uds_log_df = parse_lab_log(uds_samples)
        covid_log_df = parse_lab_log(covid_samples)
    except Exception as e:
        st.error(f"Error reading file: {e}")
        st.stop()


    # B. Pre-process Excel Data (Clean Strings & Parse IDs)
    claims_df["Referring Doctor Practice"] = claims_df["Referring Doctor Practice"].astype(str).str.strip()
    payments_df["Referring Provider Practice"] = payments_df["Referring Provider Practice"].astype(str).str.strip()

    # Determine Claim Type (Uses Accession # prefix: C, I, R for Covid group, others for UDS)
    claims_df["Claim Type"] = (
        claims_df["Accession #"].astype(str).str[0].str.upper()
            .map({"C": "COVID", "I": "Influenza", "R": "RSV"})
            .fillna("UDS")
    )

    payments_df["Claim Type"] = (
        payments_df["Accession #"].astype(str).str[0].str.upper()
            .map({"C": "COVID", "I": "Influenza", "R": "RSV"})
            .fillna("UDS")
    )

    # Parse IDs
    claims_df[["Practice_ID", "Practice_Name"]] = claims_df["Referring Doctor Practice"].apply(split_id_name).apply(pd.Series)
    payments_df[["Practice_ID", "Practice_Name"]] = payments_df["Referring Provider Practice"].apply(split_id_name).apply(pd.Series)

    # Clean IDs and drop NaNs
    for df in (claims_df, payments_df):
        df["Practice_ID"] = pd.to_numeric(df["Practice_ID"], errors="coerce")
        df["Practice_Name"] = df["Practice_Name"].str.strip()
        # Drop rows where Practice_ID couldn't be parsed
        df.dropna(subset=["Practice_ID"], inplace=True)
        # Convert to integer after dropping NaNs
        df["Practice_ID"] = df["Practice_ID"].astype(int)

    # C. Segregate Data (UDS vs Covid)
    claims_uds_raw = claims_df[claims_df["Claim Type"] == "UDS"].copy()
    payments_uds_raw = payments_df[payments_df["Claim Type"] == "UDS"].copy()

    # Covid Split (Everything NOT UDS)
    claims_covid_raw = claims_df[claims_df["Claim Type"] != "UDS"].copy()
    payments_covid_raw = payments_df[payments_df["Claim Type"] != "UDS"].copy()

    # D. Generate Summaries using the helper function
    uds_final = generate_summary(
        claims_uds_raw, 
        payments_uds_raw, 
        uds_log_df, 
        sample_col_name="UDS_Samples"
    )

    covid_final = generate_summary(
        claims_covid_raw, 
        payments_covid_raw, 
        covid_log_df, 
        sample_col_name="Covid_Samples"
    )
    
    st.success("Processing Complete. Results displayed below.")

    # E. Display Results
    tab1, tab2 = st.tabs(["UDS Summary & Dashboard", "Covid Summary & Dashboard"])

    # --- UDS Tab ---
    with tab1:
        st.header("🔬 UDS Analysis")
        st.write("### Final UDS Summary Table")
        
        # 4. Download button with Excel formatting and charts (Integration of File 1 logic)
        excel_data_uds = to_excel_with_viz(
            uds_final, 
            sheet_name="UDS_Summary", 
            payment_col="Total_Payment_Value", 
            claim_col="Total_Claim_Value"
        )
        st.download_button(
            label="Download UDS Summary Excel with Charts",
            data=excel_data_uds,
            file_name="uds_summary_with_charts.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        st.dataframe(uds_final, use_container_width=True)

        # --- Raw Data Expander ---
        with st.expander("View Raw UDS Claims/Payments Data"):
            st.write("Filtered UDS Claims", claims_uds_raw)
            st.write("Filtered UDS Payments", payments_uds_raw)
            # Add raw data download buttons if needed, keeping them as CSV for simplicity
            csv_claims_uds = claims_uds_raw.to_csv(index=False).encode("utf-8")
            st.download_button("Download UDS Claims Raw CSV", csv_claims_uds, "uds_raw_claims.csv", "text/csv")


        # --- STREAMLIT DASHBOARD LAYOUT (From File 2) ---
        st.markdown("---")
        st.header("📊 UDS Performance Dashboard")
        
        # 0. Overall Summary Metrics
        st.subheader("🌎 Overall Claims and Payments Summary")

        total_claim_value = uds_final["Total_Claim_Value"].sum()
        total_payment_value = uds_final["Total_Payment_Value"].sum()
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
            color='Metric',
            use_container_width=True
        )
        st.markdown("---")
        
        # 1. Filters (Sidebar - only show filters relevant to current tab)
        # Use st.sidebar.empty() or only show relevant filters
        
        # Streamlit doesn't easily isolate the sidebar for tabs, so we'll put the filters 
        # for both sections here, using unique keys.
        st.sidebar.markdown("---")
        st.sidebar.subheader("Filter & Sort Options for **UDS**")
        
        sort_options = {
            "Total Claim Value": "Total_Claim_Value", 
            "Total Payment Value": "Total_Payment_Value", 
            "Payment Rate": "Payment_Rate",
            "Number of Claims": "Number_of_Claims"
        }
        
        sort_label_uds = st.sidebar.selectbox(
            "Sort Practices By:",
            list(sort_options.keys()),
            index=0, key="tab1selectbox_sort"
        )
        sort_by_uds = sort_options[sort_label_uds]
        
        sorted_summary_uds = uds_final.sort_values(sort_by_uds, ascending=False)
        
        top_n_uds = st.sidebar.slider(
            "Show Top N Practices (UDS)", 
            min_value=5, max_value=max(10, len(uds_final)), value=10, key="tab1slider"
        )
        
        summary_for_viz_uds = sorted_summary_uds.head(top_n_uds)

        # Practice Specific Filter
        all_practice_names_uds = sorted_summary_uds["Practice_Name"].unique().tolist()
        practice_filter_uds = st.sidebar.multiselect(
            "Or, Select Specific Practices (UDS - Overrides Top N):",
            options=all_practice_names_uds,
            default=[], key="tab1multiselect"
        )
        
        if practice_filter_uds:
            summary_for_viz_uds = sorted_summary_uds[sorted_summary_uds["Practice_Name"].isin(practice_filter_uds)]

        
        # 2. Main Visualizations
        
        if summary_for_viz_uds.empty:
            st.warning("No data found for the selected filters.")
        else:
            # --- Visualization 1: Claims vs. Payments Value Comparison ---
            st.subheader("🏥 Claims vs. Payments Value Comparison by Practice")
            st.caption(f"Showing {len(summary_for_viz_uds)} practices, sorted by: **{sort_label_uds}**")
            
            melted_summary = summary_for_viz_uds.melt(
                id_vars=["Practice_Name"],
                value_vars=["Total_Claim_Value", "Total_Payment_Value"],
                var_name="Metric Type",
                value_name="Amount"
            )

            # Get the desired sort order for the X-axis
            x_sort_order = summary_for_viz_uds.sort_values(sort_by_uds, ascending=False)["Practice_Name"].tolist()

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
            
            # Create a column for display formatting
            rate_df = summary_for_viz_uds.copy()
            # 1. Calculate the display value (0-100)
            rate_df['Payment_Rate_Display'] = rate_df['Payment_Rate'] * 100
            
            # 2. RENAME THE DATAFRAME COLUMN *BEFORE* PASSING IT TO THE CHART
            rate_df = rate_df.rename(columns={'Payment_Rate_Display': 'Payment Rate (%)'})
            
            st.bar_chart(
                data=rate_df,
                x="Practice_Name",
                y="Payment Rate (%)",  # Use the new, renamed column name
                use_container_width=True
            )
            # st.caption("Y-axis is Payment Rate percentage.") 
            # Note: The .rename() part of the code is now removed from the st.bar_chart call.

    # --- Covid Tab ---
    with tab2:
        st.header("🦠 Covid Analysis")
        st.write("### Final Covid Summary Table")
        
        # 4. Download button with Excel formatting and charts (Integration of File 1 logic)
        excel_data_covid = to_excel_with_viz(
            covid_final, 
            sheet_name="Covid_Summary", 
            payment_col="Total_Payment_Value", 
            claim_col="Total_Claim_Value"
        )
        st.download_button(
            label="Download Covid Summary Excel with Charts",
            data=excel_data_covid,
            file_name="covid_summary_with_charts.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        st.dataframe(covid_final, use_container_width=True)

        # --- Raw Data Expander ---
        with st.expander("View Raw Covid Claims/Payments Data"):
            st.write("Filtered Covid Claims", claims_covid_raw)
            st.write("Filtered Covid Payments", payments_covid_raw)
            # Add raw data download buttons if needed, keeping them as CSV for simplicity
            csv_claims_covid = claims_covid_raw.to_csv(index=False).encode("utf-8")
            st.download_button("Download Covid Claims Raw CSV", csv_claims_covid, "covid_raw_claims.csv", "text/csv")


        # --- STREAMLIT DASHBOARD LAYOUT (From File 2) ---
        st.markdown("---")
        st.header("📊 Covid Performance Dashboard")
        
        # 0. Overall Summary Metrics
        st.subheader("🌎 Overall Claims and Payments Summary")

        total_claim_value = covid_final["Total_Claim_Value"].sum()
        total_payment_value = covid_final["Total_Payment_Value"].sum()
        overall_rate = total_payment_value / total_claim_value if total_claim_value else 0

        col1, col2, col3 = st.columns(3)

        col1.metric("Total Claim Value", f"${total_claim_value:,.2f}")
        col2.metric("Total Payment Value", f"${total_payment_value:,.2f}")
        col3.metric("Overall Payment Rate", f"{overall_rate*100:,.2f}%")

        overall_df_covid = pd.DataFrame({
            'Metric': ['Total Claim Value', 'Total Payment Value'],
            'Value': [total_claim_value, total_payment_value]
        })

        st.bar_chart(
            overall_df_covid, 
            x='Metric', 
            y='Value', 
            color='Metric',
            use_container_width=True
        )
        st.markdown("---")
        
        # 1. Filters (Sidebar - only show filters relevant to current tab)
        st.sidebar.markdown("---")
        st.sidebar.subheader("Filter & Sort Options for **COVID**")
        
        # Using unique keys for Covid filters
        sort_label_covid = st.sidebar.selectbox(
            "Sort Practices By:",
            list(sort_options.keys()),
            index=0, key="tab2selectbox_sort"
        )
        sort_by_covid = sort_options[sort_label_covid]
        
        sorted_summary_covid = covid_final.sort_values(sort_by_covid, ascending=False)
        
        top_n_covid = st.sidebar.slider(
            "Show Top N Practices (COVID)", 
            min_value=5, max_value=max(10, len(covid_final)), value=10, key="tab2slider"
        )
        
        summary_for_viz_covid = sorted_summary_covid.head(top_n_covid)

        # Practice Specific Filter
        all_practice_names_covid = sorted_summary_covid["Practice_Name"].unique().tolist()
        practice_filter_covid = st.sidebar.multiselect(
            "Or, Select Specific Practices (COVID - Overrides Top N):",
            options=all_practice_names_covid,
            default=[], key="tab2multiselect"
        )
        
        if practice_filter_covid:
            summary_for_viz_covid = sorted_summary_covid[sorted_summary_covid["Practice_Name"].isin(practice_filter_covid)]

        
        # 2. Main Visualizations
        
        if summary_for_viz_covid.empty:
            st.warning("No data found for the selected filters.")
        else:
            # --- Visualization 1: Claims vs. Payments Value Comparison ---
            st.subheader("🏥 Claims vs. Payments Value Comparison by Practice")
            st.caption(f"Showing {len(summary_for_viz_covid)} practices, sorted by: **{sort_label_covid}**")
            
            melted_summary_covid = summary_for_viz_covid.melt(
                id_vars=["Practice_Name"],
                value_vars=["Total_Claim_Value", "Total_Payment_Value"],
                var_name="Metric Type",
                value_name="Amount"
            )

            # Get the desired sort order for the X-axis
            x_sort_order_covid = summary_for_viz_covid.sort_values(sort_by_covid, ascending=False)["Practice_Name"].tolist()

            # Use Altair for explicit sorting control
            chart_covid = alt.Chart(melted_summary_covid).mark_bar().encode(
                x=alt.X('Practice_Name', sort=x_sort_order_covid, title="Practice Name"), 
                y=alt.Y('Amount', title="Value ($)"),
                color='Metric Type',
                tooltip=['Practice_Name', 'Metric Type', alt.Tooltip('Amount', format='$,.2f')],
            ).properties(
                # title="Claims vs. Payments Value by Practice"
            ).interactive() 

            st.altair_chart(chart_covid, use_container_width=True)
            
            st.markdown("---")
            
            # --- Visualization 2: Payment Rate by Practice ---
            st.subheader("📈 Payment Rate by Practice")
            
            # Create a column for display formatting
            rate_df_covid = summary_for_viz_covid.copy()
            rate_df_covid['Payment_Rate_Display'] = rate_df_covid['Payment_Rate'] * 100
            
            st.bar_chart(
                data=rate_df_covid,
                x="Practice_Name",
                y="Payment_Rate_Display",
                use_container_width=True
            )
            st.caption("Y-axis is Payment Rate percentage.")