import argparse
import subprocess
from collections import namedtuple

import copy
import json
import pandas as pd
import tempfile

from core.config import cluster_config_from_path
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
                model_params = generate_model_params(server_config["usage"][usage_field], analysis_config[analysis_field], usage_field)
                # Generate a different cluster config for each entry in model_params
                for model_param in model_params:
                    analysis_model_dict = copy.deepcopy(server_config)
                    analysis_model_dict["usage"][usage_field] = model_param['model']
                    # Write the config to a temp file so it can be make into a ClusterConfig object
                    with open(tempfile.NamedTemporaryFile().name, 'a+') as f:
                        f.write(json.dumps(analysis_model_dict))
                        f.seek(0)
                        analysis_model_config = cluster_config_from_path(f.name)
                    configs_to_analyze.append({"model": analysis_model_config,
                                               "field_to_modify": model_param["field_to_modify"],
                                               "subfield_to_modify": model_param["subfield_to_modify"],
                                               "step_value": model_param["step_value"]})

    return configs_to_analyze


def generate_model_params(model_params, analysis_config_entry, field_to_modify):
    step_values = generate_steps(analysis_config_entry)
    analysis_model_params = []
    subfield_to_modify = analysis_config_entry["field_name"]
    for step_value in step_values:
        this_model_def = copy.deepcopy(model_params)
        this_model_def[subfield_to_modify] = step_value * model_params[subfield_to_modify]
        analysis_model_params.append({"model": this_model_def,
                                      "field_to_modify": field_to_modify,
                                      "subfield_to_modify": subfield_to_modify,
                                      "step_value": step_value})
    return analysis_model_params

def generate_steps(analysis_config_entry):
    val_to_add = analysis_config_entry["factor_start"]
    step_values = []
    while val_to_add <= analysis_config_entry["factor_end"]:
        step_values.append(val_to_add)
        val_to_add += analysis_config_entry["factor_step"]
    return step_values

def compare_to_baseline_values(field_to_update, output_data, baseline_step_value_index):
    return ['{}%'.format(value/(output_data[field_to_update][baseline_step_value_index]) * 100) for value in output_data[field_to_update]]

if __name__ == '__main__':

    parser = argparse.ArgumentParser('CommCare Cluster Model')
    parser.add_argument('server_config', help='Path to cluster config file')
    parser.add_argument('-o', '--output', help='Write output to Excel file at this path.')
    parser.add_argument('-s', '--service', help='Only output data for specific service.')

    args = parser.parse_args()

    pd.options.display.float_format = '{:.1f}'.format

    server_config = cluster_config_from_path(args.server_config)
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
        else:
            summary_comparisons = compare_summaries(server_config, summaries)
            incrementals = incremental_summaries(summary_comparisons, summary_dates)
            write_summary_comparisons(server_config, writer, user_count, summary_comparisons)
            write_summary_comparisons(server_config, writer, user_count, incrementals, prefix='Incremental ')

            for date in sorted(summaries):
                write_summary_data(server_config, writer, date, summaries[date], user_count[date])

        if is_excel:
            # only write raw data if writing to Excel
            write_raw_data(writer, usage, 'Usage')
            write_raw_service_data(writer, service_data, summary_data, 'Raw Data')

            with open(args.server_config, 'r') as f:
                config_string = 'Git commit: {}\n\n{}'.format(
                    get_git_revision_hash(),
                    f.read()
                )
                writer.write_config_string(config_string)
