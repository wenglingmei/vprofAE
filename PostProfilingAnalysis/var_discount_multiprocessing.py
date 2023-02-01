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
import statistics
from scipy.stats import ks_2samp
from scipy.stats import anderson_ksamp
from scipy.spatial.distance import euclidean
from concurrent.futures import ThreadPoolExecutor
from multiprocessing import Pool
import warnings
warnings.filterwarnings("ignore")

from static_analyzer import key_desc, regx_desc, func_index, symbol_index
from var_sample_multiprocessing import VarSample, VarSamples

discount_entry = namedtuple('discount_entry', 'dir, file, function, line, symbol, type, usage, discount, default')
insane_map={'proc', 'pid', 'thread', 'tid', 'time'}

class VarDiscountCalculator():
    """Calculate discount ratio with variable samples from buggy cases and baselines.
    First, perform a Kolmogorov-Smirnov test / Anderson test on these two samples
    Null hypothesis: two array of value / processing duration / delta from the same distribution
    discount -> 1.0 if null hypothesis is not rejected
    default discount means the null hypothesis is not rejected, so we thought they are similar
    in distribution.
    """
    sample_duration = 5 #ms
    def __init__(self, norm_vars, bug_vars):
        self.norms = norm_vars.samples
        self.bugs = bug_vars.samples
        self.bug_schemas = bug_vars.schemas
        self.norm_schemas = norm_vars.schemas
        self.schemas = [key for key in self.bug_schemas if key in self.norm_schemas]
        self.cur_bug_sample = None
        self.threshold = 0.95
        self.pvalue = 0.05
        self.validate_discount = 0.1
        self.default_discount = 0.8
        #calculate discount for variables
        self.discount_on_var = {}
        self.discount_on_func = {}
        self.desc_to_dimension = defaultdict(list)
        self.desc_to_func = defaultdict(lambda:None)
        self.annotate_on_func = {}
        self.global_vars = []

    def set_default_discount(self, rate):
        self.default_discount = rate

    def set_valid_discount(self, rate):
        self.validate_discount = rate

    def key_description(self, desc):
        """ extract key description from the line of key
        """
        ret = re.search(regx_desc, desc)
        try:
            var_type = ret.group(1)
            var_info = ret.group(2)
            fields = var_info.split()
            return var_type, key_desc(*fields) 
        except Exception as ex:
            pass
        return None, None

    def meaningful(self, variable, v_type):
        for item in insane_map:
            if re.search(item, variable) or re.search(item, v_type):
                return False
        return True
    
    def reject_null_hypothesis(self, norm, bug):
        """need more careful about the false positive/negative
        """
        if bug.size == 0:
            return False

        if norm.size == 0: #reject null because varsample are not collected in norm mostly fast execution
            return True

        #stat_ks_2sample, pvalue_ks_2sample = ks_2samp(norm, bug)
        #if pvalue_ks_2sample < self.pvalue:
           # return True
        try:
            stat, critical_values, pvalue = anderson_ksamp([np.asarray(norm), np.asarray(bug)])
            if pvalue < self.pvalue: 
                return True
        except Exception as ex:
            pass
        return False

    def hellinger_distance(self, norm, bug):
        """calculate a minimal discount since null hypothesis is rejected
        """
        def distribute(samples):
            values, counts = np.unique(samples, return_counts=True)
            result = {}
            for index in range(values.size):
                result[values[index]] = float(counts[index]/samples.size)
            return result

        def align_array(dict1, dict2, values, default):
            arr1 = []
            arr2 = []
            for val in values:
                arr1.append(dict1.get(val, default))
                arr2.append(dict2.get(val, default))
            return np.array(arr1), np.array(arr2)

        norm_dict = distribute(norm)
        bug_dict = distribute(bug)
        values = np.unique(np.concatenate([norm, bug]))
        norm_dist, bug_dist = align_array(norm_dict, bug_dict, values, 0.0)
        _SQRT2 = np.sqrt(2)
        distance = euclidean(np.sqrt(norm_dist), np.sqrt(bug_dist)) / _SQRT2
        return distance

    def range_distance(self, norm, bug):
        """Calculate a minimal discount since null hypothesis is rejected;
        Report the most likely diverted values
        """
        n_bug, c_bug = np.unique(bug, return_counts=True)
        if bug.size == 0:
            return 0.0, n_bug
        if norm.size == 0:
            return 1.0, n_bug
        n_norm, c_norm = np.unique(norm, return_counts=True)
        maxnorm = np.amax(n_norm)
        minnorm = np.amin(n_norm)
        bad_sample = 0
        outliers = []
        for i, val in enumerate(n_bug):
            if val * self.threshold > maxnorm or val < minnorm * self.threshold:
                bad_sample += c_bug[i]
                outliers.append(val)
        diff = float(bad_sample/bug.size)
        return diff, outliers

    def duration_array(self, samples):
        """Estimate the processing time for individual value in the variable sample list.
        Convert the us in timestamp into ms in delta.
        Return the duration array and corresponding values in a list
        """
        result = []
        vals = []
        if len(samples) == 0:
            return np.array(result), vals
        duration = self.sample_duration
        for index in range(1, len(samples)):
            if samples[index - 1].val == samples[index].val:
                delta = (samples[index].seqid - samples[index - 1].seqid)/1000
                duration = duration + delta
            else:
                vals.append(samples[index - 1].val)
                result.append(duration)
                duration = self.sample_duration
        vals.append(samples[-1].val)
        result.append(duration)
        return np.array(result), vals

    def value_array(self, samples):
        """Extract the values from the sample array
        """
        result = []
        for item in samples:
            result.append(item.val)
        return np.array(result)

    def delta_array(self, values):
        """Extract delta of values from the sample array
        """
        result = []
        if values.size == 0:
            return np.array(result)
        prev_value = values[0]
        for i, value in enumerate(values):
            result.append(value - prev_value)
            prev_value = value
        return np.array(result)

    def similar(self, norm, bug):
        """Calculate the similarity on value range for a individual variable
        """
        diff_rate, outliers = self.range_distance(norm, bug)
        if self.reject_null_hypothesis(norm, bug) == False:
            discount = self.default_discount
        else: #reject null, calculate a minimum discount with hellinger_distance
            discount = 1.0 - self.hellinger_distance(norm, bug)
        return discount, outliers

    def default_similarity(self, dimension, norm_array, bug_array):
        discount = self.default_discount
        outlier = []
        if len(norm_array) == 0 and len(bug_array) == 0:
            #if no value for both variables, we assume their values are similar
            picked_dimension = dimension + str(self.default_discount) + ': default(both=0)'
        elif len(norm_array) == 0:
            discount = self.validate_discount
            outlier = list(set(self.value_array(bug_array)))
            picked_dimension = dimension + '0.0 : zero(norm=0)'
        elif len(bug_array) == 0: #unlikely, in case comparine two versions where the variable is non-exist in the bug version.
            picked_dimension = dimension + str(self.default_discount) + ': default(bug=0)'
        return discount, outlier, picked_dimension

    def value_similarity(self, key, dimension, norm_values, bug_values):
        outlier = []
        picked_dimension = None
        if self.meaningful(key.symbol, key.type):
            discount, outlier_val = self.similar(norm_values, bug_values)
            outlier = outlier_val
            picked_dimension = dimension + str(discount) + ': val'
        #Calculate the similarity on the value deltas
        delta_discount, outlier_delta = self.similar(self.delta_array(norm_values), self.delta_array(bug_values))
        if picked_dimension == None or delta_discount <= discount:
            discount = delta_discount
            outlier = []
            prev_val = bug_values[0]
            for i, val in enumerate(bug_values):
                if val - prev_val in outlier_delta:
                    outlier.append(val)
                prev_val = val
            picked_dimension = dimension + str(discount) + ': delta'
        return discount, outlier, picked_dimension

    def processing_similarity(self, key, dimension, norm_duration, bug_duration, bug_vals):
        """Calculate the similarity on the processing time cost for individual value
        """
        discount, duration_outliers = self.similar(norm_duration, bug_duration)
        outliers = []
        for i, processing in enumerate(bug_duration):
            if processing in duration_outliers:
                outliers.append(bug_vals[i]) 
        return discount, outliers, dimension + str(discount) + ': processing'

    def cmp_to_norm_samples_on_desc(self, desc_key):
        def prepare_arrays(key_type, bug_array):
            bug_values = self.value_array(bug_array) if key_type == 'DW_TAG_base_type' else None
            bug_processing, bug_vals = self.duration_array(bug_array)
            return bug_values, bug_processing, bug_vals
        bug_desc = self.bug_schemas[desc_key]
        key_type, key = self.key_description(bug_desc)
        bug_array = self.cur_bug_sample.unfold_samples_for_desc(bug_desc)
        bug_values, bug_processing, bug_vals = prepare_arrays(key_type, bug_array)

        non_fault_ratios = []
        ratios = []
        outliers = []
        aggregated_dimension = []

        for norm_sample in self.norms:
            dimension = norm_sample.datafile + ' '
            discount = self.default_discount
            outlier = []
            picked_dimension = None
            
            norm_desc = self.norm_schemas[desc_key]
            norm_array = norm_sample.unfold_samples_for_desc(norm_desc)
            if len(norm_array) == 0 or len(bug_array) == 0:
                discount, outlier, picked_dimension = self.default_similarity(dimension, norm_array, bug_array)
            else:
                # value related similarity
                if key_type == 'DW_TAG_base_type':
                    norm_values = self.value_array(norm_array)
                    discount, outlier, picked_dimension = self.value_similarity(key, dimension, norm_values, bug_values)
                # processing simiarity
                norm_processing, norm_vals = self.duration_array(norm_array)
                duration_discount, duration_outlier, duration_dimension = self.processing_similarity(key, dimension, norm_processing, bug_processing, bug_vals)
                if picked_dimension == None or duration_discount <= discount:
                    discount = duration_discount
                    outlier = duration_outlier
                    picked_dimension = duration_dimension

                discount = 0.0 if discount < self.validate_discount else discount
                non_fault_ratios.append(discount)

            ratios.append(discount)
            outliers.append(outlier)
            aggregated_dimension.append(picked_dimension)

        return ratios, non_fault_ratios, outliers, aggregated_dimension

    def var_discount_exp(self, desc_key):
        desc = self.bug_schemas[desc_key]
        ratios, non_fault_ratios, outliers, aggregated_dimension = self.cmp_to_norm_samples_on_desc(desc_key)

        if len(ratios) == 0: #unlikely
            discount = self.default_discount
        elif len(non_fault_ratios) > 0:
            discount = statistics.median(non_fault_ratios)
        else:
            discount = statistics.median(ratios)

        ret = re.search(regx_desc, desc)
        try:
            var_info = ret.group(2)
            fields = var_info.split()
            fields.append(discount)
            fields.append(len(non_fault_ratios) == 0)
            if fields[func_index] == '#global':
                self.global_vars.append(desc)
                fields[func_index] = fields[symbol_index]+ '#global'
            discount_item = discount_entry(*fields)
        except Exception as ex:
            print(f'Error in parsing discount for {desc}: \n\t\t{fields} \n\t\tException = {ex}')
        return [ratios, outliers, aggregated_dimension, discount_item]

    def infer_pattern(self, tag, dimension, discount):
        if re.search('processing', dimension):
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

    def aggregate_discount_for_varsample(self, var_sample):
        """Aggregate discounts from variables to function
        select the minimal discount if multiple variables
        in the function
        FIXME: Algorithm on discount choice among multiple variables
        Current: pick the minimal discount and update the picked key annotation,
        save all possible anomaly
        """
        self.cur_bug_sample = var_sample

        with ThreadPoolExecutor() as exe:
            results = exe.map(self.var_discount_exp, self.schemas)
        #for schema_key in self.schemas:
        #    result = self.var_discount_exp(schema_key)

        for schema_key, result in zip(self.schemas, results):
            ratios, outliers, aggregated_dimension, discount_item = result
            desc = self.bug_schemas[schema_key]
            self.discount_on_var[desc] = discount_item
            self.desc_to_func[desc] = self.discount_on_var[desc].function
            self.desc_to_dimension[desc] = aggregated_dimension
            var_sample.discounts_dict[desc] = ratios
            var_sample.outliers_dict[desc] = outliers

        for desc, func in self.desc_to_func.items():
            dimension = ','.join(self.desc_to_dimension[desc])
            tag = desc.split(':')[-1]
            if func not in self.discount_on_func:
                self.discount_on_func[func] = self.discount_on_var[desc].discount
                self.annotate_on_func[func] = desc #+ '\n\t\t[' + ', '.join(self.desc_to_dimension[desc]) + ']'
            elif self.discount_on_var[desc].discount < self.discount_on_func[func]:
                self.discount_on_func[func] = self.discount_on_var[desc].discount
                self.annotate_on_func[func] = desc #+ '\n\t\t[' + ', '.join(self.desc_to_dimension[desc]) + ']'

            elif self.discount_on_var[desc].default == False and self.discount_on_func[func] ==  self.discount_on_var[desc].discount:
                self.discount_on_func[func] = self.discount_on_var[desc].discount
                self.annotate_on_func[func] = desc #+ '\n\t\t[' + ', '.join(self.desc_to_dimension[desc]) + ']'
            else:
                continue

            #update bug pattern inference:
            #pattern = self.infer_pattern(tag, dimension, self.discount_on_func[func])
            #self.annotate_on_func[func] = self.annotate_on_func[func] + ',' + pattern

        return var_sample

    def attribute_global_var_to_funcs(self, var_sample):
        function_cost = defaultdict(lambda:0)
        for desc in self.global_vars:
            func_samples = defaultdict(lambda:0)
            sample_array_on_global_var = var_sample.unfold_samples_for_desc(desc)
            var_sample.attach_function_to_globals(sample_array_on_global_var)
            for var_sample_entry in sample_array_on_global_var:
                if var_sample_entry.function:
                    func_samples[var_sample_entry.function] += 1

            discount_item = self.discount_on_var[desc]
            for function in func_samples:
               # if function not in self.discount_on_func:
               #     self.discount_on_func[function] = discount_item.discount
               #     self.annotate_on_func[function] = desc + '\n\t\t[' + ', '.join(self.desc_to_dimension[desc]) + ']'
               # elif discount_item.discount < self.discount_on_func[function]:
               #     self.discount_on_func[function] = discount_item.discount
               #     self.annotate_on_func[function] = desc + '\n\t\t[' + ', '.join(self.desc_to_dimension[desc]) + ']'
                if func_samples[function] > function_cost[function]:
                    function_cost[function] = func_samples[function]
        return function_cost

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Attribute variable samples to corresponding functions')
    parser.add_argument('--norm_bin', required=True, help='')
    parser.add_argument('--bug_bin', required=True, help='')
    parser.add_argument('--norms', default = 'norms', help='')
    parser.add_argument('--bugs', default = 'bugs', help='')
    parser.add_argument('--norm_srcinfo', default='norm_srcinfo.txt')
    parser.add_argument('--bug_srcinfo', default='bug_srcinfo.txt')
    parser.add_argument('--max', default=5, help ='maximum number of samples supported to process')
    args = parser.parse_args()

    norm_vars = VarSamples(args.norms, args.norm_bin, int(args.max), args.norm_srcinfo)
    bug_vars = VarSamples(args.bugs, args.bug_bin, int(args.max), args.bug_srcinfo)
    with Pool() as pool:
        norm_results = pool.map_async(norm_vars.parse_var_file, norm_vars.files_analyze)
        bug_results = pool.map_async(bug_vars.parse_var_file, bug_vars.files_analyze)
        pool.close()
        pool.join()
        norm_vars.samples = norm_results.get()
        bug_vars.samples = bug_results.get()
    bug_vars.set_schemas()
    norm_vars.set_schemas()

    for sample in norm_vars.samples:
        sample.display_samples("var_samples.norms.txt")
    for sample in bug_vars.samples:
        sample.display_samples("var_samples.bugs.txt")
    discount_calculator = VarDiscountCalculator(norm_vars, bug_vars)
    discount_calculator.aggregate_discount_for_varsample(bug_vars.samples[0])

    def unfold_descs_for_func():
        descs_for_func = {}
        for desc, func in discount_calculator.desc_to_func.items():
            if func not in descs_for_func:
                descs_for_func[func] = []
            descs_for_func[func].append(desc)
        return descs_for_func
    desc_for_func = unfold_descs_for_func()

    for func, discount in discount_calculator.discount_on_func.items():
        print(f'{func}:{discount}')
        for desc in desc_for_func[func]:
            print(f'\t\tdiscount = {discount_calculator.discount_on_var[desc]}')
            print(f'\t\t{discount_calculator.desc_to_dimension[desc]}')
