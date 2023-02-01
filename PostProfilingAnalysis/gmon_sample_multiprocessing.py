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
from multiprocessing import Pool, cpu_count

hist_entry = namedtuple('hist_entry', \
        'total_percentage,\
        total_time,\
        self_time,\
        calls,\
        total_per_call,\
        self_per_call,\
        symbol')

class histEntry:
    def __init__(self, args):
        val = hist_entry(*args)
        self.annotate = None
        self.cost = 0.0
        self.discount = 0.0
        self.total_percentage = float(val.total_percentage)
        self.total_time = float(val.total_time)
        self.self_time = float(val.self_time)
        self.calls = int(val.calls)
        self.total_per_call = float(val.total_per_call)
        self.self_per_call = float(val.self_per_call)
        self.symbol = val.symbol
        
    def print_entry(self):
        print(f'{self.symbol}\t{self.cost:.2f}\t{self.total_percentage:.2f}\t{self.total_time:.2f}\t{self.self_time:.2f}\t{self.calls:>12}\t{self.discount:.2f}')
        if self.annotate:
            print(f'Annotate: {self.annotate}')
            
    def print_entry_with_index(self, index):
        text = '[{}] {:<48}\t{:.2f}\t{:.2f}\t{:.2f}\t{:.2f}\t{:>12}\t{:.2f}'
        print(text.format(index, self.symbol, self.cost, self.total_percentage, self.total_time, self.self_time, self.calls, self.discount))
        if self.annotate:
            print("Annotate: {}".format(self.annotate))


    def print_header(self):
        print('{:<48}\t{}\t{}\t{}\t{}\t{}\t{}'.format('Function', 'adjusted_cost', 'total_percentage', 'total_time',\
            'self_time', 'calls', 'discount'))

    def get_attr(self, var):
        return getattr(self, var)

    def set_attr(self, var, val):
        setattr(self, var, val)

class gmonSample:
    def __init__(self, datafile, binfile):
        self.infile = datafile
        self.bin = binfile
        self.entries = []
        self.hist_dict = {}
        self.parse()

    def parse(self):
        cmd = '/usr/bin/gprof ' + self.bin + ' ' + self.infile
        args = shlex.split(cmd)
        is_entry = False
        with subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE) as proc:
            for line in io.TextIOWrapper(proc.stdout, encoding="utf-8"):
                if re.search('time', line) and re.search('s/call', line):
                    is_entry = True
                    continue
                if re.search('the percentage of the total running time of the', line):
                    is_entry = False
                    break
                if is_entry == False:
                    continue
                func = 'invalid'
                result = re.search(r'([.0-9 ]*)(.*)', line)
                if result:
                    func = result.group(2).split('(')[0].strip()
                    if func is None or len(func) == 0:
                        continue
                    line = result.group(1)
                    #line = line.split(' ')
                    fields = line.strip().split()
                    while len(fields) < 6:
                        fields.append('0')
                    fields.append(func)
                else:
                    print(f'Invalid Line: {line}')
                    continue

                entry = histEntry(fields)
                self.entries.append(entry)
                self.hist_dict[entry.symbol] = entry

    def get_hist_dict(self):
        return self.hist_dict

    def display(self):
        if len(self.entries) > 0:
            self.entries[0].print_header()
        for entry in self.entries:
            entry.print_entry()

class gmonSamples:
    def __init__(self, directory, binfile, max_count):
        self.dir = directory
        self.bin = binfile
        self.max_count = max_count
        self.samples = []
        self.collect_files()
        self.size = len(self.files_analyze)
        self.parse()
        # aggregate
        self.attribute_list = ['total_percentage', \
                'total_time',\
                'self_time', \
                'calls',\
                'total_per_call',\
                'self_per_call']
        self.hist_dict = {}

    def get_size(self):
        self.size = len(self.samples)
        return self.size

    def parse_gmon_file(self, datafile):
        if not os.path.isfile(self.bin):
            self.bin = self.dir + self.bin
        if not os.path.isfile(self.bin):
            print('{} is not valid execution for gprof'.format(self.bin))
        return gmonSample(datafile, self.bin)

    def collect_files(self):
        files = []
        for datafile in glob.iglob(self.dir +'/**/gmon.*.out', recursive = True):
            files.append(datafile)
        files.sort()
        files_analyze = files
        if len(files) > self.max_count:
            files_analyze = files[0:self.max_count]
        self.files_analyze = files_analyze

    def parse(self):
        with Pool() as pool:
            self.samples = pool.map(self.parse_gmon_file, self.files_analyze)

    def get_samples(self):
        return self.samples

    def aggregate(self):
        key_count = defaultdict(lambda:0)
        self.hist_dict.clear()
        for sample in self.samples:
            local_hist = sample.get_hist_dict()
            for key in local_hist:
                if not key in self.hist_dict:
                    self.hist_dict[key] = local_hist[key]
                    key_count[key] = 1
                else:
                    for attribute in self.attribute_list:
                        old_val = self.hist_dict[key].get_attr(attribute)
                        self.hist_dict[key].set_attr(attribute, old_val + local_hist[key].get_attr(attribute))
                    key_count[key] = key_count[key] + 1

        for key in key_count:
            if key_count[key] <= 1:
                continue
            for attribute in self.attribute_list:
                val = self.hist_dict[key].get_attr(attribute) / key_count[key]
                self.hist_dict[key].set_attr(attribute, val)
        return self.hist_dict

    def print_aggregate(self):
        print('aggregated histgram')
        for key in self.hist_dict:
            self.hist_dict[key].print_entry()

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Attribute variable samples to corresponding functions')
    parser.add_argument('--bin', required=True, help='')
    parser.add_argument('--norms', required=True, help='')
    parser.add_argument('--bugs', required=True, help='')
    parser.add_argument('--max', default = 100, help ='maximum number of samples supported to process')
    args = parser.parse_args()

    print('==================norm cases=================')
    norm_samples = gmonSamples(args.norms, args.bin, int(args.max))
    norm_samples.aggregate()
    norm_samples.print_aggregate()
    print('==================bug cases=================')
    bug_samples = gmonSamples(args.bugs, args.bin, int(args.max))
    bug_samples.aggregate()
    bug_samples.print_aggregate()
