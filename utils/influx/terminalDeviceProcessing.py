import pandas as pd
import re
import argparse
import os

# -----------------------------
# FPC extraction helpers
# -----------------------------

def extract_fpc_from_interfaces(value):
    match = re.search(r'et-(\d+)', str(value))
    if match:
        return f"FPC{match.group(1)}"
    return None

def extract_fpc_from_components(value):
    match = re.search(r'FPC(\d+)', str(value))
    if match:
        return f"FPC{match.group(1)}"
    return None

def extract_fpc_from_terminalDevice(row):
    for col in ['value', 'component', 'path', 'name']:
        match = re.search(r'FPC(\d+)', str(row.get(col)))
        if match:
            return f"FPC{match.group(1)}"
    return None

# -----------------------------
# Load CSV
# -----------------------------

def load_data(file_path, container):
    df = pd.read_csv(file_path, low_memory=False)

    # Force value to string (preserve nulls explicitly)
    df['value'] = df['value'].where(df['value'].notna(), '<NULL>').astype(str).str.strip()

    if container == "interfaces":
        df['fpc'] = df['value'].apply(extract_fpc_from_interfaces)
    elif container == "components":
        df['fpc'] = df['value'].apply(extract_fpc_from_components)
    elif container == "terminal-device":
        df['fpc'] = df.apply(extract_fpc_from_terminalDevice, axis=1)
    else:
        raise ValueError(f"Unsupported container type: {container}")

    return df

# -----------------------------
# Utilities
# -----------------------------

def get_fpc_interfaces(df, fpc_list):
    return df[df['fpc'].isin(fpc_list)]

def get_merge_status(row, steady_col, reboot_col):
    if row[steady_col] and row[reboot_col]:
        return 'both'
    elif row[steady_col]:
        return 'only_left'
    else:
        return 'only_right'

def normalize_value(value):
    return re.sub(r'\d+', '', str(value)).strip()

def get_normalized_value_counts(df, label):
    normalized = df['value'].dropna().apply(normalize_value)
    counts = normalized.value_counts().reset_index()
    counts.columns = ['normalized_value', f'{label}_count']
    return counts

def print_unique_components_per_field(df, label):
    print(f"\n🧩 Unique 'component' values per 'field' in {label}:")
    grouped = df.groupby('field')['component'].apply(lambda x: sorted(set(x.dropna()))).reset_index()
    print(grouped.to_string(index=False))

def get_unique_index_counts_per_field(df, label):
    counts = df.groupby('field')['index'].nunique().reset_index()
    counts.columns = ['field', f'{label}_index_count']
    return counts

# -----------------------------
# Main logic
# -----------------------------

def main(steady_path, reboot_path, container, fpcs=None):
    print(f"🔍 Loading data from '{steady_path}' and '{reboot_path}'...")

    if os.path.abspath(steady_path) == os.path.abspath(reboot_path):
        raise ValueError("❌ Steady and reboot files must be different")

    steady_df = load_data(steady_path, container)
    reboot_df = load_data(reboot_path, container)

    steady_label = os.path.splitext(os.path.basename(steady_path))[0].lower()
    reboot_label = os.path.splitext(os.path.basename(reboot_path))[0].lower()

    steady_col = f'file_{steady_label}'
    reboot_col = f'file_{reboot_label}'

    if fpcs:
        print(f"📌 Filtering by FPCs: {', '.join(fpcs)}")
        steady_df = get_fpc_interfaces(steady_df, fpcs)
        reboot_df = get_fpc_interfaces(reboot_df, fpcs)
        output_file = f"merged_fpc_{container}_terminal_device.xlsx"
    else:
        print("📌 No FPC filtering applied")
        output_file = f"merged_all_{container}_terminal_device.xlsx"

    # -----------------------------
    # STRICT grouping (requested)
    # -----------------------------

    group_cols = ['path', 'index', 'field', 'component', 'component_id', 'value']

    steady_unique = steady_df[group_cols].drop_duplicates()
    reboot_unique = reboot_df[group_cols].drop_duplicates()

    steady_unique[steady_col] = True
    reboot_unique[reboot_col] = True

    merged = pd.merge(
        steady_unique,
        reboot_unique,
        on=group_cols,
        how='outer'
    )

    merged[steady_col] = merged[steady_col].fillna(False)
    merged[reboot_col] = merged[reboot_col].fillna(False)

    merged['_merge'] = merged.apply(
        lambda row: get_merge_status(row, steady_col, reboot_col),
        axis=1
    )

    final_df = merged[group_cols + [steady_col, reboot_col, '_merge']]

    # -----------------------------
    # Reporting
    # -----------------------------

    steady_value_counts = get_normalized_value_counts(steady_df, steady_label)
    reboot_value_counts = get_normalized_value_counts(reboot_df, reboot_label)

    value_counts_merged = pd.merge(
        steady_value_counts,
        reboot_value_counts,
        on='normalized_value',
        how='outer'
    ).fillna(0)

    value_counts_merged[f'{steady_label}_count'] = value_counts_merged[f'{steady_label}_count'].astype(int)
    value_counts_merged[f'{reboot_label}_count'] = value_counts_merged[f'{reboot_label}_count'].astype(int)

    steady_field_index_counts = get_unique_index_counts_per_field(steady_df, steady_label)
    reboot_field_index_counts = get_unique_index_counts_per_field(reboot_df, reboot_label)

    merged_field_index_counts = pd.merge(
        steady_field_index_counts,
        reboot_field_index_counts,
        on='field',
        how='outer'
    ).fillna(0).astype({f'{steady_label}_index_count': int,
                        f'{reboot_label}_index_count': int})

    print("\n📊 Normalized value counts:")
    print(value_counts_merged.to_string(index=False))

    print("\n🔢 Unique assignment index counts per field:")
    print(merged_field_index_counts.to_string(index=False))

    print_unique_components_per_field(steady_df, steady_label)
    print_unique_components_per_field(reboot_df, reboot_label)

    # -----------------------------
    # Excel output (single writer)
    # -----------------------------

    with pd.ExcelWriter(output_file, engine='xlsxwriter') as writer:
        final_df.to_excel(writer, sheet_name='MergedComparison', index=False)
        value_counts_merged.to_excel(writer, sheet_name='ValueCounts', index=False)
        merged_field_index_counts.to_excel(writer, sheet_name='FieldIndexCounts', index=False)

    print(f"\n✅ Merged comparison saved to '{output_file}'")

# -----------------------------
# CLI
# -----------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Compare steady vs reboot CSVs with strict value-based grouping"
    )
    parser.add_argument('steady_csv', help='Steady-state CSV file')
    parser.add_argument('reboot_csv', help='Post-reboot CSV file')
    parser.add_argument('--container', required=True, help='Container name (e.g., terminal-device)')
    parser.add_argument('--fpcs', nargs='+', help='Optional FPC filter (e.g., FPC6 FPC7)')
    args = parser.parse_args()

    main(args.steady_csv, args.reboot_csv, args.container, args.fpcs)

