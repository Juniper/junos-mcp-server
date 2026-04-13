#!/usr/bin/env python3

import pandas as pd
import re
import argparse
import os
import csv
import psutil  # ✅ for memory monitoring

#pd.set_option('future.no_silent_downcasting', True)


def log_memory_usage(stage):
    """Logs current memory use and total system memory."""
    process = psutil.Process(os.getpid())
    mem_used = process.memory_info().rss / (1024 ** 3)
    total_mem = psutil.virtual_memory().total / (1024 ** 3)
    print(f"[MEMORY] {stage}: {mem_used:.2f} GB used (of {total_mem:.2f} GB total)")


def extract_fpc(name):
    match = re.search(r'et-(\d+)', str(name))
    if match:
        return f"FPC{match.group(1)}"
    return None

def load_data(file_path):
    # Try to auto-detect delimiter
    with open(file_path, 'r', encoding='utf-8') as f:
        sample = f.read(4096)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=[',', '\t'])
            sep = dialect.delimiter
        except csv.Error:
            sep = ','  # fallback if detection fails

    df = pd.read_csv(file_path, sep=sep, low_memory=False)
    df['fpc'] = df['interface'].apply(extract_fpc)
    df['value'] = df['value'].fillna(pd.NA)
    return df


def is_numeric_field(field):
    numeric_keywords = ['_pkts', '_discards', '_errors', '_octets']
    return any(keyword in str(field) for keyword in numeric_keywords)


def split_numeric_non_numeric(df):
    df_numeric = df[df['field'].apply(is_numeric_field)].copy()
    df_non_numeric = df[~df['field'].apply(is_numeric_field)].copy()
    return df_numeric, df_non_numeric


def et_fpc_interfaces(df, fpc_list):
    return df[df['fpc'].isin(fpc_list)]

def get_fpc_interfaces(df, fpc_list):
    fpc_list_lower = [f.lower() for f in fpc_list]
    return df[df['fpc'].str.lower().isin(fpc_list_lower)]

def get_merge_status(row, steady_col, reboot_col):
    if row[steady_col] and row[reboot_col]:
        return 'both'
    elif row[steady_col]:
        return 'only_left'
    else:
        return 'only_right'


def normalize_name(name):
    return re.sub(r'[\d-]+', '', str(name))


def get_normalized_name_counts(df, label=""):
    unique_names = df['interface'].dropna().unique()
    normalized_names = [normalize_name(name) for name in unique_names]

    name_counts = pd.Series(normalized_names).value_counts().reset_index()
    name_counts.columns = ['normalized_name', f'{label}_count']
    return name_counts


def print_unique_components_per_field(df, label=""):
    print(f"\n🧩 Unique 'component' values per 'field' in {label}:")
    grouped = df.groupby('field')['component'].apply(lambda x: sorted(set(x.dropna())))
    result_df = grouped.reset_index()
    print(result_df.to_string(index=False))

def get_unique_interface_counts_per_field(df, label):
    """
    Returns a DataFrame with count of unique interface names per field.
    """
    counts = df.groupby('field')['interface'].nunique().reset_index()
    counts.columns = ['field', f'{label}_name_count']
    return counts

def main(steady_path, reboot_path, fpcs=None):
    print(f"🔍 Loading data from '{steady_path}' and '{reboot_path}'...")
    log_memory_usage("Start of script")

    steady_df = load_data(steady_path)
    log_memory_usage("After loading steady CSV")

    reboot_df = load_data(reboot_path)
    log_memory_usage("After loading reboot CSV")

    steady_label = os.path.splitext(os.path.basename(steady_path))[0]
    reboot_label = os.path.splitext(os.path.basename(reboot_path))[0]

    steady_col = f'file_{steady_label}'
    reboot_col = f'file_{reboot_label}'

    if fpcs is not None:
        print(f"📌 Using specified FPCs: {', '.join(fpcs)}")
        steady_df = get_fpc_interfaces(steady_df, fpcs)
        reboot_df = get_fpc_interfaces(reboot_df, fpcs)
        output_file = "merged_fpc_lacp_comparison.xlsx"
    else:
        output_file = "merged_all_lacp_comparison.xlsx"
        print("📌 No FPCs specified — comparing all data across both files.")

    log_memory_usage("After FPC filtering")

    # --- Split numeric and non-numeric ---
    steady_num, steady_nonnum = split_numeric_non_numeric(steady_df)
    reboot_num, reboot_nonnum = split_numeric_non_numeric(reboot_df)
    log_memory_usage("After splitting numeric/non-numeric")

    # --- Non-Numeric Processing ---
    group_cols_nonnum = ['path', 'interface', 'field', 'value', 'component', 'component_id']
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

    # --- Numeric Processing ---
    def ensure_numeric_value(val):
        try:
            return float(val)
        except (ValueError, TypeError):
            return pd.NA

    steady_num['value'] = steady_num['value'].apply(ensure_numeric_value)
    reboot_num['value'] = reboot_num['value'].apply(ensure_numeric_value)

    group_cols_num = ['path', 'interface', 'field', 'component', 'component_id']
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
    merged_num['value'] = pd.NA

    group_cols_ordered = ['path', 'interface', 'field', 'value', 'component', 'component_id']
    merged_num = merged_num[group_cols_ordered + [steady_col, reboot_col, '_merge']]

    log_memory_usage("After merging numeric/non-numeric")

    # --- Final Combined Output ---
    final_df = pd.concat([merged_nonnum, merged_num], ignore_index=True)
    log_memory_usage("After combining final DataFrame")

    steady_label = steady_label.lower()
    reboot_label = reboot_label.lower()

    steady_name_counts = get_normalized_name_counts(steady_df, steady_label)
    reboot_name_counts = get_normalized_name_counts(reboot_df, reboot_label)

    name_counts_merged = pd.merge(
        steady_name_counts,
        reboot_name_counts,
        on='normalized_name',
        how='outer'
    ).fillna(0)

    name_counts_merged[f'{steady_label}_count'] = name_counts_merged[f'{steady_label}_count'].astype(int)
    name_counts_merged[f'{reboot_label}_count'] = name_counts_merged[f'{reboot_label}_count'].astype(int)

    steady_field_interface_counts = get_unique_interface_counts_per_field(steady_df, steady_label)
    reboot_field_interface_counts = get_unique_interface_counts_per_field(reboot_df, reboot_label)

    print("\n📊 Normalized unique name counts (side-by-side):")
    print(name_counts_merged.to_string(index=False))

    print("\n📝 Final merged DataFrame combining numeric and non-numeric grouped data:")
    print(final_df.head(30).to_string(index=False))

    print_unique_components_per_field(steady_df, steady_label)
    print_unique_components_per_field(reboot_df, reboot_label)

    merged_field_interface_counts = pd.merge(
        steady_field_interface_counts,
        reboot_field_interface_counts,
        on='field',
        how='outer'
    ).fillna(0)

    merged_field_interface_counts[f'{steady_label}_name_count'] = merged_field_interface_counts[f'{steady_label}_name_count'].astype(int)
    merged_field_interface_counts[f'{reboot_label}_name_count'] = merged_field_interface_counts[f'{reboot_label}_name_count'].astype(int)


    with pd.ExcelWriter(output_file, engine='xlsxwriter') as writer:
        final_df.to_excel(writer, sheet_name='MergedComparison', index=False)
        name_counts_merged.to_excel(writer, sheet_name='InterfaceNameCounts', index=False)

        steady_field_components = steady_df.groupby('field')['component'].apply(lambda x: sorted(set(x.dropna()))).reset_index()
        steady_field_components.columns = ['field', f'{steady_label}_FieldComponents']

        reboot_field_components = reboot_df.groupby('field')['component'].apply(lambda x: sorted(set(x.dropna()))).reset_index()
        reboot_field_components.columns = ['field', f'{reboot_label}_FieldComponents']

        merged_field_components = pd.merge(
            steady_field_components,
            reboot_field_components,
            on='field',
            how='outer'
        ).fillna('[]')

        merged_field_components.to_excel(writer, sheet_name='FieldComponents', index=False)
        merged_field_interface_counts.to_excel(writer, sheet_name='FieldInterfaceCounts', index=False)
    log_memory_usage("After writing Excel output")
    print(f"\n✅ Merged comparison saved to '{output_file}'.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Compare interfaces data before and after reboot, optionally filtered by FPCs"
    )
    parser.add_argument('steady_csv', help='CSV file path for steady state data')
    parser.add_argument('reboot_csv', help='CSV file path for post reboot data')
    parser.add_argument('--fpcs', nargs='+', help='Optional: List of FPCs like FPC14 FPC15. If not provided, all data is compared.')
    args = parser.parse_args()

    main(args.steady_csv, args.reboot_csv, args.fpcs)

