import argparse
import subprocess
from collections import namedtuple

import copy
import json
import pandas as pd
import tempfile

from core.config import cluster_config_from_path, dict_config_from_path
from core.generate import generate_usage_data, generate_service_data
from core.output import write_raw_data, write_summary_comparisons, write_summary_data, write_raw_service_data
from core.summarize import incremental_summaries, \
    summarize_service_data, compare_summaries, get_summary_data
from core.writers import ConsoleWriter
from core.writers import ExcelWriter

SummaryData = namedtuple('SummaryData', 'storage compute')


def get_git_revision_hash():
    return subprocess.check_output(['git', 'rev-parse', 'HEAD']).strip().decode('utf8')

def generate_server_configs(server_config, analysis_config):
    configs_to_analyze = []
    for analysis_field in analysis_config:
        for usage_field in server_config["usage"]:
            if usage_field == analysis_field:
                model_params = generate_model_params(server_config["usage"][usage_field], analysis_config[analysis_field])
                # Generate a different cluster config for each entry in model_params
                for model_param in model_params:
                    analysis_model_dict = copy.deepcopy(server_config)
                    analysis_model_dict["usage"][usage_field] = model_param
                    # Write the config to a temp file so it can be make into a ClusterConfig object
                    with open(tempfile.NamedTemporaryFile().name, 'a+') as f:
                        f.write(json.dumps(analysis_model_dict))
                        f.seek(0)
                        analysis_model_config = cluster_config_from_path(f.name)
                    configs_to_analyze.append(analysis_model_config)

    return configs_to_analyze


def generate_model_params(model_params, analysis_config_entry):
    factor_values = generate_steps(analysis_config_entry)
    analysis_model_params = []
    field_to_modify = analysis_config_entry["field_name"]
    for factor_value in factor_values:
        this_model_def = copy.deepcopy(model_params)
        this_model_def[field_to_modify] = factor_value * model_params[field_to_modify]
        analysis_model_params.append(this_model_def)
    return analysis_model_params

def generate_steps(analysis_config_entry):
    val_to_add = analysis_config_entry["factor_start"]
    step_values = []
    while val_to_add <= analysis_config_entry["factor_end"]:
        step_values.append(val_to_add)
        val_to_add += analysis_config_entry["factor_step"]
    return step_values

if __name__ == '__main__':

    parser = argparse.ArgumentParser('CommCare Cluster Model')
    parser.add_argument('server_config', help='Path to cluster config file')
    parser.add_argument('-a', '--analysis_config', help='Path to analysis config file', required=False, )
    parser.add_argument('-o', '--output', help='Write output to Excel file at this path.')
    parser.add_argument('-s', '--service', help='Only output data for specific service.')

    args = parser.parse_args()

    pd.options.display.float_format = '{:.1f}'.format

    base_server_config = dict_config_from_path(args.server_config)
    if args.analysis_config:
        analysis_config = dict_config_from_path(args.analysis_config)
        all_server_configs = generate_server_configs(base_server_config, analysis_config)




        ####################################################################################
        for server_config in all_server_configs:
            usage = generate_usage_data(server_config)
            service_data = generate_service_data(server_config, usage)
            summary_data = get_summary_data(server_config, service_data)

            if server_config.summary_dates:
                summary_dates = server_config.summary_date_vals
            else:
                summary_dates = [usage.iloc[-1].name]  # summarize at final date


            date_list = list(usage.index.to_series())
            summary_data = get_summary_data(server_config, service_data)

            summary = summarize_service_data(server_config, summary_data, summary_dates[0])
            user_count = usage.loc[summary_dates[0]]['users']


            ram = summary[0].iloc[0]['RAM Total (GB)']
            cpu = summary[0].iloc[0]['Cores Total']
            sas_storage = summary[1].iloc[0]['Rounded Total (TB)']
            ssd_storage = summary[1].iloc[1]['Rounded Total (TB)']
            total_vms = summary[0].iloc[0]['VMs Total']

            dummy = 5

            # for date in summary_dates:
            #     summaries[date] = summarize_service_data(server_config, summary_data, date)
            #     user_count[date] = usage.loc[date]['users']
            #
            # if len(summary_dates) == 1:
            #     date = summary_dates[0]
            #     summary_data_snapshot = summaries[date]
            #     write_summary_data(server_config, writer, date, summary_data_snapshot, user_count[date])
        ####################################################################################




    server_config = config = cluster_config_from_path(args.server_config)
    usage = generate_usage_data(server_config)
    if args.service:
        server_config.services = {
            args.service: server_config.services[args.service]
        }

    service_data = generate_service_data(server_config, usage)

    if server_config.summary_dates:
        summary_dates = server_config.summary_date_vals
    else:
        summary_dates = [usage.iloc[-1].name]  # summarize at final date

    is_excel = bool(args.output)
    if is_excel:
        writer = ExcelWriter(args.output)
    else:
        writer = ConsoleWriter()

    with writer:
        summaries = {}
        user_count = {}
        date_list = list(usage.index.to_series())
        summary_data = get_summary_data(server_config, service_data)
        for date in summary_dates:
            summaries[date] = summarize_service_data(server_config, summary_data, date)
            user_count[date] = usage.loc[date]['users']

        if len(summary_dates) == 1:
            date = summary_dates[0]
            summary_data_snapshot = summaries[date]
            write_summary_data(server_config, writer, date, summary_data_snapshot, user_count[date])
