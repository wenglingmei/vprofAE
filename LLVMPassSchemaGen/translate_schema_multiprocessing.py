from __future__ import print_function
from collections import defaultdict
import os
import sys
import argparse
import re
import shlex
import subprocess

# If pyelftools is not installed, the example can also run from the root or
# examples/ dir of the source distribution.
sys.path[0:0] = ['.', '..']

from elftools.elf.elffile import ELFFile
from elftools.elf.sections import SymbolTableSection
from elftools.common.py3compat import itervalues
from elftools.dwarf.descriptions import (
    describe_DWARF_expr, set_global_machine_arch)
from elftools.dwarf.locationlists import (
    LocationEntry, LocationExpr, LocationParser)
from elftools.dwarf.descriptions import describe_form_class
from elftools.dwarf.dwarf_expr import DW_OP_name2opcode
from multiprocessing import Pool, cpu_count

symbol_tables = None
dwarfinfo = None
location_lists = None
range_lists = None
loc_parser = None

def symbol_addr_from_symtable(variable):
    for section_index, section in symbol_tables:
        if not isinstance(section, SymbolTableSection):
            continue
        if section['sh_entsize'] == 0:
            continue
        symbols =  section.get_symbol_by_name(variable)
        if symbols:
            return symbols[0].entry.st_value
        # base = map_base - elf_Phdr.p_vaddr(PT_LOAD DATA segment virtual address) ?= loadAddress
        # base + symbol.entry.st_value
    return None

def path_index(CU, directory, path):
    line_program = dwarfinfo.line_program_for_CU(CU)
    if line_program is None:
        print('  DWARF info is missing a line program for this CU')
        return None

    file_entries = line_program.header['file_entry']
    for lpe in line_program.get_entries():
        if not lpe.state or lpe.state.file == 0:
            continue
        file_entry = file_entries[lpe.state.file - 1]

        if os.path.basename(file_entry.name.decode()) == os.path.basename(path) or \
             os.path.basename(file_entry.name.decode()) == os.path.join(directory, path):
            return lpe.state.file
    return -1

def check_top_DIE_for_path(DIE, directory, path):
    if DIE.get_full_path() == path or DIE.get_full_path() == os.path.join(directory, path):
        return True
    elif (DIE.attributes.get('DW_AT_name', None).value.decode() == path or
            DIE.attributes.get('DW_AT_name', None).value.decode() == os.path.join(directory, path)):
        return True
    return False

def get_CU_for_path(directory, path):
    for CU in dwarfinfo.iter_CUs():
        if check_top_DIE_for_path(CU.get_top_DIE(), directory, path):
            index = path_index(CU, directory, path)
            if index != -1:
                return CU, index
    return None, None

def interpret_loclist(loclist, dwarfinfo, indent, cu_offset):
    result = []
    for loc_entity in loclist:
        if isinstance(loc_entity, LocationEntry):
            result.append('%s <<%s>>' % (
                loc_entity,
                describe_DWARF_expr(loc_entity.loc_expr, dwarfinfo.structs, cu_offset)))
        else:
            result.append(str(loc_entity))
    return result

def collect_location(DIE, CU):
    result = []
    for attr in itervalues(DIE.attributes):
    # Check if this attribute contains location information
        if loc_parser.attribute_has_location(attr, CU['version']):
            loc = loc_parser.parse_from_attribute(attr, CU['version'])
            if isinstance(loc, LocationExpr):
                result.append(describe_DWARF_expr(loc.loc_expr, dwarfinfo.structs, CU.cu_offset))
            elif isinstance(loc, list):
                result.extend(interpret_loclist(loc, dwarfinfo, '      ', CU.cu_offset))
    return result

def first_child(DIE):
    for child in DIE.iter_children():
        return child
    return None

def collect_type(DIE):
    base_DIE = DIE.get_DIE_from_attribute('DW_AT_type')
    try:
        while base_DIE.tag != 'DW_TAG_base_type' and base_DIE.tag != 'DW_TAG_pointer_type':
            #by default reference the first member in a structure type
            if base_DIE.tag == 'DW_TAG_structure_type':
                base_DIE = first_child(base_DIE)
            base_DIE = base_DIE.get_DIE_from_attribute('DW_AT_type')
        return base_DIE
    except:
        return None

#Variable location potential formats to processes:
#1. LocationEntry(entry_offset=33018411, begin_offset=14328925, \
#   end_offset=14328994,loc_expr=[48, 159]) <<(DW_OP_lit0; DW_OP_stack_value)>>
#2. LocationEntry(entry_offset=427334, begin_offset=4574818, \
#   end_offset=4574904, loc_expr=[243, 1, 85, 159]) \
#   <<(DW_OP_GNU_entry_value: (DW_OP_reg5 (r5)); DW_OP_stack_value)>>
#3. (DW_OP_fbreg: -32)
#4. (DW_OP_addr: 601018)
#5. (DW_OP_breg7 (rsp): 8)
#6. (DW_OP_GNU_entry_value: (DW_OP_reg2 (r2))) 

def parse_LocInfo(entry):
    loc = None
    addr = 0
    s_entry = entry
    pairs = re.search('DW_OP_GNU_entry_value: \((DW_OP_.*)\)\)', entry)
    if pairs:
        s_entry = pairs.group(1)
    #3. (DW_OP_fbreg: -32)
    #4. (DW_OP_addr: 601018)
    pairs = re.search('(DW_OP_[\w]+): ([-]?[0-9a-fA-F]+)', s_entry)
    if pairs:
        loc = pairs.group(1)
        if loc == 'DW_OP_addr':
             addr = int(pairs.group(2), 16)
        if loc == 'DW_OP_fbreg':
            addr = int(pairs.group(2), 10)
        return loc, addr
    #5. (DW_OP_breg7 (rsp): 8)
    pairs = re.search('(DW_OP_[\w]+) \(.*\): ([-\dabcdef]+)', s_entry)
    if pairs:
        loc = pairs.group(1)
        addr = int(pairs.group(2), 10)
        return loc, addr
    #6. (DW_OP_GNU_entry_value: (DW_OP_reg2 (r2))) 
    pairs = re.search('(DW_OP_[\w]+)[ ;|\)]', s_entry)
    if pairs:
        loc = pairs.group(1)
        return loc, addr
    #logging.debug('LocInfo: Fail to search loc_atom and offset in %s (%s)' % (entry, loc))
    return None, None

def parse_LocationEntry(entry, base_address):
    pairs = re.search('begin_offset=(\d+?), end_offset=(\d+?),.+ <<\((DW_OP_.+?)\)>>', entry)
    if not pairs:
        #logging.debug('LocationEntry: Fail to search begin_offset and end_offset in %s' % entry)
        return None, None, None, None
    begin_offset = int(pairs.group(1)) + base_address
    end_offset = int(pairs.group(2)) + base_address
    loc_atom, addr = parse_LocInfo(pairs.group(3))
    return begin_offset, end_offset, loc_atom, addr

def report_var_locs(CU, line, var, type_size, member_offset, result, pc_range):
    if not member_offset:
        member_offset = 0
    cu_low_pc = 0
    try:
        cu_low_pc = CU.get_top_DIE().attributes['DW_AT_low_pc'].value
    except:
        pass

    base_address = 0
    ret = []
    for entry in result:
        if 'BaseAddressEntry' in entry:
            base_addr = re.search('base_address=(\d+)', entry)
            base_address = int(base_addr.group(1))
        elif 'LocationEntry' in entry:
            begin_offset, end_offset, loc_atom, addr = parse_LocationEntry(entry, base_address)
            if begin_offset != None and loc_atom != None:
                ret.append(f'0x{begin_offset + cu_low_pc:x}:0x{end_offset + cu_low_pc:x}:{DW_OP_name2opcode[loc_atom]}:{addr + member_offset}:{type_size}\n')
                #print('0x%x:0x%x:%s:%d:%d' % (begin_offset + cu_low_pc, end_offset + cu_low_pc,\
                #        DW_OP_name2opcode[loc_atom], addr + member_offset, type_size))
        elif ':' in entry:
            loc, addr = parse_LocInfo(entry)
            if loc == None or addr == None:
                continue
            for begin_offset in pc_range:
                end_offset = pc_range[begin_offset]
                #print('0x%x:0x%x:%s:%d:%d' % (begin_offset, end_offset,\
                #            DW_OP_name2opcode[loc], addr + member_offset, type_size))
                ret.append(f'0x{begin_offset:x}:0x{end_offset:x}:{DW_OP_name2opcode[loc]}:{addr + member_offset}:{type_size}\n')
        #(DW_OP_reg2 (r2))
        else:
            pairs = re.search('(DW_OP_[0-9a-z]+)', entry)
            if not pairs:
                print('Fail to search loc_atom in %s' % entry)
                continue
            loc = pairs.group(1)
            addr = 0
            for begin_offset in pc_range:
                end_offset = pc_range[begin_offset]
                #print('0x%x:0x%x:%s:%d:%d' % (begin_offset, end_offset,\
                #            DW_OP_name2opcode[loc], addr + member_offset, type_size)) 
                ret.append(f'0x{begin_offset:x}:0x{end_offset:x}:{DW_OP_name2opcode[loc]}:{addr + member_offset}:{type_size}\n')

    return ret

def find_pc_range(DIE):
    pc_range = {}
    try:
        lowpc = DIE.attributes['DW_AT_low_pc'].value
        # DWARF v4 in section 2.17 describes how to interpret the
        # DW_AT_high_pc attribute based on the class of its form.
        # For class 'address' it's taken as an absolute address
        # (similarly to DW_AT_low_pc); for class 'constant', it's
        # an offset from DW_AT_low_pc.
        highpc_attr = DIE.attributes['DW_AT_high_pc']
        highpc_attr_class = describe_form_class(highpc_attr.form)
        if highpc_attr_class == 'address':
            highpc = highpc_attr.value
        elif highpc_attr_class == 'constant':
            highpc = lowpc + highpc_attr.value - 1
        pc_range[lowpc] = highpc
        return pc_range
    except KeyError:
        pass

    try:
        range_offset = DIE.attributes['DW_AT_ranges'].value
        rangelist = range_lists.get_range_list_at_offset(range_offset)
        cu_low_pc = DIE.cu.get_top_DIE().attributes['DW_AT_low_pc'].value
        for entry in rangelist:
            pc_range[entry[0] + cu_low_pc] = cu_low_pc + entry[1]
        return pc_range
    except KeyError:
        pass
    return pc_range

def pc_range_from_parent(DIE):
    parent = DIE.get_parent()
    if parent == None:
        return None
    ranges = find_pc_range(parent)
    if len(ranges) > 0:
        return ranges
    ranges = {}
    DIEs = DIEs_refer(DIE.cu.get_top_DIE(), DIE.offset)
    for entry in DIEs:
        ranges.update(pc_range_from_parent(entry))
    if len(ranges) > 0:
        return ranges
    return pc_range_from_parent(parent)


def DIEs_refer(root, offset):
    ret = []
    try:
        if root.attributes['DW_AT_abstract_origin'].value  + root.cu.cu_offset == offset:
            ret.append(root)
    except Exception as ex:
        pass

    for child in root.iter_children():
        child_ret = DIEs_refer(child, offset)
        if child_ret:
            ret.extend(child_ret)
    return ret

def dfs_DIE_for_var(root, line, func, variable):
    if root.tag == 'DW_TAG_variable' or root.tag == 'DW_TAG_formal_parameter':
        try:
            if root.attributes['DW_AT_name'].value.decode() == variable:
                if func.strip() == '#global' or root.attributes['DW_AT_decl_line'].value == int(line):
                    return root

        except Exception as ex:
            pass

    for child in root.iter_children():
        if func.strip() == '#global' and child.tag == 'DW_TAG_subprogram':
            continue

        ret = dfs_DIE_for_var(child, line, func, variable)
        if ret != None:
            return ret
    return None

def my_trans(name):
    if name is None:
        return None
    cmds = str('c++filt ') + name
    try:
        pipe = subprocess.Popen(shlex.split(cmds), stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        stdout, _ = pipe.communicate()
        reted = stdout.decode().split()
        pipe.kill()
        return reted[0]
    except Exception as ex:
        pass
    return None

def get_func_DIE_for_local_var(root, func):
    if root.tag == 'DW_TAG_subprogram':
        try:
            func_attr = root.attributes.get('DW_AT_name')
            if func_attr:
                if func_attr.value.decode() == func:
                    yield root
            func_die = root.get_DIE_from_attribute('DW_AT_specification')
            func_attr = func_die.attributes.get('DW_AT_linkage_name')
            func_signature = my_trans(func_attr.value.decode())
            pairs = re.search('([\w\d_:]+)\(.*', func_signature)
            if pairs and pairs.group(1) == func:
                yield root
        except Exception as ex:
            pass
    else:
        for child in root.iter_children():
            for ret in get_func_DIE_for_local_var(child, func):
                if ret != None:
                    yield ret
    yield None

def get_DIE_for_var(root, file_index, func, line, variable):
    if func.strip() != '#global' :
        for func_die in get_func_DIE_for_local_var(root, func):
            if func_die:
                ret = dfs_DIE_for_var(func_die, line, func, variable)
                if ret:
                    return ret
    else:
        for child in root.iter_children():
            #cut searching space for global variables
            if (child.tag == 'DW_TAG_subprogram'):
                #or child.attributes['DW_AT_decl_file'].value != file_index):
                continue
            ret = dfs_DIE_for_var(child, line, func, variable)
            if ret:
                return ret
    return None

def get_DIE_for_member(root, cur_member):
    for child in root.iter_children():
        if child.tag == 'DW_TAG_member':
            name = child.attributes.get('DW_AT_name', None)
            if name.value.decode() == cur_member:
                offset = child.attributes.get('DW_AT_data_member_location', None).value
                return child, offset

        if child.tag == 'DW_TAG_inheritance':
            init_offset = child.attributes.get('DW_AT_data_member_location', None).value
            base_DIE = child.get_DIE_from_attribute('DW_AT_type')
            if base_DIE and init_offset:
                ret_DIE, offset = get_DIE_for_member(base_DIE, cur_member)
                if ret_DIE and offset:
                    return ret_DIE, init_offset + offset
    return None, None      

def search_member_offset(var_DIE, member_name):
    root = var_DIE.get_DIE_from_attribute('DW_AT_type')
    if not root:
        return None
    try:
        root = root.get_DIE_from_attribute('DW_AT_type')
    except:
        pass

    cur_member = member_name
    sub_member = None
    fields = re.search('(\w+)[\\.]([\w\\.]+)', member_name)
    if fields:
        cur_member = fields.group(1)
        sub_member = fields.group(2)

    cur_DIE, offset = get_DIE_for_member(root, cur_member)
    
    if cur_DIE and offset and sub_member:
        sub_offset = search_member_offset(cur_DIE, sub_member)
        return offset + sub_offset

    return offset

def search_variable_live_locations(CU, line, variable, valtype, file_index, func, lineno):
    member = re.search('(\w+)[\\.]([\w\\.]+)', variable)
    member_offset = None
    if member:
        DIE = get_DIE_for_var(CU.get_top_DIE(), file_index, func, lineno, member.group(1))
        if DIE:
            member_offset = search_member_offset(DIE, member.group(2))
    else:
        DIE = get_DIE_for_var(CU.get_top_DIE(), file_index, func, lineno, variable)

    if not DIE:
        return None
    type_die = collect_type(DIE)

    try:
        type_size = type_die.attributes.get('DW_AT_byte_size', None).value
    except Exception as ex:
        type_size = 8

    pc_range = pc_range_from_parent(DIE)
    result = collect_location(DIE, CU)
    if result:
        ret_str = '#variable = '
        if type_die:
            ret_str = ret_str + type_die.tag + ' ' + line.rstrip()
        else:
            ret_str = ret_str + 'None ' + line.rstrip()
        ret_str = ret_str + '\n' + ''.join(report_var_locs(CU, line, variable, type_size, member_offset, result, pc_range))
        return ret_str

    if func.strip() == '#global':
        ret_str = '#variable = '
        if type_die:
            ret_str = ret_str + type_die.tag + ' ' + line.rstrip()
        else:
            ret_str = ret_str + 'None ' + line.rstrip()

        loc = 'DW_OP_addr'
        addr = symbol_addr_from_symtable(variable)
        if addr == None:
            return None
            #print('Fail to get address from symbol table')
        for begin_offset in pc_range:
            end_offset = pc_range[begin_offset]
            #print('0x%x:0x%x:%s:%d:%d' % (begin_offset, end_offset,\
            #    DW_OP_name2opcode[loc], addr, type_size))
            ret_str = ret_str + '\n' + f'0x{begin_offset:x}:0x{end_offset:x}:{DW_OP_name2opcode[loc]}:{addr}:{type_size}\n'
        return ret_str


    # No loc info inside the DIE, search DIEs refer to the current DIE with DW_AT_abstract_origin
    result = []
    pc_range.clear()
    ref_DIEs = DIEs_refer(CU.get_top_DIE(), DIE.offset)
    for entry in ref_DIEs:
        pc_range.update(pc_range_from_parent(entry))
        result.extend(collect_location(entry, CU))

    if len(result) > 0:
        ret_str = '#variable = '
        if type_die:
            ret_str = ret_str + type_die.tag + ' ' + line.rstrip()
        else:
            ret_str = ret_str + 'None ' + line.rstrip()
        ret_str = ret_str + '\n' + ''.join(report_var_locs(CU, line, variable, type_size, member_offset, result, pc_range))
        return ret_str

def parse_config_line(line):
    if re.search('^#', line):
        return None
    try:
        file_dir, file_path, func, lineno, variable, valtype, role = line.split()
    except:
        return None
    if not file_path or not func or not variable:
        #return f'Invalid config line: {line.rstrip()}'
        return None
    CU, file_index = get_CU_for_path(file_dir, file_path)
    if CU == None:
        #return f'No CU find for config line {line.rstrip()}, path = {file_path}'
        return None
    return search_variable_live_locations(CU, line, variable, valtype, file_index, func, lineno)    


def parse_config(schema_filename, outfile):
    if dwarfinfo == None:
        print('No dwarf info exist')
        return
    lines = []
    valueflows = []
    with open(schema_filename, 'r') as config_f:
        for line in config_f:
            if re.search('^#ValueFlow:', line):
                #return line.rstrip()
                valueflows.append(line)
            else:
                lines.append(line.rstrip())
        #lines = [line.rstrip() for line in config_f]

    out = open(outfile, "a")
    with Pool() as pool:
        res = pool.map(parse_config_line, lines)
        for item in res:
            if item:
                out.writelines(item)
                #print(item)
    out.writelines(valueflows)
    out.close()

def read_elf(elf_f):
    #with open(filename, 'rb') as elf_f:
    elffile = ELFFile(elf_f)
    if not elffile.has_dwarf_info():
        print('File %s has no DWARF info.' % filename)
        return
    global dwarfinfo
    global location_lists
    global range_lists
    global loc_parser
    global symbol_tables
    dwarfinfo = elffile.get_dwarf_info()
    location_lists = dwarfinfo.location_lists()
    range_lists = dwarfinfo.range_lists()
    loc_parser = LocationParser(location_lists)
    symbol_tables = [(idx, s) for idx, s in enumerate(elffile.iter_sections())
            if isinstance(s, SymbolTableSection)]
    if not symbol_tables and elffile.num_sections() == 0:
        print('Fail to get symbol_tables')

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Translate variables into location offset/register in execution')
    parser.add_argument('--elf', required=True, help='object files with debugging infomation')
    parser.add_argument('--schema', required=True, help='''schema file with variables required value sampling.
        Each line is formatted with [path func line variable type]''')
    parser.add_argument('--out', required=True, help='output file to save meta data translated from schema(--schema)' )
    parser.add_argument('--exec', help='process name the schema is generated for')

    args = parser.parse_args()
    
    if args.exec:
        out = open(args.out, "w")
        out.write('#{}\n'.format(args.exec))
        out.close()

    with open(args.elf, 'rb') as elf_f:
        read_elf(elf_f)
        parse_config(args.schema, args.out)
    
