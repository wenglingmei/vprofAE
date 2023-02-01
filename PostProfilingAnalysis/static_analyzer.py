import os
import os.path
import sys
import glob
import argparse
import re

from collections import namedtuple
import struct
import operator

# If pyelftools is not installed, the example can also run from the root or
# examples/ dir of the source distribution.
sys.path[0:0] = ['.', '..']

from elftools.common.py3compat import maxint, bytes2str
from elftools.dwarf.descriptions import describe_form_class
from elftools.elf.elffile import ELFFile

#import logging
#FORMAT = '%(asctime)s %(message)s'
#logging.basicConfig(filename='debug_static_analysis.log', format=FORMAT, level=logging.CRITICAL)

regx_desc = '#variable = (\w+) ([\/\w\. #\,\*|:<>_-]+)'
key_desc = namedtuple('key_desc', 'dir, file, function, line, symbol, type, tags')
func_index = 2
line_index = 3
symbol_index = 4
max_ip_offset = 6
AddressEntry = namedtuple('AddressEntry', ['begin', 'end', 'file', 'line'])

class ValueFlow:
    def __init__(self, schema_file):
        self.in_file = schema_file

    def var_desc_to_key(self, var_desc):
        ret = re.search(regx_desc, var_desc)
        try:
            var_type = ret.group(1)
            var_info = ret.group(2)
            fields = var_info.split()
            dictionary = key_desc(*fields)
            return dictionary.file.split('/')[-1] + ':' + dictionary.function + ':' + dictionary.symbol + ':' + dictionary.tags, dictionary
        except Exception as ex:
            print(f'parsing var_desc {var_desc} : {ex}')
            if ret:
                print(f'fail to parse {fields}')
        return None, None

    def valueflow_desc_to_key(self, vf_desc):
        try:
            dictionary = dict(subString.split('=') for subString in line.split(','))
            return dictionary['path'].split('/')[-1] + ':' + dictionary['func'] + ':' + dictionary['var'], dictionary
        except Exception as ex:
            return None, None

    def parse_value_flow(self):
        value_flow_dict = {}
        with open(self.in_file, 'r') as f:
            for line in f:
                line = line.rstrip()
                if not re.search('#ValueFlow:', line):
                    continue
                vf_desc = line[len('#ValueFlow:'):];
                key, dictionary = self.valueflow_desc_to_key(vf_desc)
                if not key:
                    continue
                if key not in value_flow_dict:
                    value_flow_dict[key] = []
                value_flow_dict[key].append(dictionary)
        return value_flow_dict

class Layout:
    def __init__(self, conf_file, exec_file):
        self.conf_file = conf_file
        self.exec_file = exec_file
        self.value_flow = ValueFlow(conf_file)
        self.path = {}
        self.addr_map = []
        self.schema_meta_items = []
        self.parse_schema_meta()
        if self.exec_file and os.path.isfile(self.exec_file):
            self.process_elf()
        else:
            self.dwarfinfo = None
        self.value_flow_dict = self.value_flow.parse_value_flow()

    def parse_schema_meta(self):
        """parse the saved layout of variable samples
        schema_meta_items is a list. Each elemen is a sublist
        ([schema_desc, dictionary1_for_atomic1, dictionary2_for_atomic2, ...]);
        The sublist corresponds to the translated layout of variable from schema.
        """
        with open(self.conf_file, 'r') as f:
            next(f)
            for line in f:
                line = line.rstrip()
                if re.search(regx_desc, line):
                    key, dictionary = self.value_flow.var_desc_to_key(line)
                    self.path[dictionary.dir+ '/'+ dictionary.file] = dictionary.file
                    self.schema_meta_items.append([(key, line)])
                elif re.search('^#', line):
                    continue
                else:
                    dictionary = dict(subString.split('=') for subString in line.split(','))
                    self.schema_meta_items[-1].append(dictionary)
        return self.schema_meta_items

    def get_schema_meta(self):
        return self.schema_meta_items
    
    def process_elf(self):
        """get_dwarf_info returns a DWARFInfo context object, which is the
        ostarting point for all DWARF-based processing in pyelftools.
        """
        with open(self.exec_file, 'rb') as f:
            elffile = ELFFile(f)
            if not elffile.has_dwarf_info():
                print('  file has no DWARF info')
                return
            self.dwarfinfo = elffile.get_dwarf_info()
            self.dump_address_map()

    def dump_address_map(self):
        """Go over all the line programs in the DWARF information, looking for
        one that describes the addresses from the given component.
        """
        if self.dwarfinfo is None:
            return
        def dump_address_map_file(target_path, target_fullpath):
            #print(f'dump address map for {target_path} and {target_fullpath}')
            for CU in self.dwarfinfo.iter_CUs():
                DIE = CU.get_top_DIE()
                if DIE.get_full_path() != target_path and DIE.get_full_path() != target_fullpath:
                    #print(f'{DIE.get_full_path()} != {target_path} and {DIE.get_full_path()} != {target_fullpath}')
                    continue
                # First, look at line programs to find the file/line for the address
                lineprog = self.dwarfinfo.line_program_for_CU(CU)
                prevstate = None
                for entry in lineprog.get_entries():
                    # We're interested in those entries where a new state is assigned
                    if entry.state is None:
                        continue
                    if prevstate:
                        filename = lineprog['file_entry'][prevstate.file - 1].name.decode()
                        line = prevstate.line
                        address_entry = AddressEntry(prevstate.address, entry.state.address, filename, line)
                        self.addr_map.append(address_entry)
                    if entry.state.end_sequence:
                        prevstate = None
                    else:
                        prevstate = entry.state

        for full_path, path in self.path.items():
            dump_address_map_file(path, full_path)
        self.addr_map.sort(key = lambda x: x[0])

    def decode_files_lines(self, addresses):
        def next_addr(index):
            index = index + 1
            if index < len(addresses):
                return index
            return -1

        map_to_line = {}
        map_to_file = {}
        if len(self.addr_map) == 0:
            print('Address map(line prog) is not initialized')
            return map_to_line, map_to_file

        addresses.sort()
        index = 0
        address = addresses[index]
        for entry in self.addr_map:
            if address - max_ip_offset > entry.end:
                continue
            while address < entry.begin:
                index = next_addr(index)
                if index == -1:
                    return map_to_line, map_to_file
                address = addresses[index]
            while entry.begin <= address and entry.end > address - max_ip_offset:
                map_to_file[address] = entry.file
                map_to_line[address] = entry.line
                index = next_addr(index)
                if index == -1:
                    return map_to_line, map_to_file
                address = addresses[index]
        return map_to_line, map_to_file

    def attach_value_flow(self, var_desc, value_sample):
        key, dictionary = self.value_flow.var_desc_to_key(var_desc)
        decl_line = dictionary.line
        attached = False
        if key not in self.value_flow_dict:
            return
        for vf_entry in self.value_flow_dict[key]:
            if vf_entry['line'] < decl_line or int(value_sample.line) < vf_entry['line']:
                continue
            loc_entry.propagate.insert(vf_entry['srcF'])
            attached = True
        return attached
