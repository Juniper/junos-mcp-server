import argparse
import yaml
import os, sys
import pandas as pd
import numpy as np
from influxdb_client import InfluxDBClient
import warnings
from influxdb_client.client.warnings import MissingPivotFunction

try:
    warnings.simplefilter("ignore", MissingPivotFunction)
except Exception:
    pass

suffix_map = {
    '_delays_ms': 'delays_ms',
    '_received_time': 'received_time',
    '_recvd_time': 'received_time'
}

class Logger(object):
    def __init__(self, filename):
        self.terminal = sys.stdout  # keep printing to console
        self.log = open(filename, "w", encoding='utf-8')
        #self.buffer = ''  # To collect partial writes until newline

    def write(self, message):
        self.terminal.write(message)  # print to console
        self.log.write(message)        # write to file

        #self.buffer += message
        #if '\n' in self.buffer:
        #    # Split by lines
        #    lines = self.buffer.split('\n')
        #    for line in lines[:-1]:  # all complete lines
        #        if line.strip():  # only if not empty line
        #            underline = '-' * len(line) + '\n'
        #            self.terminal.write(underline)
        #            self.log.write(underline)
        #    # Keep the last partial line (after last \n)
        #    self.buffer = lines[-1]

    def flush(self):
        self.terminal.flush()
        self.log.flush()

def load_config(config_path):
    with open(config_path, 'r') as f:
        return yaml.safe_load(f)

def run_flux_query(url, token, org, query):
    client = InfluxDBClient(url=url, token=token, org=org, timeout=900000)
    tables = client.query_api().query_data_frame(query, org=org)
    if isinstance(tables, list):
        df = pd.concat(tables, ignore_index=True)
    else:
        df = tables
    return df

def load_clean_influx_csv(filename, drop_columns=None):
    drop_columns = drop_columns or []
    with open(filename, 'r') as f:
        lines = f.readlines()
    lines = [line for line in lines if not line.startswith('#')]
    if not lines:
        return pd.DataFrame()
    header_line = lines[0].strip()
    data_lines = [line for line in lines if line.strip() != header_line]
    csv_content = '\n'.join([header_line] + data_lines)
    from io import StringIO
    df = pd.read_csv(StringIO(csv_content), dtype=str)
    drop_cols_existing = [col for col in drop_columns if col in df.columns]
    if drop_cols_existing:
        df = df.drop(columns=drop_cols_existing)
    return df

def get_base_and_suffix(field):
    for suffix in suffix_map:
        if field.endswith(suffix):
            base = field[:-len(suffix)]
            return base, suffix_map[suffix]
    return field, None

def PRocess_suffix_fields(df):
    df['base_field'] = None
    df['suffix_col'] = None

    for idx, row in df.iterrows():
        base, suffix_col = get_base_and_suffix(row['_field'])
        df.at[idx, 'base_field'] = base
        df.at[idx, 'suffix_col'] = suffix_col

    base_rows = df[df['suffix_col'].isna()].copy()
    suffix_rows = df[df['suffix_col'].notna()].copy()

    if suffix_rows.empty:
        return base_rows.rename(columns={'base_field': '_field'})

    pivoted = suffix_rows.pivot_table(
        index=['_measurement', 'path', 'name', 'base_field', '_time'],
        columns='suffix_col',
        values='_value',
        aggfunc='first'
    ).reset_index()

    merged = pd.merge(
        base_rows,
        pivoted,
        left_on=['_measurement', 'path', 'name', '_field', '_time'],
        right_on=['_measurement', 'path', 'name', 'base_field', '_time'],
        how='left'
    )

    merged = merged.drop(columns=['base_field_y', 'suffix_col'])
    merged = merged.rename(columns={'base_field_x': '_field'})

    return merged

def process_suffix_fields(df):
    if df.empty:
        return df
    df['_field'] = df['_field'].astype(str).str.strip()
    # Above 3 lines added on 02/25/2026
    df['base_field'] = None
    df['suffix_col'] = None

    for idx, row in df.iterrows():
        base, suffix_col = get_base_and_suffix(row['_field'])
        df.at[idx, 'base_field'] = base
        df.at[idx, 'suffix_col'] = suffix_col

    base_rows = df[df['suffix_col'].isna()].copy()
    suffix_rows = df[df['suffix_col'].notna()].copy()

    if suffix_rows.empty:
        return base_rows.rename(columns={'base_field': '_field'})

    # --- DYNAMIC INDEX HANDLING ---
    # If "name" column is available, include it in grouping/pivot
    index_cols = ['_measurement', 'path', 'base_field', '_time']
    merge_left = ['_measurement', 'path', '_field', '_time']
    merge_right = ['_measurement', 'path', 'base_field', '_time']

    if 'name' in suffix_rows.columns:
        index_cols.insert(2, 'name')          # for pivot
        merge_left.insert(2, 'name')          # for merge-left
        merge_right.insert(2, 'name')         # for merge-right

    # --- Pivot based on available columns ---
    pivoted = suffix_rows.pivot_table(
        index=index_cols,
        columns='suffix_col',
        values='_value',
        aggfunc='first'
    ).reset_index()

    # --- Merge base rows ---
    merged = pd.merge(
        base_rows,
        pivoted,
        left_on=merge_left,
        right_on=merge_right,
        how='left'
    )

    # Clean up helper fields
    if 'base_field_y' in merged.columns:
        merged = merged.drop(columns=['base_field_y'])
    if 'suffix_col' in merged.columns:
        merged = merged.drop(columns=['suffix_col'])

    merged = merged.rename(columns={'base_field_x': '_field'})

    return merged

def flag_duplicates(df):
    # Round producer_time to seconds for grouping
    df['producer_time'] = pd.to_datetime(df['producer_time'], errors='coerce')
    df['producer_time_rounded'] = df['producer_time'].dt.floor('s')

    # Columns to check duplicates on
    group_cols = ['path', 'name', 'field', 'value', 'component', 'component_id', 'producer_time_rounded']

    # Find all duplicates (keep=False marks all duplicates as True)
    duplicated_mask = df.duplicated(subset=group_cols, keep=False)

    # Add duplicated column with "Yes"/"No"
    df['duplicated'] = duplicated_mask.map({True: "Yes", False: "No"})

    # Drop the helper rounded column before returning
    #df.drop(columns=['producer_time_rounded'], inplace=True)
    return df

def flag_duplicates_exact_time_diff(df):
    df = df.copy()
    df['producer_time'] = pd.to_datetime(df['producer_time'], errors='coerce')

    measurement_group_map = {
        'system': ["path", "name", "field", "value", "component_id"],
        'qos': ["path", "name", "interface_id", "field", "component", "component_id"],
        'lacp': ["path", "interface", "field", "component"],
        'interfaces': ["path", "name", "field", "component"],
        'components': ["path", "name", "field", "component"],
        "terminal_device": ["path", "index", "field", "component", "value", "component_id"],
        'lldp': ["path", "index", "field", "component", "value", "component_id"],
        'components_component_controller_card': ["field", "component", "component_id", "name", "path", "value"],
        'components_component_cpu': ["field", "component", "component_id", "name", "path", "value"],
        'components_component_fabric': ["field", "component", "component_id", "name", "path", "value"],
        'components_component_fan': ["field", "component", "component_id", "name", "path", "value"],
        'components_component_integrated_circuit': ["field", "component", "component_id", "name", "path", "sub_component_id"],
        'components_component_linecard': ["field", "component", "component_id", "name", "path", "value"],
        'components_component_optical_channel': ["field", "component", "component_id", "name", "path", "value"],
        'components_component_power_supply': ["field", "component", "component_id", "name", "path", "value"],
        'components_component_properties': ["field", "component", "component_id", "name", "path", "value"],
        'components_component_state': ["field", "component", "component_id", "name", "path", "value"],
        'components_component_transceiver': ["field", "component", "component_id", "name", "path", "value", "index", "severity"],
        'network_instances_network_instance_policy_forwarding': ["field", "component", "component_id", "name", "path", "policy_id", "sequence_id", "sub_component_id", "value", "interface_id"],
        'network_instances_network_instance_protocols_protocol_bgp': ["path", "name", "field", "component", "value", "afi_name", "interface_id", "level_number", "safi_name", "neighbor_address", "peer_group_name", "identifier", "afi_safi_name"],
        'network_instances_network_instance_protocols_protocol_isis': ["path", "name", "field", "component", "value", "afi_name", "interface_id", "safi_name", "identifier","instance_number", "system_id", "id", "type", "prefix", "lsp_id", "level_number", "identifier"],
        'network_instances_network_instance_protocols_protocol_static_routes': ["path", "name", "field", "component", "component_id", "identifier", "prefix", "value", "index"],
        'network_instances_network_instance_table_connections': ["path", "name", "field", "component", "component_id", "address_family", "dst_protocol", "src_protocol", "value"],
        'network_instances_network_instance_protocols_protocol_isis_interfaces_interface_levels_level_afi_safi_af_state_metric': ["path", "name", "field", "component", "value", "afi_name", "interface_id", "level_number", "safi_name"],
        'terminal_device_logical_channels_channel_ingress': ["path", "index", "field", "component", "value", "component_id"],
        'terminal_device_logical_channels_channel_logical_channel_assignments_assignment_state': ["path", "index", "field", "component", "value", "component_id"],
        'terminal_device_logical_channels_channel_otn_state_esnr': ["path", "index", "field", "component", "value", "component_id"],
        'terminal_device_logical_channels_channel_otn_state_fec_uncorrectable_blocks': ["path", "index", "field", "component", "value", "component_id"],
        'terminal_device_logical_channels_channel_otn_state_pre_fec_ber': ["path", "index", "field", "component", "value", "component_id"],
        'terminal_device_logical_channels_channel_otn_state_q_value': ["path", "index", "field", "component", "value", "component_id"],
        'terminal_device_logical_channels_channel_state': ["path", "index", "field", "component", "value", "component_id"],
        'network_instances_network_instance_protocols_protocol_bgp_neighbors': [],
        'junos_krt_acknowledgement_state': ["path", "device", "field", "component", "value", "component_id"],
        'junos_krt_state_information': ["path", "device", "field", "component", "value", "component_id"],
        'junos_cos_forwarding_class_information': ["path", "device", "name", "field", "component", "value", "component_id"],
        'junos_system_linecard_firewall': ["path", "device", "field", "component", "value", "component_id", "name"],
        'junos_system_linecard_npu_memory': ["path", "device", "field", "component", "value", "component_id", "name"],
        'junos_system_linecard_npu_utilization': ["path", "device", "field", "component", "value", "component_id", "name"],
        'junos_system_linecard_packet_usage': ["path", "device", "field", "component", "value", "component_id", "name", "Custom1"],
        'junos_task_memory_information_task_memory_overall_report': ["path", "device", "field", "component", "value", "component_id", "name"],
    }

    all_results = []
    duplicate_id_counter = 1

    for meas, subdf in df.groupby('_measurement', group_keys=False):
        group_cols = measurement_group_map.get(
            meas, ['path', 'name', 'field', 'component', 'component_id'])
        group_cols = [c for c in group_cols if c in subdf.columns]
        subdf = subdf.sort_values(group_cols + ['producer_time'], na_position='last')

        subdf['time_diff'] = subdf.groupby(group_cols)['producer_time'].diff()
        subdf['is_dup'] = subdf['time_diff'] < pd.Timedelta(seconds=1)
        time_dup_id = pd.Series(index=subdf.index, dtype='Int64')

        for _, g in subdf.groupby(group_cols):
            dup_mask = g['is_dup'].fillna(False)
            run_indices = []
            run_active = False
            for idx, isdup in zip(g.index, dup_mask):
                if isdup:
                    if len(run_indices) == 0:
                        prev_idx_pos = g.index.get_loc(idx) - 1
                        if prev_idx_pos >= 0:
                            prev_idx = g.index[prev_idx_pos]
                            run_indices.append(prev_idx)
                    run_indices.append(idx)
                    run_active = True
                else:
                    if run_active and len(run_indices) > 0:
                        time_dup_id.loc[run_indices] = duplicate_id_counter
                        duplicate_id_counter += 1
                    run_indices = []
                    run_active = False
            if run_active and len(run_indices) > 0:
                time_dup_id.loc[run_indices] = duplicate_id_counter
                duplicate_id_counter += 1

        subdf['time_duplicate_id'] = time_dup_id
        all_results.append(subdf)

    df_out = pd.concat(all_results, ignore_index=False)
    df_out.drop(columns=['is_dup'], inplace=True)
    return df_out

def print_unique_counts_summary(df, filename):
    columns_to_check = ['path', 'name', 'field', 'value', 'component', 'component_id']
    print(f"\nSummary of unique counts for {filename}:")
    for col in columns_to_check:
        if col in df.columns:
            unique_count = df[col].nunique(dropna=True)
            print(f"  Unique {col}: {unique_count}")
        else:
            print(f"  Column '{col}' not found in data.")

def analyze_and_save(df, output_csv):
    if df.empty:
        print(f"No data to process for {output_csv}")
        return

    if df.columns.duplicated().any():
        df = df.loc[:, ~df.columns.duplicated()]

    df = df.rename(columns={'_time': 'producer_time', '_value': 'value', '_field': 'field'})

    desired_order = ['_measurement', 'path', 'name', 'field', 'value', 'received_time', 'producer_time', 'delays_ms']
    cols = [col for col in desired_order if col in df.columns] + [c for c in df.columns if c not in desired_order]
    df = df[cols]

    print(f"\nProcessing result saved to {output_csv}")

    df['path'] = df['path'].astype(str).str.strip()
    #df['name'] = df['name'].astype(str).str.strip()
    # commented above line due to below if condition
    if 'name' in df.columns:
        df['name'] = df['name'].astype(str).str.strip()
    else:
        # create empty placeholder so the rest of the pipeline doesn't break
        df['name'] = ""

    df['field'] = df['field'].astype(str).str.strip()

    print(f"Unique path count: {df['path'].nunique()}")
    print(f"Unique name count: {df['name'].nunique()}")
    print(f"Unique field count: {df['field'].nunique()}")

    grouped_counts = df.groupby(['path', 'name', 'field']).size().reset_index(name='count')
    print("\nCount by path, name, and field:")
    print(grouped_counts)

    field_totals = df['field'].value_counts().reset_index()
    field_totals.columns = ['field', 'total_count']
    print("\nTotal count of each field:")
    print(field_totals)

    def has_missing_and_present(group):
        return group['value'].isna().any() and group['value'].notna().any()

    group_cols = ['path', 'name', 'field']
    inconsistent_groups = df.groupby(group_cols).filter(has_missing_and_present)
    inconsistent_keys = inconsistent_groups[group_cols].drop_duplicates()
    df['has_inconsistency'] = df.set_index(group_cols).index.isin(inconsistent_keys.set_index(group_cols).index)
    df['has_inconsistency'] = df['has_inconsistency'].map({True: 'yes', False: 'no'})

    df['delays_ms'] = pd.to_numeric(df.get('delays_ms', pd.Series(dtype=float)), errors='coerce')
    count_delays_over_10s = (df['delays_ms'] > 10000).sum()
    print(f"Rows with delay > 10 seconds: {count_delays_over_10s}")
    #df = flag_duplicates(df)
    df = flag_duplicates_exact_time_diff(df)
    print_unique_counts_summary(df, output_csv)
    df.to_csv(output_csv, index=False)
    print(f"Saved processed CSV to: {output_csv}")

def check_subset(df1, df2, subset_cols):
    """
    Check if df2[subset_cols] is a subset of df1[subset_cols].
    """
    df1_subset = df1[subset_cols].drop_duplicates()
    df2_subset = df2[subset_cols].drop_duplicates()

    merged = df2_subset.merge(df1_subset, on=subset_cols, how='left', indicator=True)
    missing = merged[merged['_merge'] == 'left_only']

    if missing.empty:
        print(f"\ndf2 is a subset of df1 based on columns {subset_cols}")
        return True
    else:
        print(f"\ndf2 is NOT a subset of df1 based on columns {subset_cols}")
        print(f"Missing rows in df1 (present in df2):\n{missing}")
        return False

def main():
    parser = argparse.ArgumentParser(description="Process multiple influx queries from YAML config.")
    parser.add_argument("config", help="Path to YAML config file")
    args = parser.parse_args()

    # Redirect print output to file AND console
    sys.stdout = Logger("README.txt")

    config = load_config(args.config)
    influx_cfg = config.get("influx", {})
    queries = config.get("queries", [])
    csv_drop_columns = [
        'result', 'table', '_start', '_stop', 'Unnamed: 0', 'device', 'host', 'source', 'sub_component_id', 'uuid'
    ]

    url = influx_cfg.get("url")
    token = influx_cfg.get("token")
    org = influx_cfg.get("org")
    bucket = influx_cfg.get("bucket")

    for q in queries:
        name = q.get("name", "unnamed_query")
        print(f"\nRunning query: {name}")

        query = q.get("query")
        raw_csv = q.get("raw_csv")
        output_csv = q.get("output_csv")

        df = None

        if query:
            df = run_flux_query(url, token, org, query)
            if df is None or df.empty:
                print(f"No data returned for query {name}")
                continue
            df.to_csv(raw_csv, index=False)
            print(f"Query results saved to {raw_csv}")
        elif raw_csv:
            if not os.path.exists(raw_csv):
                print(f"Raw CSV {raw_csv} not found, skipping.")
                continue
            print(f"Loading raw CSV from {raw_csv}")
        else:
            print(f"No query or raw_csv specified for {name}, skipping.")
            continue

        df = load_clean_influx_csv(raw_csv, drop_columns=csv_drop_columns)
        if df.empty:
            print(f"No data after cleaning for {name}")
            continue
        # Added below 3 lines for converting fc_name to name for junos/cos path for NGPR
        if 'name' not in df.columns and 'fc_name' in df.columns:
            df = df.rename(columns={'fc_name': 'name'})
        if 'name' not in df.columns and 'tms_name' in df.columns:
            df = df.rename(columns={'tms_name': 'name'})
        if 'Custom1' not in df.columns and '/components/component/properties/property/name' in df.columns:
            df = df.rename(columns={'/components/component/properties/property/name': 'Custom1'})
        df['name'] = df['name'].astype('string').str.strip()

        df_processed = process_suffix_fields(df)
        analyze_and_save(df_processed, output_csv)

    if len(queries) >= 2:
        print("\nComparing the two query results for subset check (columns: path, field)...")
        df1 = pd.read_csv(queries[0]['output_csv'])
        df2 = pd.read_csv(queries[1]['output_csv'])

        check_subset(df1, df2, ['path', 'field'])
    else:
        print("\nNot enough queries to perform subset comparison.")
    print("\n !! Test Quiery Completed !!.")
if __name__ == "__main__":
    main()

