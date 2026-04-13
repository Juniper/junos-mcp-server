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
    """Load CSV with delimiter auto-detection and extract FPC."""
    with open(file_path, 'r', encoding='utf-8') as f:
        sample = f.read(4096)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=[',', '\t'])
            sep = dialect.delimiter
        except csv.Error:
            sep = ','  # fallback

    df = pd.read_csv(file_path, sep=sep, low_memory=False)
    df['fpc'] = df['name'].apply(extract_fpc)
    df['value'] = df['value'].fillna(pd.NA)
    return df


def is_numeric_field(field):
    """Determine if a field should be treated as numeric."""
    numeric_keywords = ['_pkts', '_discards', '_errors', '_octets']
    return any(keyword in str(field) for keyword in numeric_keywords)


def split_numeric_non_numeric(df):
    df_numeric = df[df['field'].apply(is_numeric_field)].copy()
    df_non_numeric = df[~df['field'].apply(is_numeric_field)].copy()
    return df_numeric, df_non_numeric


def get_fpc_interfaces(df, fpc_list):
    """Filter DataFrame by FPC list (case-insensitive)."""
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
    """Count unique normalized interface names."""
    unique_names = df['name'].dropna().unique()
    normalized_names = [normalize_name(name) for name in unique_names]
    name_counts = pd.Series(normalized_names).value_counts().reset_index()
    name_counts.columns = ['normalized_name', f'{label}_count']
    return name_counts


def print_unique_components_per_field(df, label=""):
    print(f"\n🧩 Unique 'component' values per 'field' in {label}:")
    grouped = df.groupby('field')['component'].apply(lambda x: sorted(set(x.dropna())))
    result_df = grouped.reset_index()
    print(result_df.to_string(index=False))


def get_unique_name_counts_per_field(df, label):
    """Count unique interface names per field."""
    counts = df.groupby('field')['name'].nunique().reset_index()
    counts.columns = ['field', f'{label}_name_count']
    return counts


def ensure_numeric_value(val):
    """Convert to float if numeric, else NA."""
    try:
        return float(val)
    except (ValueError, TypeError):
        return pd.NA


def main(steady_path, reboot_path, fpcs=None):
    print(f"🔍 Loading data from '{steady_path}' and '{reboot_path}'...")
    log_memory_usage("Start of script")

    steady_df = load_data(steady_path)
    reboot_df = load_data(reboot_path)
    log_memory_usage("After CSV load")

    steady_label = os.path.splitext(os.path.basename(steady_path))[0].lower()
    reboot_label = os.path.splitext(os.path.basename(reboot_path))[0].lower()

    if fpcs:
        print(f"📌 Using specified FPCs: {', '.join(fpcs)}")
        steady_df = get_fpc_interfaces(steady_df, fpcs)
        reboot_df = get_fpc_interfaces(reboot_df, fpcs)
        output_file = "merged_fpc_interfaces_comparison.xlsx"
    else:
        print("📌 No FPC filter used")
        output_file = "merged_all_interfaces_comparison.xlsx"

    log_memory_usage("After FPC filtering")

    # --- Split numeric and non-numeric ---
    steady_num, steady_nonnum = split_numeric_non_numeric(steady_df)
    reboot_num, reboot_nonnum = split_numeric_non_numeric(reboot_df)
    log_memory_usage("After splitting numeric/non-numeric")

    # --- Non-numeric processing ---
    group_cols_nonnum = ['path', 'name', 'field', 'value', 'component', 'component_id']
    steady_nonnum_unique = steady_nonnum[group_cols_nonnum].drop_duplicates()
    reboot_nonnum_unique = reboot_nonnum[group_cols_nonnum].drop_duplicates()

    steady_nonnum_unique[f'file_{steady_label}'] = True
    reboot_nonnum_unique[f'file_{reboot_label}'] = True

    merged_nonnum = pd.merge(
        steady_nonnum_unique,
        reboot_nonnum_unique,
        on=group_cols_nonnum,
        how='outer'
    )

    merged_nonnum[f'file_{steady_label}'] = merged_nonnum[f'file_{steady_label}'].fillna(False)
    merged_nonnum[f'file_{reboot_label}'] = merged_nonnum[f'file_{reboot_label}'].fillna(False)
    merged_nonnum['_merge'] = merged_nonnum.apply(
        lambda row: get_merge_status(row, f'file_{steady_label}', f'file_{reboot_label}'), axis=1
    )

    # --- Numeric processing ---
    steady_num['value'] = steady_num['value'].apply(ensure_numeric_value)
    reboot_num['value'] = reboot_num['value'].apply(ensure_numeric_value)

    group_cols_num = ['path', 'name', 'field', 'component', 'component_id']
    steady_num_grouped = steady_num[group_cols_num].drop_duplicates()
    reboot_num_grouped = reboot_num[group_cols_num].drop_duplicates()

    steady_num_grouped[f'file_{steady_label}'] = True
    reboot_num_grouped[f'file_{reboot_label}'] = True

    merged_num = pd.merge(
        steady_num_grouped,
        reboot_num_grouped,
        on=group_cols_num,
        how='outer'
    )

    merged_num[f'file_{steady_label}'] = merged_num[f'file_{steady_label}'].fillna(False)
    merged_num[f'file_{reboot_label}'] = merged_num[f'file_{reboot_label}'].fillna(False)
    merged_num['_merge'] = merged_num.apply(
        lambda row: get_merge_status(row, f'file_{steady_label}', f'file_{reboot_label}'), axis=1
    )
    merged_num['value'] = pd.NA
    group_cols_ordered = ['path', 'name', 'field', 'value', 'component', 'component_id']
    merged_num = merged_num[group_cols_ordered + [f'file_{steady_label}', f'file_{reboot_label}', '_merge']]

    log_memory_usage("After merging numeric/non-numeric")

    # --- Final combined DataFrame ---
    final_df = pd.concat([merged_nonnum, merged_num], ignore_index=True)
    log_memory_usage("After combining final DataFrame")

    # --- Normalized name counts ---
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

    print("\n📊 Normalized unique name counts (side-by-side):")
    print(name_counts_merged.to_string(index=False))

    # --- Unique name counts per field ---
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

    # --- Print merged_df preview and components ---
    print("\n📝 Final merged DataFrame combining numeric and non-numeric grouped data:")
    print(final_df.head(30).to_string(index=False))

    print_unique_components_per_field(steady_df, steady_label)
    print_unique_components_per_field(reboot_df, reboot_label)

    # --- Write Excel ---
    with pd.ExcelWriter(output_file, engine='xlsxwriter') as writer:
        final_df.to_excel(writer, sheet_name='MergedComparison', index=False)
        name_counts_merged.to_excel(writer, sheet_name='InterfaceNameCounts', index=False)

        steady_field_components = steady_df.groupby('field')['component']\
            .apply(lambda x: sorted(set(x.dropna()))).reset_index()
        steady_field_components.columns = ['field', f'{steady_label}_FieldComponents']

        reboot_field_components = reboot_df.groupby('field')['component']\
            .apply(lambda x: sorted(set(x.dropna()))).reset_index()
        reboot_field_components.columns = ['field', f'{reboot_label}_FieldComponents']

        merged_field_components = pd.merge(
            steady_field_components,
            reboot_field_components,
            on='field',
            how='outer'
        ).fillna('[]')

        merged_field_components.to_excel(writer, sheet_name='FieldComponents', index=False)
        merged_field_name_counts.to_excel(writer, sheet_name='FieldNameCounts', index=False)

    log_memory_usage("After writing Excel output")
    print(f"\n✅ Merged comparison saved to '{output_file}'.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Compare interfaces data before and after reboot, optionally filtered by FPCs"
    )
    parser.add_argument('steady_csv', help='CSV file path for steady state data')
    parser.add_argument('reboot_csv', help='CSV file path for post reboot data')
    parser.add_argument('--fpcs', nargs='+', help='Optional: List of FPCs like FPC14 FPC15')
    args = parser.parse_args()

    main(args.steady_csv, args.reboot_csv, args.fpcs)

