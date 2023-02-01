import os
import sys
import glob
import argparse
import re
import pandas as pd
import numpy as np
from scipy.stats import spearmanr
from scipy.stats.mstats import gmean
from collections import namedtuple
import struct
import operator
import time
from multiprocessing import Pool, cpu_count
from static_analyzer import Layout

# If pyelftools is not installed, the example can also run from the root or
# examples/ dir of the source distribution.
sys.path[0:0] = ['.', '..']

from elftools.common.py3compat import maxint, bytes2str
from elftools.dwarf.descriptions import describe_form_class
from elftools.elf.elffile import ELFFile

Hdr = namedtuple('Hdr', ['lowpc', 'highpc', 'hist_size', 'prof_rate',
        'dimen1', 'dimen2', 'froms_size', 'var_limit',
        'sample_limit', 'log_hashfraction', 'scale',
        'hdr_size', 'var_size', 'sample_size'])
HdrFormat='@PPii15sciiiiiiii'
Var = namedtuple('Var', ['loc_atom', 'addr', 'size', 'link',
        'sample_tail', 'lower', 'upper'])
VarFormat='@HllLLLL'
Val = namedtuple('Val', ['seqid', 'type', 'val', 'tid', 'var_pc', 'callee_pc', 'link'])
ValFormat='@QHQQLLL'

class ValueEntry:
    def __init__(self, value, _line, _file):
        self.seqid = value.seqid
        self.type = value.type
        self.val = value.val
        self.tid = value.tid
        self.pc = value.var_pc
        self.callee_pc = value.callee_pc
        self.link = value.link
        self.line = _line
        self.file = _file
        self.function = None
        self.propagate = set()

class VarSample:
    def __init__(self, schema_items, filename):
        self.load_address = 0
        self.schema_items = schema_items
        self.datafile = filename
        self.schema_descs = {}
        self.callsites = []
        self.variables = []
        self.samples = []
        self.sample_dict = {}
        self.discounts_dict = {} #store discount list for key, compared to a list of normal samples
        self.outliers_dict = {} #store abnormal value list for key, compared to a list of normal samples
        self.unpack_raw()
        self.classify_samples()
    
    def print_info(self):
        print(self.datafile)
        print(self.hdr)
        print('hashtable size ={}KB'.format(self.hdr.froms_size / 1024))
        print('variable size = {}KB'.format(self.variables[0].link * struct.calcsize(VarFormat) / 1024))
        print('sample size = {}KB'.format(self.samples[0].link * struct.calcsize(ValFormat) / 1024))
        self.total_duration = (self.samples[self.samples[0].link - 1].seqid - self.samples[1].seqid) / 1000000
        print('time cost {}s'.format(self.total_duration))
        print(f'#samples = {self.samples[0].link}')
        print(len(self.samples))

    def unpack_raw(self):
        """restoring variable samples from the binary data file
        """
        with open(self.datafile, 'rb') as f:
            data = f.read()
            hdr_size = struct.calcsize(HdrFormat)
            callsite_size = struct.calcsize('@L')
            hdr = Hdr._make(struct.unpack(HdrFormat, data[0 : hdr_size]))
            callsites_offset = hdr_size
            varoffset = hdr_size + hdr.froms_size
            sampleoffset = varoffset + hdr.var_limit * hdr.var_size
            self.hdr = hdr

            for i in range(callsites_offset, varoffset, callsite_size):
                callsite,  = struct.unpack('@L', data[i: i + callsite_size])
                self.callsites.append(callsite)

            for i in range(varoffset, sampleoffset, hdr.var_size):
                var = Var._make(struct.unpack(VarFormat, data[i: i + hdr.var_size]))
                self.variables.append(var)

            for i in range(sampleoffset, len(data), hdr.sample_size):
                try:
                    val = Val._make(struct.unpack(ValFormat, data[i: i + hdr.sample_size]))
                    sample = ValueEntry(val, None, None)
                    self.samples.append(sample)
                except Exception as ex:
                    pass
            #for old data, which does not substract load address for unwinded pc, use self.load_address to adjust
            #otherwise, self.load_address will be always 0
                if self.load_address == 0 and sample.type == 1:
                    self.load_address = sample.pc - sample.callee_pc
            if self.load_address > 0:
                for sample in self.samples:
                    sample.pc = sample.pc - self.load_address - 6

    def translate_pc(self, layout):
        def collect_addresses():
            addresses = set()
            for sample in self.samples:
                addresses.add(sample.pc)
            return addresses

        def attach_line_info_to_sample(map_to_line, map_to_file):
            for sample in self.samples:
                var_addr = sample.pc
                if var_addr in map_to_line:
                    sample.line = map_to_line[var_addr]
                    sample.file = map_to_file[var_addr]
                else:
                    sample.line = "LineNotFound"
                    sample.file = "FileNotFound"

        addresses = list(collect_addresses())
        map_to_line, map_to_file = layout.decode_files_lines(addresses)
        attach_line_info_to_sample(map_to_line, map_to_file)

    def attach_function_to_globals(self, sample_array):
        def construct_line_to_function():
            function_info = []
            with open(self.srcinfo, 'r') as fin:
                for line in fin:
                    groups = re.search('function=(.*),begin=([-\d]+),end=([-\d]+),filename=(.*)', line)
                    if not groups:
                        continue
                    try:
                        function_entry = {}
                        function_entry['function'] = groups.group(1).split('(')[0]
                        function_entry['begin'] = int(groups.group(2))
                        function_entry['end'] = int(groups.group(3))
                        function_entry['filename']  = groups.group(4)
                        function_info.append(function_entry)
                    except Exception as es:
                        print('srcinfo: {line}')
                        exit(1)
            return sorted(function_info, key=lambda x: x['begin'])

        function_infos = construct_line_to_function()

        def getFunction(line, filename):
            for info in function_infos:
                #if info['filename'] == filename and 
                if info['begin'] <= line and line <= info['end']:
                    return info['function']
            return None

        for sample in sample_array:
            try:
                sample.function = getFunction(int(sample.line), sample.file)
            except Exception as ex:
                continue

    def attach_value_flow(self, desc, sample, layout):
        return layout.attach_value_flow(desc, sample)
        
    def extract_from_sample_array(self, metadata):
        """get a set of var_index(lines describe location atomic in config)
        and corresponding sample lists for each var_index
        sorted as a dict
        """
        var_samples = {}
        for val in set(entry['var_index'] for entry in metadata):
            var_index = int(val)
            var_samples[var_index] = []
            sample_index = self.variables[var_index].sample_tail
            prev_index = 0
            while sample_index != prev_index and sample_index > 0:
                var_samples[var_index].append(sample_index)
                prev_index = sample_index
                try:
                    next_index = self.samples[prev_index].link
                    sample_index = next_index
                except Exception as ex:
                    print(f'Fail to get sample[{prev_index}].link')
                    print(ex)
            var_samples[var_index].sort()
        return var_samples

    def classify_samples(self):
        """ sample_dict maps key into a dict named var_samples
        where var_samples maps var_index(one line describes location atomic in config)
        into a list of variale samples.
        """
        for desc in self.schema_items:
            self.sample_dict[desc[0][1]] = self.extract_from_sample_array(desc[1:])
            self.schema_descs[desc[0][0]] = desc[0][1]

    def unfold_samples_for_desc(self, desc):
        """convert the var_samples dict into sample array sorted by timestamp
        """
        samples_array = []
        if not desc in self.sample_dict:
            return samples_array

        s = self.sample_dict[desc]
        for var_index, s_indexes in s.items():
            for sample_index in s_indexes:
                sample = self.samples[sample_index]
                samples_array.append(sample)
        samples_array.sort(key=lambda x:x.seqid)
        return samples_array

    def print_sample(self, sample):
        text = '    timestamp = {s_id}, type = {stype}, val = 0x{val:x}, pc = 0x{pc:x}, tid = 0x{tid:x}, file = {filename}, line = {line}\n'
        print(text.format(s_id = sample.seqid, stype = sample.type, val = sample.val, pc = sample.pc, tid = sample.tid,\
                filename = sample.file, line = sample.line))

    def display_samples(self):
        print(self.datafile)
        for desc, s in self.sample_dict.items():
            print(desc)
            for sample in self.unfold_samples_for_desc(desc):
                self.print_sample(sample)

    def display_samples(self, outfile):
        with open(outfile, 'a') as f:
            for desc, s in self.sample_dict.items():
                f.write(f'{self.datafile}')
                f.write(f'{desc}\n')
                for sample in self.unfold_samples_for_desc(desc):
                    f.write(f'    timestamp = {sample.seqid}, type = {sample.type}, val = 0x{sample.val:x}, pc = 0x{sample.pc:x}, tid = 0x{sample.tid:x}, file = {sample.file}, line = {sample.line}\n')

    def display_fix_samples(self, func, var, outfile):
        with open(outfile, 'a') as f:
            for desc, s in self.sample_dict.items():
                if re.search(func, desc) and re.search(var, desc) :
                    f.write(f'{self.datafile}')
                    f.write(f'{desc}\n')
                    for sample in self.unfold_samples_for_desc(desc):
                        f.write(f'    timestamp = {sample.seqid}, type = {sample.type}, val = 0x{sample.val:x}, pc = 0x{sample.pc:x}, tid = 0x{sample.tid:x}, file = {sample.file}, line = {sample.line}\n')
                    return

class VarSamples:
    def __init__(self, directory, binary, maxcount, srcinfo):
        self.dir = directory
        self.bin = binary
        self.srcinfo = srcinfo
        self.max_count = maxcount
        self.samples = []
        self.collect_files()
        self.size = len(self.files_analyze)
        self.schemas = []
        #self.parse()

    def set_schemas(self):
        if len(self.samples) > 0:
            self.schemas = self.samples[0].schema_descs

    def get_size(self):
        self.size = len(self.samples)
        return self.size

    def parse_var_file(self, data_file):
        layout_file = data_file.replace('gmon_var', 'layout')
        layout = Layout(layout_file, self.bin)
        sample = VarSample(layout.get_schema_meta(), data_file)
        sample.layout_file = layout_file
        sample.srcinfo = self.srcinfo
        sample.translate_pc(layout)
        return sample

    def collect_files(self):
        files = []
        for datafile in glob.iglob(self.dir + '/**/gmon_var.*.out', recursive = True):
            files.append(datafile)

        files.sort()
        files_analyze = files
        if len(files) > self.max_count:
            files_analyze = files[0:self.max_count]
        self.files_analyze = files_analyze

    def parse(self):
        with Pool() as pool:
            self.samples = pool.map(self.parse_var_file, self.files_analyze)
        self.set_schemas()
        return self.samples

#check the result of recorded value samples
if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='calculate weight of variables on performance bugs by diffing among multiple runs')
    parser.add_argument('--norm_bin', required=True, help='')
    parser.add_argument('--bug_bin', required=True, help='')
    parser.add_argument('--norms', default = 'norms', help='')
    parser.add_argument('--bugs', default = 'bugs', help='')
    parser.add_argument('--norm_srcinfo', default='norm_srcinfo.txt')
    parser.add_argument('--bug_srcinfo', default='bug_srcinfo.txt')
    parser.add_argument('--max', default = 5, help = 'maximum number of samples supported to process')
    parser.add_argument('--output', help = 'file to store output data')
    parser.add_argument('--index')

    args = parser.parse_args()
    max_count = int(args.max)
    normSample = []
    bugSample = []

    norm_vars = VarSamples(args.norms, args.norm_bin, int(args.max), args.norm_srcinfo)
    bug_vars = VarSamples(args.bugs, args.bug_bin, int(args.max), args.bug_srcinfo)
    with Pool() as pool:
        norm_results = pool.map_async(norm_vars.parse_var_file, norm_vars.files_analyze)
        bug_results = pool.map_async(bug_vars.parse_var_file, bug_vars.files_analyze)
        pool.close()
        pool.join()
        norm_vars.samples = norm_results.get()
        bug_vars.samples = bug_results.get()

    for sample in bug_vars.samples:
        sample.print_info()
    for sample in norm_vars.samples:
        sample.print_info()

   # norm_vars.samples[0].print_info()
   # for sample in norm_vars.samples:
   #     sample.display_samples("var_samples.norms.txt")

   # for sample in bug_vars.samples:
   #     sample.display_samples("var_samples.bugs.txt")

