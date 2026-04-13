#!/usr/bin/env python3

import pandas as pd
import re
import argparse
import os
#pd.set_option('future.no_silent_downcasting', True)

def extract_fpc_from_interfaces(name):
    match = re.search(r'et-(\d+)', str(name))
    if match:
        return f"FPC{match.group(1)}"
    return None

def extract_fpc_from_components(name):
    match = re.search(r'FPC(\d+)', str(name))
    if match:
        return f"FPC{match.group(1)}"
    return None

def extractFPC(name):
    #match = re.search(r'', str(name))
    #if match:
    #    return f"FPC{match.group(1)}"
    return None

def load_data(file_path, container):
    # Select extract function based on container
    if container == "interfaces":
        extract_fpc = extract_fpc_from_interfaces
    elif container == "components":
        extract_fpc = extract_fpc_from_components
    #elif container == "qos":
    #    extract_fpc = extractFPC
    #elif container == "lacp":
    #    extract_fpc = extractFPC
    else:
        raise ValueError(f"Unsupported container type: {container}")

    df = pd.read_csv(file_path, low_memory=False)
    df['fpc'] = df['name'].apply(extract_fpc)
    if '_value' in df.columns and 'value' not in df.columns:
        df.rename(columns={'_value': 'value'}, inplace=True)
    df['value'] = df['value'].fillna(pd.NA)
    return df

def is_numeric_field(field):
    numeric_keywords = ['_pkts', '_discards', '_errors', '_octets']
    return any(keyword in str(field) for keyword in numeric_keywords)

def split_numeric_non_numeric(df):
    df_numeric = df[df['field'].apply(is_numeric_field)].copy()
    df_non_numeric = df[~df['field'].apply(is_numeric_field)].copy()
    return df_numeric, df_non_numeric

def get_fpc_interfaces(df, fpc_list):
    return df[df['fpc'].isin(fpc_list)]

def get_merge_status(row, steady_col, reboot_col):
    if row[steady_col] and row[reboot_col]:
        return 'both'
    elif row[steady_col]:
        return 'only_left'
    else:
        return 'only_right'

def normalize_name(name):
    # Remove all digits and trailing hyphen numbers
    return re.sub(r'[\d\-]+', '', str(name))


def print_name_group_counts(df):
    print("\n📊 Grouped count of entries by normalized 'name' (ignoring digits):")

    df = df.copy()
    df['normalized_name'] = df['name'].apply(normalize_name)

    grouped_counts = df['normalized_name'].value_counts().reset_index()
    grouped_counts.columns = ['normalized_name', 'count']

    print(grouped_counts.to_string(index=False))

def get_normalized_name_counts(df, label=""):
    unique_names = df['name'].dropna().unique()
    normalized_names = [normalize_name(name) for name in unique_names]

    name_counts = pd.Series(normalized_names).value_counts().reset_index()
    #name_counts.columns = ['normalized_name', 'count']
    name_counts.columns = ['normalized_name', f'{label}_count']
    return name_counts

def print_unique_components_per_field(df, label=""):
    print(f"\n🧩 Unique 'component' values per 'field' in {label}:")
    
    grouped = df.groupby('field')['component'].apply(lambda x: sorted(set(x.dropna())))
    result_df = grouped.reset_index()
    
    # Pretty-print the result
    print(result_df.to_string(index=False))

def get_unique_name_counts_per_field(df, label):
    """
    Returns a DataFrame with count of unique interface names per field.
    """
    counts = df.groupby('field')['name'].nunique().reset_index()
    counts.columns = ['field', f'{label}_name_count']
    return counts

def main(steady_path, reboot_path, container, fpcs=None):
    print(f"🔍 Loading data from '{steady_path}' and '{reboot_path}'...")

    if os.path.abspath(steady_path) == os.path.abspath(reboot_path):
        raise ValueError("❌ Both steady and reboot paths point to the same file. Please provide two different files.")

    steady_df = load_data(steady_path, container)
    reboot_df = load_data(reboot_path, container)

    steady_label = os.path.splitext(os.path.basename(steady_path))[0]
    reboot_label = os.path.splitext(os.path.basename(reboot_path))[0]

    steady_col = f'file_{steady_label}'
    reboot_col = f'file_{reboot_label}'

    if fpcs is not None:
        print(f"📌 Using specified FPCs: {', '.join(fpcs)}")
        steady_df = get_fpc_interfaces(steady_df, fpcs)
        reboot_df = get_fpc_interfaces(reboot_df, fpcs)
        output_file = "merged_fpc_" + container + "_comparison.xlsx"

    else:
        output_file = "merged_all_" + container + "_comparison.xlsx"
        print("📌 No FPCs specified — comparing all data across both files.")

    # Step 1: Split numeric and non-numeric by field
    steady_num, steady_nonnum = split_numeric_non_numeric(steady_df)
    reboot_num, reboot_nonnum = split_numeric_non_numeric(reboot_df)

    ### --- Non-Numeric Processing --- ###
    group_cols_nonnum = ['path', 'name', 'field', 'value', 'component', 'component_id']
    steady_nonnum_unique = steady_nonnum[group_cols_nonnum].drop_duplicates()
    reboot_nonnum_unique = reboot_nonnum[group_cols_nonnum].drop_duplicates()

    steady_nonnum_unique[steady_col] = True
    reboot_nonnum_unique[reboot_col] = True

    merged_nonnum = pd.merge(
        steady_nonnum_unique,
        reboot_nonnum_unique,
        on=group_cols_nonnum,
        how='outer'
    )

    merged_nonnum[steady_col] = merged_nonnum[steady_col].fillna(False).infer_objects(copy=False)
    merged_nonnum[reboot_col] = merged_nonnum[reboot_col].fillna(False).infer_objects(copy=False)
    merged_nonnum['_merge'] = merged_nonnum.apply(lambda row: get_merge_status(row, steady_col, reboot_col), axis=1)
    merged_nonnum = merged_nonnum[group_cols_nonnum + [steady_col, reboot_col, '_merge']]

    ### --- Numeric Processing (Presence-based only) --- ###
    # Fill missing or invalid values with NaN (ensure 'value' exists even if missing)
    def ensure_numeric_value(val):
        try:
            return float(val)
        except (ValueError, TypeError):
            return pd.NA

    steady_num['value'] = steady_num['value'].apply(ensure_numeric_value)
    reboot_num['value'] = reboot_num['value'].apply(ensure_numeric_value)

    # Group only by identity — ignore 'value' itself for comparison
    group_cols_num = ['path', 'name', 'field', 'component', 'component_id']
    steady_num_grouped = steady_num[group_cols_num].drop_duplicates()
    reboot_num_grouped = reboot_num[group_cols_num].drop_duplicates()

    steady_num_grouped[steady_col] = True
    reboot_num_grouped[reboot_col] = True

    merged_num = pd.merge(
        steady_num_grouped,
        reboot_num_grouped,
        on=group_cols_num,
        how='outer'
    )

    merged_num[steady_col] = merged_num[steady_col].fillna(False).infer_objects(copy=False)
    merged_num[reboot_col] = merged_num[reboot_col].fillna(False).infer_objects(copy=False)
    merged_num['_merge'] = merged_num.apply(lambda row: get_merge_status(row, steady_col, reboot_col), axis=1)

    # Add empty value column for structure match
    merged_num['value'] = pd.NA
    group_cols_ordered = ['path', 'name', 'field', 'value', 'component', 'component_id']
    merged_num = merged_num[group_cols_ordered + [steady_col, reboot_col, '_merge']]

    ### --- Final Combined Output --- ###
    final_df = pd.concat([merged_nonnum, merged_num], ignore_index=True)
    #print_name_group_counts(final_df)
    #print_normalized_name_counts(steady_df)
    #print_normalized_name_counts(reboot_df)

    steady_label = os.path.splitext(os.path.basename(steady_path))[0].lower()
    reboot_label = os.path.splitext(os.path.basename(reboot_path))[0].lower()

    # Get tabular normalized name counts
    steady_name_counts = get_normalized_name_counts(steady_df, steady_label)
    reboot_name_counts = get_normalized_name_counts(reboot_df, reboot_label)

    steady_field_name_counts = get_unique_name_counts_per_field(steady_df, steady_label)
    reboot_field_name_counts = get_unique_name_counts_per_field(reboot_df, reboot_label)

    merged_field_name_counts = pd.merge(
        steady_field_name_counts,
        reboot_field_name_counts,
        on='field',
        how='outer'
    ).fillna(0)

    merged_field_name_counts[f'{steady_label}_name_count'] = merged_field_name_counts[f'{steady_label}_name_count'].astype(int)
    merged_field_name_counts[f'{reboot_label}_name_count'] = merged_field_name_counts[f'{reboot_label}_name_count'].astype(int)

    print("\n🔢 Unique interface name counts per field:")
    print(merged_field_name_counts.to_string(index=False))

    # Merge side-by-side for tabular display
    name_counts_merged = pd.merge(
        steady_name_counts,
        reboot_name_counts,
        on='normalized_name',
        how='outer'
    ).fillna(0)

    # Convert counts to int
    #name_counts_merged['STEADY_count'] = name_counts_merged['STEADY_count'].astype(int)
    #name_counts_merged['REBOOT_count'] = name_counts_merged['REBOOT_count'].astype(int)

    name_counts_merged[f'{steady_label}_count'] = name_counts_merged[f'{steady_label}_count'].astype(int)
    name_counts_merged[f'{reboot_label}_count'] = name_counts_merged[f'{reboot_label}_count'].astype(int)

    # Print as table
    print("\n📊 Normalized unique name counts (side-by-side):")
    print(name_counts_merged.to_string(index=False))

    print("\n📝 Final merged DataFrame combining numeric and non-numeric grouped data:")
    print(final_df.head(30).to_string(index=False))

    print_unique_components_per_field(steady_df, steady_label)
    print_unique_components_per_field(reboot_df, reboot_label)

    #output_file = "merged_interfaces_comparison.xlsx"
    with pd.ExcelWriter(output_file, engine='xlsxwriter') as writer:
        final_df.to_excel(writer, sheet_name='MergedComparison', index=False)

    with pd.ExcelWriter(output_file, engine='xlsxwriter') as writer:
        final_df.to_excel(writer, sheet_name='MergedComparison', index=False)
        name_counts_merged.to_excel(writer, sheet_name='InterfaceNameCounts', index=False)

    # Also write component values per field (STEADY & REBOOT)
    steady_field_components = steady_df.groupby('field')['component'].apply(lambda x: sorted(set(x.dropna()))).reset_index()
    steady_field_components.columns = ['field', f'{steady_label}_FieldComponents']

    reboot_field_components = reboot_df.groupby('field')['component'].apply(lambda x: sorted(set(x.dropna()))).reset_index()
    reboot_field_components.columns = ['field', f'{reboot_label}_FieldComponents']

    # Merge them for side-by-side comparison
    merged_field_components = pd.merge(
        steady_field_components,
        reboot_field_components,
        on='field',
        how='outer'
    ).fillna('[]')

    # Save to Excel (along with previous sheets)
    with pd.ExcelWriter(output_file, engine='xlsxwriter') as writer:
        final_df.to_excel(writer, sheet_name='MergedComparison', index=False)
        name_counts_merged.to_excel(writer, sheet_name='InterfaceNameCounts', index=False)
        merged_field_components.to_excel(writer, sheet_name='FieldComponents', index=False)
        merged_field_name_counts.to_excel(writer, sheet_name='FieldNameCounts', index=False)

    print(f"\n✅ Merged comparison saved to '{output_file}'.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Compare interfaces data before and after reboot, optionally filtered by FPCs")
    parser.add_argument('steady_csv', help='CSV file path for steady state data')
    parser.add_argument('reboot_csv', help='CSV file path for post reboot data')
    parser.add_argument('--container', required=True, help='Required: Container name (e.g., interfaces)')
    parser.add_argument('--fpcs', nargs='+', help='Optional: List of FPCs like FPC14 FPC15. If not provided, all data is compared.')
    args = parser.parse_args()
    main(args.steady_csv, args.reboot_csv, args.container, args.fpcs)

