from collections import defaultdict
import os
import sys
import glob
import io
import shlex, subprocess
import argparse
import re
from collections import namedtuple
import operator
import numpy as np

from gmon_sample_multiprocessing import histEntry, gmonSamples
from cost_discount_multiprocessing import CostDiscountCalculator
from static_analyzer import key_desc, Layout
from var_sample_multiprocessing import VarSamples
from var_discount_multiprocessing import VarDiscountCalculator
from multiprocessing import Pool

import time

class DiscountAttributer:
    def __init__(self, norm_vars, norm_gmon, bug_vars, bug_gmon, index, default_discount, valid_discount):
        self.hist_attr_list=[ 'total_percentage',\
                'total_time',\
                'self_time',\
                'calls',\
                'total_per_call',\
                'self_per_call']
        self.time_per_sample = 0.005 #seconds
        self.cost_calculator = CostDiscountCalculator(norm_gmon, bug_gmon)
        self.cost_calculator.set_valid_discount(valid_discount)
        self.cost_discounts = self.cost_calculator.aggregate_discount()

        self.var_calculator = VarDiscountCalculator(norm_vars, bug_vars)
        self.var_calculator.set_valid_discount(valid_discount)
        self.var_calculator.set_default_discount(default_discount)
        self.default_discount = default_discount

        self.bug_sample = self.var_calculator.aggregate_discount_for_varsample(bug_vars.samples[index])

        self.discount_on_func = self.var_calculator.discount_on_func
        self.annotate_on_func = self.var_calculator.annotate_on_func
        self.desc_to_func = self.var_calculator.desc_to_func
        self.desc_to_dimension = self.var_calculator.desc_to_dimension

        def unfold_descs():
            self.func_to_descs = {}
            for desc, func in self.desc_to_func.items():
                if func not in self.func_to_descs:
                    self.func_to_descs[func] = []
                self.func_to_descs[func].append(desc)
        unfold_descs()

    def sample_counts_for_funcs(self):
        """make up function cost due to execution outside text segment such as call to dynamic libraries
        """
        func_samples = self.var_calculator.attribute_global_var_to_funcs(self.bug_sample)
        for key, desc in self.bug_sample.schema_descs.items():
            samples = self.bug_sample.unfold_samples_for_desc(desc)
            if desc in self.desc_to_func:
                func = self.desc_to_func[desc]
            else:
                func = key.split(':')[1]
            func_samples[func] = max(func_samples[func], len(samples))
        return func_samples

    def update_cost(self, sample, hist_attr):
        """try re-attribute cost and detect variable samples that misssing hist entry
        """
        hist_list = sample.entries
        hist_dict = sample.get_hist_dict()
        for func, nsamples in self.sample_counts_for_funcs().items():
            time = float(nsamples * self.time_per_sample)
            if func in hist_dict:
                if float(time) > float(getattr(hist_dict[func], hist_attr)):
                    setattr(hist_dict[func], hist_attr, time)
            elif re.search('#global', func):
                continue
            else:
                hist_entry = histEntry(['0.0', time, time, '0', '0', '0', func])
                hist_entry.cost = float(time)
                if func in self.discount_on_func:
                    hist_entry.discount = self.discount_on_func[func]
                else:
                    hist_entry.discount = 0.0
                hist_entry.calls = nsamples
                hist_list.append(hist_entry)
                hist_dict[func] = hist_entry

        for index in range(len(hist_list)):
            func = hist_list[index].symbol
            if not func:
                continue
            discount = 0.0
            if func in self.discount_on_func:
                discount = self.discount_on_func[func]
            elif func in self.cost_discounts:
                discount = self.cost_discounts[func]
            hist_list[index].discount = discount
            hist_list[index].cost = float(getattr(hist_list[index], hist_attr)) * (float)(1 - discount)
        self.annotate(hist_list)
        return hist_list

    def annotate(self, hist_list):
        for index in range(len(hist_list)):
            func = hist_list[index].symbol
            if not func:
                continue
            if func in self.annotate_on_func:
                hist_list[index].annotate = self.annotate_on_func[func]

    def infer_pattern(self, tag, dimension, discount):
        if re.search('processing', dimension):
            if discount >= self.default_discount:
                return 'Scalability'

            if re.search('loop', tag) or re.search('cond', tag):
                return 'MissConstraint'

        else:
            if re.search('loop', tag):
                return 'Scalability'

            if re.search('cond', tag):
                return 'WrongConstraint'

        if discount >= self.default_discount or re.search('norm=0', dimension):
            return 'Scalability'
        return 'Undefined'


    def sort_variable_location(self, layout, hist_entry):
        def collect_vals(outliers):
            outlier_vals = set()
            for vals in outliers:
                for val in vals:
                    outlier_vals.add(val)
            return outlier_vals

        def translate_val_to_location(key, values):
            samples_locs = defaultdict(list)
            for sample in self.bug_sample.unfold_samples_for_desc(key):
                if sample.val in values and sample.line != None:
                    samples_locs[sample.val].append(sample.file + '_' + str(sample.line))
                    if self.bug_sample.attach_value_flow(key, sample, layout):
                        samples_locs[sampel.val].append(':propagated_from_' + '||'.join(list(sample.propagate)))
            return samples_locs
        
        def collect_locs(outliers_on_key, locations_on_key):
            locs = defaultdict(lambda:0)
            for vals in outliers_on_key:
                for val_i in vals:
                    for item in locations_on_key[val_i]:
                        locs[item] += 1
            return locs

        if hist_entry.symbol not in self.func_to_descs:
            return

        for key in self.func_to_descs[hist_entry.symbol]:
            discounts_on_key = self.bug_sample.discounts_dict[key]
            outliers_on_key = self.bug_sample.outliers_dict[key]
            #sort them based on the list of discounts on key
            sorted_on_discounts = sorted(list(zip(discounts_on_key, outliers_on_key, self.desc_to_dimension[key])), key=lambda i: i[0])
            locations_on_key = translate_val_to_location(key, collect_vals(outliers_on_key))
            locs = collect_locs(outliers_on_key, locations_on_key)
            #display annotated info
            try:
                print(f"\n\t\t{key}\n\t\t**Discount:{list(zip(*sorted_on_discounts))[0]}\n\t\t**dimension:[{', '.join(list(zip(*sorted_on_discounts))[2])}]")
            except Exception as ex:
                print(f'\n\t\tex: key = {key}, dim = {self.desc_to_dimension[key]}')
            pattern = self.infer_pattern(key.split()[-1], ''.join(self.desc_to_dimension[key]), max(discounts_on_key))
            print(f'\t\t**Pattern inferred: {pattern}')
            if len(locs) > 0:
                print(f'\t\t**Code area: {set(locs.keys())}')

    def attribute_sample_cost(self, sample, layout, outfile):
        print('--- Update cost based on value samples ---')
        hist_list = self.update_cost(sample, self.hist_attr_list[2])
        print('--- Discounted cost based on {} ---'.format(self.hist_attr_list[2]))
        hist_list.sort(key=operator.attrgetter('cost', 'calls'), reverse=True)
        hist_list[0].print_header()
        for i, item in enumerate(hist_list):
            item.print_entry_with_index(i)
            self.sort_variable_location(layout, item)

def vprof(args):
    start_time = time.time()
    norm_gmons = gmonSamples(args.norms, args.norm_bin, int(args.max))
    bug_gmons = gmonSamples(args.bugs, args.bug_bin, int(args.max))
    norm_vars = VarSamples(args.norms, args.norm_bin, int(args.max), args.norm_srcinfo)
    bug_vars = VarSamples(args.bugs, args.bug_bin, int(args.max), args.bug_srcinfo)
    with Pool() as pool:
        norm_results = pool.map_async(norm_vars.parse_var_file, norm_vars.files_analyze)
        bug_results = pool.map_async(bug_vars.parse_var_file, bug_vars.files_analyze)
        pool.close()
        pool.join()
        norm_vars.samples = norm_results.get()
        bug_vars.samples = bug_results.get()

    if norm_vars.size == 0 or bug_vars.size == 0:
        print('var samples missing in bug or norm case')
        exit(1)
    print("--- %s seconds parsing samples ---" % (time.time() - start_time))

    for sample in norm_vars.samples:
        sample.display_samples("var_samples.norms.txt")

    for sample in bug_vars.samples:
        sample.display_samples("var_samples.bugs.txt")

    print('--- Begin construct discount attributer ---')
    start_time = time.time()
    index = min(int(args.index), int(args.max) - 1)
    bug_vars.set_schemas()
    norm_vars.set_schemas()

    attributer = DiscountAttributer(norm_vars, norm_gmons, bug_vars, bug_gmons, index, float(args.default_discount), float(args.valid_discount))
    layout = Layout(bug_vars.samples[index].layout_file, args.bug_bin)
    attributer.attribute_sample_cost(bug_gmons.samples[index], layout, args.output)
    print("--- %s seconds attribute sample cost ---" % (time.time() - start_time))

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Attribute variable samples to corresponding functions')
    parser.add_argument('--norm_bin', required=True, help='')
    parser.add_argument('--bug_bin', required=True, help='')
    parser.add_argument('--norms', default = 'norms', help='')
    parser.add_argument('--bugs', default = 'bugs', help='')
    parser.add_argument('--norm_srcinfo', default='norms/src2bb.txt')
    parser.add_argument('--bug_srcinfo', default='bugs/src2bb.txt')

    #default paramters
    parser.add_argument('--max', default = 8, help ='maximum number of samples supported to process')
    parser.add_argument('--index', default = 0, help ='report based on the bug gmon in the bugid th bug sample')
    parser.add_argument('--output', default = "vprof_discount_attribute.report")
    parser.add_argument('--default_discount', default = 0.8)
    parser.add_argument('--valid_discount', default = 0.1)
    args = parser.parse_args()
    print(f'default_ratio={args.default_discount}, valid_ratio={args.valid_discount}')
    vprof(args)
